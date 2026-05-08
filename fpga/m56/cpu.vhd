-- cpu.vhd — M56 CPU core
--
-- Four-state pipeline: FETCH → EXEC → (LOAD | STORE) → FETCH → ...
--
-- Timing contract with the synchronous BRAM:
--   The address for instruction N must be stable for a full cycle BEFORE the
--   FETCH edge so that bram_rdat is valid when EXEC begins.
--   EXEC (and LOAD/STORE) set mem_addr to the next fetch address at their
--   ending edge.  FETCH is then a pure wait: it does not touch mem_addr or
--   mem_re, so the BRAM reads the correct address at the FETCH edge.
--
-- PC convention (regs(15)):
--   FETCH sets regs(15) := mem_addr + 4.  While EXEC is running,
--   regs(15) is therefore the address of the instruction *after* the one
--   being executed — matching the assembler's offset convention.
--
-- STORE state exists because an indirect write puts the peripheral/BRAM
-- address in mem_addr.  STORE clears mem_we and redirects mem_addr to
-- the next fetch address before handing off to FETCH.

library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;

entity m56_cpu is
    port (
        clk      : in  STD_LOGIC;
        resetn   : in  STD_LOGIC;
        mem_addr : out STD_LOGIC_VECTOR(31 downto 0);
        mem_rdat : in  STD_LOGIC_VECTOR(31 downto 0);
        mem_wdat : out STD_LOGIC_VECTOR(31 downto 0);
        mem_we   : out STD_LOGIC;
        mem_re   : out STD_LOGIC
    );
end entity m56_cpu;

architecture rtl of m56_cpu is

    type regfile_t is array(0 to 15) of std_logic_vector(31 downto 0);
    signal regs : regfile_t := (
        14 => x"0007FFFC",
        15 => x"00000000",
        others => (others => '0')
    );

    type state_t is (FETCH, EXEC, LOAD, STORE);
    signal state    : state_t := FETCH;
    signal load_dst : integer range 0 to 15;

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
        variable vreg    : integer range 0 to 15;
        variable vrdst   : integer range 0 to 15;
        variable take    : boolean;
        variable next_pc : std_logic_vector(31 downto 0);
    begin
        if resetn = '0' then
            regs     <= (
                14 => x"0007FFFC",
                15 => x"00000000",
                others => (others => '0')
            );
            state    <= FETCH;
            mem_addr <= (others => '0');
            mem_wdat <= (others => '0');
            mem_we   <= '0';
            mem_re   <= '1';   -- prime BRAM for first fetch at address 0

        elsif rising_edge(clk) then

            case state is

                -- FETCH: BRAM is sampling mem_addr at this edge.
                -- Do not touch mem_addr or mem_re.
                -- Derive PC as fetch-address + 4.
                when FETCH =>
                    mem_we   <= '0';
                    regs(15) <= std_logic_vector(unsigned(mem_addr) + 4);
                    state    <= EXEC;

                when EXEC =>
                    mem_we <= '0';
                    mem_re <= '0';

                    vreg  := to_integer(unsigned(d_reg));
                    vrdst := to_integer(unsigned(d_imm19(3 downto 0)));

                    if d_is_mov = '1' then
                        case d_mode is

                            when "0001" =>  -- mov-h #imm19, Rdst
                                regs(vreg) <= d_imm19 & "0000000000000";
                                mem_addr <= regs(15);
                                mem_re   <= '1';
                                state    <= FETCH;

                            when "0010" =>  -- mov Rsrc, Rdst
                                regs(vrdst) <= regs(vreg);
                                mem_addr <= regs(15);
                                mem_re   <= '1';
                                state    <= FETCH;

                            when "0011" =>  -- mov [Rsrc], Rdst  (indirect read)
                                mem_addr <= regs(vreg);
                                mem_re   <= '1';
                                load_dst <= vrdst;
                                state    <= LOAD;

                            when "0100" =>  -- mov Rsrc, [Rdst]  (indirect write)
                                mem_addr <= regs(vrdst);
                                mem_wdat <= regs(vreg);
                                mem_we   <= '1';
                                state    <= STORE;

                            when others =>
                                mem_addr <= regs(15);
                                mem_re   <= '1';
                                state    <= FETCH;
                        end case;

                    elsif d_is_alu = '1' then
                        case d_opcode is
                            when "00010" => regs(vreg) <= std_logic_vector(unsigned(regs(vreg)) + unsigned(d_imm32));
                            when "00011" => regs(vreg) <= std_logic_vector(unsigned(regs(vreg)) - unsigned(d_imm32));
                            when "00100" => regs(vreg) <= regs(vreg) and d_imm32;
                            when "00101" => regs(vreg) <= regs(vreg) or  d_imm32;
                            when "00110" => regs(vreg) <= regs(vreg) xor d_imm32;
                            when others  => null;
                        end case;
                        mem_addr <= regs(15);
                        mem_re   <= '1';
                        state    <= FETCH;

                    elsif d_is_jpr = '1' then
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
                            next_pc  := std_logic_vector(unsigned(regs(15)) + unsigned(d_imm32));
                            mem_addr <= next_pc;
                        else
                            mem_addr <= regs(15);
                        end if;
                        mem_re <= '1';
                        state  <= FETCH;

                    else
                        mem_addr <= regs(15);
                        mem_re   <= '1';
                        state    <= FETCH;
                    end if;

                -- Capture indirect-read data; pre-load next fetch address.
                when LOAD =>
                    regs(load_dst) <= mem_rdat;
                    mem_addr <= regs(15);
                    mem_re   <= '1';
                    state    <= FETCH;

                -- Clear write-enable; redirect mem_addr to next fetch address.
                -- uart_wr / mem_we is high for exactly this one cycle (set by EXEC).
                when STORE =>
                    mem_we   <= '0';
                    mem_addr <= regs(15);
                    mem_re   <= '1';
                    state    <= FETCH;

            end case;
        end if;
    end process;

end architecture rtl;
