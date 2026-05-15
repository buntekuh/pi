-- cpu.vhd — M56 CPU core
--
-- The CPU has 16 registers (R0-R15), each 32 bits wide.
-- R14 is the stack pointer (SP).  R15 is the program counter (PC).
--
-- The CPU talks to the outside world through a simple memory bus:
--   memory_address    — the address the CPU wants to read from or write to
--   memory_read_data  — data coming back from memory (or a peripheral)
--   memory_write_data — data the CPU wants to write
--   memory_write_enable — '1' for one clock cycle when writing
--   memory_read_enable  — '1' for one clock cycle when reading
--
-- ─── Instruction format ──────────────────────────────────────────────────────
--
--   Bit  31..27   opcode  (5 bits)
--   Bit  26..24   mode    (3 bits)   — addressing mode or condition code
--   Bit  23..20   register(4 bits)
--   Bit  19..0    imm20  (20 bits)   — immediate, offset, or 2nd register
--
-- ─── Byte order (endianness) ───────────────────────────────────────────────
--
-- The M56 is big-endian: the most significant byte of a multi-byte value
-- is stored at the lowest memory address.
--
-- In practice: a 32-bit value 0x12345678 stored at address N occupies:
--   N+0 = 0x12  (most significant byte)
--   N+1 = 0x34
--   N+2 = 0x56
--   N+3 = 0x78  (least significant byte)
--
-- ─── Four-state execution cycle ────────────────────────────────────────────
--
--   FETCH  → present instruction address to Block RAM, compute PC = addr + 4
--   EXEC   → Block RAM data is ready; decode and execute the instruction
--   LOAD   → (indirect reads only) capture data from memory_read_data into a register
--   STORE  → (indirect writes only) clear write-enable, redirect to next fetch

library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;

entity m56_cpu is
    port (
        clk      : in  STD_LOGIC;
        resetn   : in  STD_LOGIC;             -- active low: '0' = reset, '1' = running

        -- Memory / peripheral bus
        memory_address      : out STD_LOGIC_VECTOR(31 downto 0);
        memory_read_data    : in  STD_LOGIC_VECTOR(31 downto 0);
        memory_write_data   : out STD_LOGIC_VECTOR(31 downto 0);
        memory_write_enable : out STD_LOGIC;
        memory_read_enable  : out STD_LOGIC;

        -- Interrupt interface
        interrupt_request    : in  STD_LOGIC;
        irq_status           : in  STD_LOGIC_VECTOR(31 downto 0);
        interrupts_enabled   : out STD_LOGIC;

        -- Stall: asserted by slow peripherals (e.g. SRAM controller)
        memory_stall         : in  STD_LOGIC
    );
end entity m56_cpu;

architecture rtl of m56_cpu is

    -- 16 × 32-bit register file.
    -- R14 = stack pointer (top of SRAM), R15 = program counter.
    type register_file_type is array(0 to 15) of std_logic_vector(31 downto 0);
    signal registers : register_file_type := (
        14 => x"000BFFFC",   -- SP starts at top of SRAM
        15 => x"00000000",   -- PC starts at address 0
        others => (others => '0')
    );

    -- Execution state machine.
    -- CALL_STORE mirrors INTERRUPT_ENTRY: completes a stack push for bra/bar.
    type state_type is (FETCH, EXEC, LOAD_WAIT, LOAD, STORE, INTERRUPT_ENTRY, CALL_STORE);
    signal state            : state_type := FETCH;
    signal load_destination : integer range 0 to 15;
    signal load_is_byte     : std_logic := '0';
    signal call_target      : std_logic_vector(31 downto 0);

    -- Decoder output signals — wired from the decoder module below.
    -- These are combinational: they update instantly when memory_read_data changes.
    -- During EXEC, memory_read_data holds the current instruction.
    signal d_opcode   : std_logic_vector(4 downto 0);
    signal d_mode     : std_logic_vector(2 downto 0);
    signal d_reg      : std_logic_vector(3 downto 0);
    signal d_imm20    : std_logic_vector(19 downto 0);
    signal d_imm32    : std_logic_vector(31 downto 0);
    signal d_is_mov   : std_logic;
    signal d_is_mvb   : std_logic;
    signal d_is_alu   : std_logic;
    signal d_is_not   : std_logic;
    signal d_is_shf   : std_logic;
    signal d_is_sar   : std_logic;
    signal d_is_jmp   : std_logic;
    signal d_is_jpr   : std_logic;
    signal d_is_bra   : std_logic;
    signal d_is_bar   : std_logic;
    signal d_is_wfi   : std_logic;
    signal d_is_eai   : std_logic;
    signal d_is_dai   : std_logic;
    signal d_is_rti   : std_logic;
    signal d_jmp_cond : std_logic_vector(2 downto 0);

    -- Interrupt enable flag.  Starts disabled at reset.
    signal interrupts_enabled_reg : std_logic := '0';

