-- cpu.vhd — M56 CPU core
--
-- Implements the subset required by firmware/echo.s:
--   mov (modes 1-4), and (mode 0), jpr (.al / .z / .nz / .n / .nn)
--
-- Three-state pipeline:  FETCH → EXEC → LOAD
-- LOAD is only entered for indirect reads (mov mode 3).
-- All other instructions complete in two cycles (FETCH + EXEC).
--
-- Memory interface is word-addressed via a 32-bit bus.
-- Address decoding (BRAM vs UART vs other peripherals) lives in the top level.

library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;

entity m56_cpu is
    port (
        clk      : in  STD_LOGIC;
        resetn   : in  STD_LOGIC;             -- active-low
        -- Memory / peripheral bus
        mem_addr : out STD_LOGIC_VECTOR(31 downto 0);
        mem_rdat : in  STD_LOGIC_VECTOR(31 downto 0);
        mem_wdat : out STD_LOGIC_VECTOR(31 downto 0);
        mem_we   : out STD_LOGIC;             -- write enable, one-cycle pulse
        mem_re   : out STD_LOGIC              -- read enable (address is valid)
    );
end entity m56_cpu;

architecture rtl of m56_cpu is

    -- 16 × 32-bit register file.  R14 = SP, R15 = PC.
    type regfile_t is array(0 to 15) of std_logic_vector(31 downto 0);
    signal regs : regfile_t := (
        14 => x"0007FFFC",   -- SP: top of RAM
        15 => x"00000000",   -- PC: reset vector
        others => (others => '0')
    );

    type state_t is (FETCH, EXEC, LOAD);
    signal state    : state_t := FETCH;
    signal load_dst : integer range 0 to 15;

    -- Decoder outputs (combinational from mem_rdat)
    signal d_opcode   : std_logic_vector(4 downto 0);
    signal d_mode     : std_logic_vector(3 downto 0);
    signal d_reg      : std_logic_vector(3 downto 0);
    signal d_imm19    : std_logic_vector(18 downto 0);
    signal d_imm32    : std_logic_vector(31 downto 0);
    signal d_is_mov   : std_logic;
    signal d_is_alu   : std_logic;
    signal d_is_jpr   : std_logic;
    signal d_jmp_sub  : std_logic;
    signal d_jmp_cond : std_logic_vector(2 downto 0);

begin

    dec: entity work.M56_Decoder
        port map (
            instr    => mem_rdat,
            opcode   => d_opcode,
            mode     => d_mode,
            reg      => d_reg,
            imm19    => d_imm19,
            imm32    => d_imm32,
            is_mov   => d_is_mov,
            is_mvb   => open,
            is_alu   => d_is_alu,
            is_not   => open,
            is_shf   => open,
            is_sar   => open,
            is_jmp   => open,
            is_jpr   => d_is_jpr,
            is_wfi   => open,
            is_eai   => open,
            is_dai   => open,
            jmp_sub  => d_jmp_sub,
            jmp_cond => d_jmp_cond
        );

    process(clk, resetn)
        variable vreg  : integer range 0 to 15;
        variable vrdst : integer range 0 to 15;
        variable take  : boolean;
    begin
        if resetn = '0' then
            regs <= (
                14 => x"0007FFFC",
                15 => x"00000000",
                others => (others => '0')
            );
            state    <= FETCH;
            mem_addr <= (others => '0');
            mem_wdat <= (others => '0');
            mem_we   <= '0';
            mem_re   <= '1';

        elsif rising_edge(clk) then
            mem_we <= '0';   -- default: no write this cycle
            mem_re <= '0';   -- default: no read  this cycle

            case state is

                -- Issue read at current PC; advance PC.
                when FETCH =>
                    mem_addr <= regs(15);
                    mem_re   <= '1';
                    regs(15) <= std_logic_vector(unsigned(regs(15)) + 4);
                    state    <= EXEC;

                -- Instruction is on mem_rdat; decoder outputs are valid.
                when EXEC =>
                    vreg  := to_integer(unsigned(d_reg));
                    vrdst := to_integer(unsigned(d_imm19(3 downto 0)));

                    if d_is_mov = '1' then
                        case d_mode is
                            when "0001" =>   -- mov-h #imm19, Rdst
                                regs(vreg) <= d_imm19 & "0000000000000";
                                state <= FETCH;

                            when "0010" =>   -- mov Rsrc, Rdst
                                regs(vrdst) <= regs(vreg);
                                state <= FETCH;

                            when "0011" =>   -- mov [Rsrc], Rdst  (indirect read)
                                mem_addr <= regs(vreg);
                                mem_re   <= '1';
                                load_dst <= vrdst;
                                state    <= LOAD;

                            when "0100" =>   -- mov Rsrc, [Rdst]  (indirect write)
                                mem_addr <= regs(vrdst);
                                mem_wdat <= regs(vreg);
                                mem_we   <= '1';
                                state    <= FETCH;

                            when others =>
                                state <= FETCH;
                        end case;

                    elsif d_is_alu = '1' then
                        -- ALU mode 0: Rdst = Rdst op sign_extend(imm19)
                        case d_opcode is
                            when "00010" => regs(vreg) <= std_logic_vector(unsigned(regs(vreg)) + unsigned(d_imm32));
                            when "00011" => regs(vreg) <= std_logic_vector(unsigned(regs(vreg)) - unsigned(d_imm32));
                            when "00100" => regs(vreg) <= regs(vreg) and d_imm32;
                            when "00101" => regs(vreg) <= regs(vreg) or  d_imm32;
                            when "00110" => regs(vreg) <= regs(vreg) xor d_imm32;
                            when others  => null;
                        end case;
                        state <= FETCH;

                    elsif d_is_jpr = '1' then
                        -- regs(15) = original_PC + 4; offset is relative to that.
                        take := false;
                        case d_jmp_cond is
                            when "000" => take := true;
                            when "001" => take := (regs(vreg) = x"00000000");
                            when "010" => take := (regs(vreg) /= x"00000000");
                            when "011" => take := (regs(vreg)(31) = '1');
                            when "100" => take := (regs(vreg)(31) = '0');
                            when others => null;
                        end case;
                        if take then
                            regs(15) <= std_logic_vector(
                                unsigned(regs(15)) + unsigned(d_imm32));
                        end if;
                        state <= FETCH;

                    else
                        state <= FETCH;
                    end if;

                -- Data from indirect read is ready on mem_rdat.
                when LOAD =>
                    regs(load_dst) <= mem_rdat;
                    state <= FETCH;

            end case;
        end if;
    end process;

end architecture rtl;