begin

    interrupts_enabled <= interrupts_enabled_reg;

    -- ── Decoder ─────────────────────────────────────────────────────────────
    dec: entity work.M56_Decoder
        port map (
            instruction => memory_read_data,
            opcode   => d_opcode,
            mode     => d_mode,
            regn     => d_reg,
            imm20    => d_imm20,
            imm32    => d_imm32,
            is_mov   => d_is_mov,
            is_mvb   => d_is_mvb,
            is_alu   => d_is_alu,
            is_not   => d_is_not,
            is_shf   => d_is_shf,
            is_sar   => d_is_sar,
            is_jmp   => d_is_jmp,
            is_jpr   => d_is_jpr,
            is_bra   => d_is_bra,
            is_bar   => d_is_bar,
            is_wfi   => d_is_wfi,
            is_eai   => d_is_eai,
            is_dai   => d_is_dai,
            is_rti   => d_is_rti,
            jmp_cond => d_jmp_cond
        );

    -- ── Main clocked process ─────────────────────────────────────────────────
    process(clk, resetn)
        variable register_index       : integer range 0 to 15;
        variable destination_register : integer range 0 to 15;
        variable take_branch          : boolean;
        variable next_pc              : std_logic_vector(31 downto 0);
        variable alu_src              : std_logic_vector(31 downto 0);
        variable shift_count          : integer range 0 to 31;
    begin

        if resetn = '0' then
            registers <= (
                14 => x"000BFFFC",   -- SP = top of SRAM
                15 => x"00000000",   -- PC = address 0
                others => (others => '0')
            );
            state               <= FETCH;
            memory_address      <= (others => '0');
            memory_write_data   <= (others => '0');
            memory_write_enable <= '0';
            memory_read_enable  <= '1';
            interrupts_enabled_reg <= '0';
            load_is_byte        <= '0';

        elsif rising_edge(clk) then

            case state is

                -- ── FETCH ───────────────────────────────────────────────────
                -- Block RAM is sampling memory_address at this edge and will
                -- have data ready next cycle.  Advance PC and go to EXEC.
                when FETCH =>
                    memory_write_enable <= '0';
                    registers(15) <= std_logic_vector(unsigned(memory_address) + 4);
                    state <= EXEC;

                -- ── EXEC ────────────────────────────────────────────────────
                when EXEC =>
                    memory_write_enable <= '0';
                    memory_read_enable  <= '0';

                    register_index        := to_integer(unsigned(d_reg));
                    destination_register  := to_integer(unsigned(d_imm20(3 downto 0)));

                    -- ── Interrupt check ──────────────────────────────────────
                    if interrupt_request = '1' and interrupts_enabled_reg = '1' then
                        registers(14) <= std_logic_vector(unsigned(registers(14)) - 4);
                        memory_address    <= std_logic_vector(unsigned(registers(14)) - 4);
                        memory_write_data <= registers(15);
                        memory_write_enable <= '1';
                        registers(13) <= irq_status;
                        interrupts_enabled_reg <= '0';
                        state <= INTERRUPT_ENTRY;

                    -- ── mov family ──────────────────────────────────────────
                    elsif d_is_mov = '1' then
                        case d_mode is

                            -- mov #imm20, Rdst  (mode 0) — sign-extended immediate
                            when "000" =>
                                registers(register_index) <= d_imm32;
                                memory_address     <= registers(15);
                                memory_read_enable <= '1';
                                state <= FETCH;

                            -- mov-h #imm20, Rdst  (mode 1) — load into bits 31..12
                            when "001" =>
                                registers(register_index) <= d_imm20 & "000000000000";
                                memory_address     <= registers(15);
                                memory_read_enable <= '1';
                                state <= FETCH;

                            -- mov Rsrc, Rdst  (mode 2) — register copy
                            when "010" =>
                                registers(destination_register) <= registers(register_index);
                                memory_address     <= registers(15);
                                memory_read_enable <= '1';
                                state <= FETCH;

                            -- mov [Rsrc], Rdst  (mode 3) — indirect read
                            -- Peripherals (bit 22 = 1): combinatorial data, skip LOAD_WAIT.
                            -- BRAM/SRAM: registered, go through LOAD_WAIT.
                            when "011" =>
                                memory_address     <= registers(register_index);
                                memory_read_enable <= '1';
                                load_destination   <= destination_register;
                                if registers(register_index)(22) = '1' then
                                    state <= LOAD;
                                else
                                    state <= LOAD_WAIT;
                                end if;

                            -- mov Rsrc, [Rdst]  (mode 4) — indirect write
                            when "100" =>
                                memory_address      <= registers(destination_register);
                                memory_write_data   <= registers(register_index);
                                memory_write_enable <= '1';
                                state <= STORE;

                            when others =>
                                memory_address     <= registers(15);
                                memory_read_enable <= '1';
                                state <= FETCH;
                        end case;

                    -- ── mvb — byte move ──────────────────────────────────────
                    elsif d_is_mvb = '1' then
                        case d_mode is
                            when "011" =>   -- mvb [Rsrc], Rdst — byte read
                                memory_address     <= registers(register_index);
                                memory_read_enable <= '1';
                                load_destination   <= destination_register;
                                load_is_byte       <= '1';
                                if registers(register_index)(22) = '1' then
                                    state <= LOAD;
                                else
                                    state <= LOAD_WAIT;
                                end if;
                            when "100" =>   -- mvb Rsrc, [Rdst] — byte write
                                memory_address      <= registers(destination_register);
                                memory_write_data   <= (31 downto 8 => '0') & registers(register_index)(7 downto 0);
                                memory_write_enable <= '1';
                                state <= STORE;
                            when "101" =>   -- mvb #imm, [Rdst] — immediate byte write
                                memory_address      <= registers(register_index);
                                memory_write_data   <= (31 downto 8 => '0') & d_imm20(7 downto 0);
                                memory_write_enable <= '1';
                                state <= STORE;
                            when others =>
                                memory_address     <= registers(15);
                                memory_read_enable <= '1';
                                state <= FETCH;
                        end case;

                    -- ── ALU family ───────────────────────────────────────────
                    -- add, sub, and, orr, xor  (opcodes 2-6)
                    -- Mode 010: second operand from register.
                    -- Otherwise: sign-extended imm20.
                    elsif d_is_alu = '1' then
                        if d_mode = "010" then
                            alu_src := registers(destination_register);
                        else
                            alu_src := d_imm32;
                        end if;
                        case d_opcode is
                            when "00010" => registers(register_index) <= std_logic_vector(unsigned(registers(register_index)) + unsigned(alu_src));
                            when "00011" => registers(register_index) <= std_logic_vector(unsigned(registers(register_index)) - unsigned(alu_src));
                            when "00100" => registers(register_index) <= registers(register_index) and alu_src;
                            when "00101" => registers(register_index) <= registers(register_index) or  alu_src;
                            when "00110" => registers(register_index) <= registers(register_index) xor alu_src;
                            when others  => null;
                        end case;
                        memory_address     <= registers(15);
                        memory_read_enable <= '1';
                        state <= FETCH;

                    -- ── not — bitwise NOT ────────────────────────────────────
                    elsif d_is_not = '1' then
                        registers(register_index) <= not registers(register_index);
                        memory_address     <= registers(15);
                        memory_read_enable <= '1';
                        state <= FETCH;

                    -- ── shf — logical shift ───────────────────────────────────
                    elsif d_is_shf = '1' then
                        if d_mode = "010" then
                            if registers(destination_register)(31) = '0' then
                                shift_count := to_integer(unsigned(registers(destination_register)(4 downto 0)));
                                registers(register_index) <= std_logic_vector(shift_left(unsigned(registers(register_index)), shift_count));
                            else
                                shift_count := to_integer(unsigned(not registers(destination_register)(4 downto 0)) + 1);
                                registers(register_index) <= std_logic_vector(shift_right(unsigned(registers(register_index)), shift_count));
                            end if;
                        else
                            if d_imm20(19) = '0' then
                                shift_count := to_integer(unsigned(d_imm20(4 downto 0)));
                                registers(register_index) <= std_logic_vector(shift_left(unsigned(registers(register_index)), shift_count));
                            else
                                shift_count := to_integer(unsigned(not d_imm20(4 downto 0)) + 1);
                                registers(register_index) <= std_logic_vector(shift_right(unsigned(registers(register_index)), shift_count));
                            end if;
                        end if;
                        memory_address     <= registers(15);
                        memory_read_enable <= '1';
                        state <= FETCH;

                    -- ── sar — arithmetic shift right ──────────────────────────
                    elsif d_is_sar = '1' then
                        if d_mode = "010" then
                            shift_count := to_integer(unsigned(registers(destination_register)(4 downto 0)));
                        else
                            shift_count := to_integer(unsigned(d_imm20(4 downto 0)));
                        end if;
                        registers(register_index) <= std_logic_vector(shift_right(signed(registers(register_index)), shift_count));
                        memory_address     <= registers(15);
                        memory_read_enable <= '1';
                        state <= FETCH;

                    -- ── jmp / bra — absolute jump or call ────────────────────
                    -- jmp (d_is_jmp): goto, no return address saved.
                    -- bra (d_is_bra): call, pushes return address before jumping.
                    elsif d_is_jmp = '1' or d_is_bra = '1' then
                        take_branch := false;
                        case d_jmp_cond is
                            when "000" => take_branch := true;
                            when "001" => take_branch := (registers(register_index) = x"00000000");
                            when "010" => take_branch := (registers(register_index) /= x"00000000");
                            when "011" => take_branch := (registers(register_index)(31) = '1');
                            when "100" => take_branch := (registers(register_index)(31) = '0');
                            when others => null;
                        end case;
                        if take_branch then
                            next_pc := (31 downto 20 => '0') & d_imm20;
                            if d_is_bra = '1' then
                                registers(14) <= std_logic_vector(unsigned(registers(14)) - 4);
                                memory_address    <= std_logic_vector(unsigned(registers(14)) - 4);
                                memory_write_data <= registers(15);
                                memory_write_enable <= '1';
                                call_target <= next_pc;
                                state <= CALL_STORE;
                            else
                                memory_address     <= next_pc;
                                memory_read_enable <= '1';
                                state <= FETCH;
                            end if;
                        else
                            memory_address     <= registers(15);
                            memory_read_enable <= '1';
                            state <= FETCH;
                        end if;

                    -- ── jpr / bar — relative jump or call ────────────────────
                    -- jpr (d_is_jpr): goto PC+offset, no return address saved.
                    -- bar (d_is_bar): call PC+offset, pushes return address.
                    -- PC here is registers(15) = instruction address + 4 (set in FETCH).
                    elsif d_is_jpr = '1' or d_is_bar = '1' then
                        take_branch := false;
                        case d_jmp_cond is
                            when "000" => take_branch := true;
                            when "001" => take_branch := (registers(register_index) = x"00000000");
                            when "010" => take_branch := (registers(register_index) /= x"00000000");
                            when "011" => take_branch := (registers(register_index)(31) = '1');
                            when "100" => take_branch := (registers(register_index)(31) = '0');
                            when others => null;
                        end case;
                        if take_branch then
                            next_pc := std_logic_vector(unsigned(registers(15)) + unsigned(d_imm32));
                            if d_is_bar = '1' then
                                registers(14) <= std_logic_vector(unsigned(registers(14)) - 4);
                                memory_address    <= std_logic_vector(unsigned(registers(14)) - 4);
                                memory_write_data <= registers(15);
                                memory_write_enable <= '1';
                                call_target <= next_pc;
                                state <= CALL_STORE;
                            else
                                memory_address     <= next_pc;
                                memory_read_enable <= '1';
                                state <= FETCH;
                            end if;
                        else
                            memory_address     <= registers(15);
                            memory_read_enable <= '1';
                            state <= FETCH;
                        end if;

                    -- ── eai — enable interrupts ──────────────────────────────
                    elsif d_is_eai = '1' then
                        interrupts_enabled_reg <= '1';
                        memory_address     <= registers(15);
                        memory_read_enable <= '1';
                        state <= FETCH;

                    -- ── dai — disable interrupts ──────────────────────────────
                    elsif d_is_dai = '1' then
                        interrupts_enabled_reg <= '0';
                        memory_address     <= registers(15);
                        memory_read_enable <= '1';
                        state <= FETCH;

                    -- ── wfi — wait for interrupt ──────────────────────────────
                    elsif d_is_wfi = '1' then
                        memory_address     <= std_logic_vector(unsigned(registers(15)) - 4);
                        memory_read_enable <= '1';
                        state <= FETCH;

                    -- ── rti — return from interrupt ───────────────────────────
                    -- mode=000: rti — re-enable interrupts and jump to R13.
                    -- mode=001: rts — pop return address from stack into R15.
                    elsif d_is_rti = '1' then
                        if d_mode = "000" then
                            interrupts_enabled_reg <= '1';
                            memory_address     <= registers(13);
                            memory_read_enable <= '1';
                            state <= FETCH;
                        else
                            registers(14) <= std_logic_vector(unsigned(registers(14)) + 4);
                            memory_address     <= registers(14);
                            memory_read_enable <= '1';
                            load_destination   <= 15;
                            state <= LOAD_WAIT;
                        end if;

                    else
                        -- Unknown / unimplemented instruction — skip.
                        memory_address     <= registers(15);
                        memory_read_enable <= '1';
                        state <= FETCH;
                    end if;

                -- ── LOAD_WAIT ───────────────────────────────────────────────
                -- Wait for BRAM or SRAM read to settle.
                -- SRAM controller asserts memory_stall until all byte transfers complete.
                when LOAD_WAIT =>
                    if memory_stall = '0' then
                        state <= LOAD;
                    end if;

                -- ── LOAD ────────────────────────────────────────────────────
                -- Capture data into the destination register.
                when LOAD =>
                    if load_is_byte = '1' then
                        registers(load_destination) <= (31 downto 8 => '0') & memory_read_data(7 downto 0);
                        load_is_byte <= '0';
                    else
                        registers(load_destination) <= memory_read_data;
                    end if;
                    if load_destination = 15 then
                        memory_address <= memory_read_data;
                    else
                        memory_address <= registers(15);
                    end if;
                    memory_read_enable <= '1';
                    state <= FETCH;

                -- ── STORE ───────────────────────────────────────────────────
                -- Clear write enable (must pulse for exactly one cycle).
                -- Wait for stall to clear before fetching next instruction.
                when STORE =>
                    memory_write_enable <= '0';
                    if memory_stall = '0' then
                        memory_address     <= registers(15);
                        memory_read_enable <= '1';
                        state <= FETCH;
                    end if;

                -- ── CALL_STORE ───────────────────────────────────────────────
                -- Completes the stack push started by bra or bar in EXEC,
                -- then redirects to the saved call target.
                when CALL_STORE =>
                    memory_write_enable <= '0';
                    memory_address      <= call_target;
                    memory_read_enable  <= '1';
                    state <= FETCH;

                -- ── INTERRUPT_ENTRY ──────────────────────────────────────────
                -- Stack push completing; redirect to interrupt vector.
                when INTERRUPT_ENTRY =>
                    memory_write_enable <= '0';
                    memory_address      <= x"00000010";
                    memory_read_enable  <= '1';
                    state <= FETCH;

            end case;
        end if;
    end process;

end architecture rtl;
