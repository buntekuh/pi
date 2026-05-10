-- cpu.vhd — M56 CPU core
--
-- The CPU has 16 registers (R0-R15), each 32 bits wide.
-- R14 is the stack pointer (SP).  R15 is the program counter (PC).
--
-- The CPU talks to the outside world through a simple memory bus:
--   memory_address  — the address the CPU wants to read from or write to
--   memory_read_data  — data coming back from memory (or a peripheral)
--   memory_write_data  — data the CPU wants to write
--   memory_write_enable    — '1' for one clock cycle when writing
--   memory_read_enable    — '1' for one clock cycle when reading
--
-- Everything in memory space is accessed through this same bus —
-- whether it is program code in Block RAM, data in Block RAM, or the UART register.
-- The top-level (system.vhd) decides which device to route the access to.
--
-- ─── Byte order (endianness) ───────────────────────────────────────────────
--
-- The M56 is big-endian: the most significant byte of a multi-byte value
-- is stored at the lowest memory address.
--
-- This matches how humans read and write numbers — the largest part comes
-- first. The dominant alternative, little-endian (used by x86, ARM, and
-- most modern CPUs), stores the least significant byte first. That is a
-- historical accident from Intel's 8080 in the 1970s, not a principled
-- choice.
--
-- The terms come from Jonathan Swift's Gulliver's Travels (1726), where
-- two kingdoms go to war over which end of a boiled egg to crack open —
-- the big end or the little end. Danny Cohen borrowed the analogy in 1980
-- to describe the same kind of arbitrary but bitterly contested choice in
-- computing. Big-endians crack their egg on the big end: the most
-- significant byte lives at the lowest address. Little-endians crack on
-- the little end: the least significant byte comes first.
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
--
-- Each instruction takes 2 clock cycles (FETCH + EXEC) for simple operations,
-- or 3 cycles (FETCH + EXEC + LOAD) for reading from memory/peripherals,
-- or 3 cycles (FETCH + EXEC + STORE) for writing to memory/peripherals.
--
-- ─── Block RAM timing ────────────────────────────────────────────────────────────
--
-- Block RAM is synchronous: you present an address on one cycle and the data
-- arrives on the next. Every instruction fetch therefore takes two cycles —
-- one to ask, one to receive. There is no speculation or look-ahead; the
-- CPU simply accepts this one-tick cost and the FETCH state exists for
-- exactly that purpose: it holds the address steady while Block RAM does its work.

library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;

entity m56_cpu is
    port (
        clk      : in  STD_LOGIC;
        resetn   : in  STD_LOGIC;             -- reset signal; the trailing n is hardware convention for active low, meaning '1' = running normally, '0' = reset

        -- Memory / peripheral bus
        memory_address : out STD_LOGIC_VECTOR(31 downto 0);  -- address to access
        memory_read_data : in  STD_LOGIC_VECTOR(31 downto 0);  -- data read back
        memory_write_data : out STD_LOGIC_VECTOR(31 downto 0);  -- data to write
        memory_write_enable   : out STD_LOGIC;                      -- write enable pulse
        memory_read_enable   : out STD_LOGIC;                      -- read enable pulse

        -- Interrupt interface
        interrupt_request    : in  STD_LOGIC;                      -- '1' when a peripheral is requesting attention
        irq_status           : in  STD_LOGIC_VECTOR(31 downto 0); -- one bit per source; written to R13 on entry
        interrupts_enabled   : out STD_LOGIC                       -- '1' when the CPU will accept interrupts
    );
end entity m56_cpu;

-- rtl = Register Transfer Level: describes the design as registers (flip-flops that
-- hold state) and the logic that transfers values between them each clock cycle.
-- This is the standard name for synthesisable hardware in VHDL.
architecture rtl of m56_cpu is

    -- 16 × 32-bit register file.
    -- These are the CPU's working storage — everything the program computes
    -- lives here.  R14 = stack pointer, R15 = program counter.
    type register_file_type is array(0 to 15) of std_logic_vector(31 downto 0);
    signal registers : register_file_type := (
        14 => x"0007FFFC",   -- SP starts at top of RAM
        15 => x"00000000",   -- PC starts at address 0
        others => (others => '0')
    );

    -- The execution state machine.
    type state_type is (FETCH, EXEC, LOAD, STORE, INTERRUPT_ENTRY);
    signal state    : state_type := FETCH;
    signal load_destination : integer range 0 to 15;  -- which register LOAD will write into

    -- Decoder output signals — wired from the decoder module below.
    -- These are combinational: they update instantly whenever memory_read_data changes.
    -- During EXEC, memory_read_data holds the current instruction, so these signals
    -- describe that instruction throughout the EXEC cycle.
    signal d_opcode   : std_logic_vector(4 downto 0);  -- raw opcode number
    signal d_mode     : std_logic_vector(3 downto 0);  -- addressing mode
    signal d_reg      : std_logic_vector(3 downto 0);  -- register field
    signal d_imm19    : std_logic_vector(18 downto 0); -- 19-bit immediate
    signal d_imm32    : std_logic_vector(31 downto 0); -- imm19 sign-extended to 32 bits
    signal d_is_mov   : std_logic;  -- '1' if this is a mov instruction
    signal d_is_alu   : std_logic;  -- '1' if this is add/sub/and/orr/xor
    signal d_is_jpr   : std_logic;  -- '1' if this is a relative jump
    signal d_is_wfi   : std_logic;  -- '1' if this is a wait-for-interrupt
    signal d_is_eai   : std_logic;  -- '1' if this is enable-interrupts
    signal d_is_dai   : std_logic;  -- '1' if this is disable-interrupts
    signal d_is_rti   : std_logic;  -- '1' if this is return-from-interrupt
    signal d_jmp_sub  : std_logic;  -- '1' if jump is a subroutine call
    signal d_jmp_cond : std_logic_vector(2 downto 0);  -- jump condition code

    -- Interrupt enable flag.  Starts disabled at reset; the program must
    -- execute eai to allow interrupts.  Automatically cleared when the CPU
    -- enters an interrupt handler, so the handler cannot be interrupted again.
    signal interrupts_enabled_reg : std_logic := '0';

begin

    -- Expose the interrupt enable flag so system.vhd can read it (e.g. for an LED or status register).
    interrupts_enabled <= interrupts_enabled_reg;

    -- ── Decoder ─────────────────────────────────────────────────────────────
    -- The decoder is always watching memory_read_data.  During EXEC, memory_read_data contains
    -- the instruction the Block RAM returned.  The decoder's outputs (d_*) are
    -- therefore always valid and ready to use in EXEC.
    dec: entity work.M56_Decoder
        port map (
            instruction => memory_read_data,   -- instruction word from Block RAM
            opcode   => d_opcode,
            mode     => d_mode,
            reg      => d_reg,
            imm19    => d_imm19,
            imm32    => d_imm32,
            is_mov   => d_is_mov,
            is_mvb   => open,       -- byte move not yet implemented in CPU
            is_alu   => d_is_alu,
            is_not   => open,       -- not yet implemented
            is_shf   => open,       -- not yet implemented
            is_sar   => open,       -- not yet implemented
            is_jmp   => open,       -- absolute jump not yet implemented
            is_jpr   => d_is_jpr,
            is_wfi   => d_is_wfi,
            is_eai   => d_is_eai,
            is_dai   => d_is_dai,
            is_rti   => d_is_rti,
            jmp_sub  => d_jmp_sub,
            jmp_cond => d_jmp_cond
        );

    -- ── Main clocked process ─────────────────────────────────────────────────
    process(clk, resetn)
        variable register_index         : integer range 0 to 15;           -- register index from d_reg
        variable destination_register   : integer range 0 to 15;           -- destination register from imm19[3:0]
        variable take_branch            : boolean;                         -- should this branch be taken?
        variable next_pc                : std_logic_vector(31 downto 0);   -- computed branch target
    begin

        -- ── Reset ──────────────────────────────────────────────────────────
        -- BTN0 held pulls resetn low.  Everything goes to a known starting state.
        if resetn = '0' then
            registers     <= (
                14 => x"0007FFFC",   -- SP = top of RAM
                15 => x"00000000",   -- PC = address 0 (first instruction)
                others => (others => '0')
            );
            state    <= FETCH;
            memory_address <= (others => '0');  -- address 0 for first fetch
            memory_write_data <= (others => '0');
            memory_write_enable   <= '0';
            memory_read_enable   <= '1';   -- tell Block RAM to read immediately when reset releases
            interrupts_enabled_reg <= '0';  -- interrupts disabled until the program issues eai

        -- ── Every rising clock edge ────────────────────────────────────────
        elsif rising_edge(clk) then

            case state is

                -- ── FETCH ───────────────────────────────────────────────────
                -- The Block RAM is sampling memory_address RIGHT NOW at this clock edge
                -- and will have data ready next cycle.
                -- Our only job here is:
                --   1. Compute PC = fetch address + 4  (so the program can read PC)
                --   2. Clear any write enable left over from the previous cycle
                --   3. Advance to EXEC
                --
                -- We deliberately do NOT change memory_address here —
                -- it was already set to the right address by EXEC/LOAD/STORE.
                when FETCH =>
                    memory_write_enable   <= '0';
                    registers(15) <= std_logic_vector(unsigned(memory_address) + 4);
                    state    <= EXEC;

                -- ── EXEC ────────────────────────────────────────────────────
                -- The Block RAM data (the instruction) is now in memory_read_data.
                -- The decoder has already broken it into fields (d_*).
                -- Execute the instruction and set up the next fetch address.
                when EXEC =>
                    memory_write_enable <= '0';   -- default: no write this cycle
                    memory_read_enable <= '0';   -- default: no read this cycle

                    -- Convert 4-bit register fields to integers for array indexing.
                    -- d_reg is the main register field (bits 22..19 of instruction).
                    -- destination_register comes from the low 4 bits of imm19 — used as a second
                    -- register number in instructions that need two registers.
                    register_index  := to_integer(unsigned(d_reg));
                    destination_register := to_integer(unsigned(d_imm19(3 downto 0)));

                    -- ── Interrupt check ──────────────────────────────────────
                    -- Before executing the decoded instruction, check whether a
                    -- peripheral is requesting attention and the CPU is willing to
                    -- accept it.  If so, the instruction is not executed — the CPU
                    -- saves the return address and jumps to the handler instead.
                    -- registers(15) already holds (instruction address + 4), set in
                    -- FETCH, which is exactly the address the handler returns to.
                    if interrupt_request = '1' and interrupts_enabled_reg = '1' then
                        -- Push return address onto the stack.
                        -- SP (R14) decrements by 4; the new SP is the write address.
                        registers(14) <= std_logic_vector(unsigned(registers(14)) - 4);
                        memory_address    <= std_logic_vector(unsigned(registers(14)) - 4);
                        memory_write_data <= registers(15);
                        memory_write_enable <= '1';
                        -- R13 receives the interrupt status word so the handler
                        -- knows which source(s) fired without any extra memory read.
                        registers(13) <= irq_status;
                        interrupts_enabled_reg <= '0';
                        state <= INTERRUPT_ENTRY;

                    -- ── mov family ──────────────────────────────────────────
                    -- All load, store, and register-copy operations share opcode 0.
                    -- The mode field says which variant this is.
                    elsif d_is_mov = '1' then
                        case d_mode is

                            -- mov-h #imm19, Rdst  (mode 1)
                            -- Load a 19-bit value into the UPPER bits of a register.
                            -- The value lands at bits 31..13 and zeros bits 12..0.
                            -- Together with a plain mov #imm, you can load any 32-bit
                            -- constant into a register in two instructions.
                            -- Example: mov-h #0x200, R4 sets R4 = 0x00400000
                            --   because 0x200 shifted left 13 = 0x400000.
                            when "0001" =>
                                registers(register_index) <= d_imm19 & "0000000000000";  -- shift left 13
                                -- Set up the next instruction's address and return to FETCH.
                                memory_address <= registers(15);
                                memory_read_enable   <= '1';
                                state    <= FETCH;

                            -- mov Rsrc, Rdst  (mode 2)
                            -- Copy one register into another.  Completely straightforward.
                            when "0010" =>
                                registers(destination_register) <= registers(register_index);
                                memory_address <= registers(15);
                                memory_read_enable   <= '1';
                                state    <= FETCH;

                            -- mov [Rsrc], Rdst  (mode 3) — indirect READ
                            -- Read a 32-bit word from the address held in Rsrc.
                            -- This could be a Block RAM address or a peripheral like the UART.
                            -- We put the address on memory_address, assert memory_read_enable, and go to
                            -- LOAD — which will capture memory_read_data one cycle later.
                            when "0011" =>
                                memory_address <= registers(register_index);  -- address to read from
                                memory_read_enable   <= '1';
                                load_destination <= destination_register;       -- remember which register gets the result
                                state    <= LOAD;

                            -- mov Rsrc, [Rdst]  (mode 4) — indirect WRITE
                            -- Write Rsrc to the address held in Rdst.
                            -- We put the address on memory_address, the value on memory_write_data,
                            -- assert memory_write_enable, and go to STORE.
                            -- STORE will clear memory_write_enable and then redirect to the next fetch.
                            when "0100" =>
                                memory_address <= registers(destination_register);  -- address to write to
                                memory_write_data <= registers(register_index);   -- value to write
                                memory_write_enable   <= '1';
                                state    <= STORE;

                            when others =>
                                -- Unknown mode — skip and continue.
                                memory_address <= registers(15);
                                memory_read_enable   <= '1';
                                state    <= FETCH;
                        end case;

                    -- ── ALU family ───────────────────────────────────────────
                    -- add, sub, and, orr, xor  (opcodes 2-6)
                    -- All operate on one register and a 32-bit immediate (from imm32).
                    -- Result is written back to the same register (Rdst).
                    -- Mode 0 = immediate operand (the only mode echo.s uses).
                    elsif d_is_alu = '1' then
                        case d_opcode is
                            when "00010" =>  -- add Rdst, #imm
                                registers(register_index) <= std_logic_vector(unsigned(registers(register_index)) + unsigned(d_imm32));
                            when "00011" =>  -- sub Rdst, #imm
                                registers(register_index) <= std_logic_vector(unsigned(registers(register_index)) - unsigned(d_imm32));
                            when "00100" =>  -- and Rdst, #imm
                                registers(register_index) <= registers(register_index) and d_imm32;
                            when "00101" =>  -- orr Rdst, #imm
                                registers(register_index) <= registers(register_index) or  d_imm32;
                            when "00110" =>  -- xor Rdst, #imm
                                registers(register_index) <= registers(register_index) xor d_imm32;
                            when others  => null;
                        end case;
                        memory_address <= registers(15);
                        memory_read_enable   <= '1';
                        state    <= FETCH;

                    -- ── jpr — relative jump ──────────────────────────────────
                    -- Jump to (PC + offset) if a condition is met.
                    -- PC here is registers(15), which FETCH already set to
                    -- (instruction address + 4).  The assembler calculates
                    -- offsets relative to that same value, so they match.
                    --
                    -- Conditions: always / zero / nonzero / negative / non-negative.
                    -- "Zero" means the test register equals 0x00000000.
                    -- "Negative" means bit 31 of the test register is set.
                    elsif d_is_jpr = '1' then
                        take_branch :=false;
                        case d_jmp_cond is
                            when "000" => take_branch :=true;                          -- jpr    (always)
                            when "001" => take_branch :=(registers(register_index) = x"00000000");   -- jpr.z  (zero)
                            when "010" => take_branch :=(registers(register_index) /= x"00000000");  -- jpr.nz (nonzero)
                            when "011" => take_branch :=(registers(register_index)(31) = '1');       -- jpr.n  (negative)
                            when "100" => take_branch :=(registers(register_index)(31) = '0');       -- jpr.nn (non-negative)
                            when others => null;
                        end case;

                        if take_branch then
                            -- Compute branch target = PC + signed offset.
                            -- d_imm32 is the sign-extended offset from the instruction.
                            next_pc  := std_logic_vector(unsigned(registers(15)) + unsigned(d_imm32));
                            memory_address <= next_pc;  -- send the branch target to Block RAM
                        else
                            memory_address <= registers(15); -- no branch: next instruction as normal
                        end if;
                        memory_read_enable <= '1';
                        state  <= FETCH;

                    -- ── eai — enable interrupts ──────────────────────────────
                    -- From this point on, interrupt_request = '1' will be acted on.
                    elsif d_is_eai = '1' then
                        interrupts_enabled_reg <= '1';
                        memory_address <= registers(15);
                        memory_read_enable <= '1';
                        state <= FETCH;

                    -- ── dai — disable interrupts ──────────────────────────────
                    -- Blocks interrupt delivery until eai is issued again.
                    -- The handler issues dai on entry (automatically, via interrupt
                    -- check above) and eai before returning, so dai in user code is
                    -- only needed for short critical sections.
                    elsif d_is_dai = '1' then
                        interrupts_enabled_reg <= '0';
                        memory_address <= registers(15);
                        memory_read_enable <= '1';
                        state <= FETCH;

                    -- ── wfi — wait for interrupt ──────────────────────────────
                    -- Suspends execution by re-fetching this same instruction
                    -- on every cycle until an interrupt fires.  The interrupt check
                    -- at the top of EXEC will catch it and redirect to the handler.
                    -- Note: interrupts must be enabled (eai) before calling wfi,
                    -- otherwise the CPU will spin here forever.
                    elsif d_is_wfi = '1' then
                        memory_address <= std_logic_vector(unsigned(registers(15)) - 4);
                        memory_read_enable <= '1';
                        state <= FETCH;

                    -- ── rti — return from interrupt ───────────────────────────
                    -- Atomically enables interrupts and jumps to R13.
                    -- R13 was loaded from the stack by the handler's closing
                    -- sequence before this instruction runs.
                    -- Because interrupts_enabled_reg is still '0' during this
                    -- EXEC cycle, the interrupt check at the top cannot fire here —
                    -- any pending interrupt will only be seen in the next EXEC,
                    -- by which point PC already points at the return address.
                    elsif d_is_rti = '1' then
                        interrupts_enabled_reg <= '1';
                        memory_address <= registers(13);
                        memory_read_enable <= '1';
                        state <= FETCH;

                    -- ── Unknown / unimplemented instruction ──────────────────
                    -- Quietly skip it and continue.
                    else
                        memory_address <= registers(15);
                        memory_read_enable   <= '1';
                        state    <= FETCH;
                    end if;

                -- ── LOAD ────────────────────────────────────────────────────
                -- One cycle after EXEC issued a read request (memory_read_enable='1'),
                -- memory_read_data now contains the data from memory or a peripheral.
                -- Capture it into the destination register.
                --
                -- For a UART read: memory_read_data = { 22'b0, TX_busy, RX_valid, rx_byte }
                --   bit 9 = TX busy (currently transmitting)
                --   bit 8 = RX valid (a byte has arrived and is waiting)
                --   bits 7..0 = the received byte
                --
                -- Pre-load the NEXT fetch address so FETCH can do its job.
                when LOAD =>
                    registers(load_destination) <= memory_read_data;   -- store the result
                    memory_address <= registers(15);          -- next instruction address for Block RAM
                    memory_read_enable   <= '1';
                    state    <= FETCH;

                -- ── STORE ───────────────────────────────────────────────────
                -- EXEC asserted memory_write_enable='1' and put a peripheral/memory address
                -- on memory_address.  During THIS cycle, that write enable is HIGH
                -- and the peripheral (e.g. UART) sees it and acts on it.
                -- Our job here is to clear memory_write_enable so it only pulses for ONE cycle,
                -- and redirect memory_address to the next fetch address.
                --
                -- For a UART write: while memory_write_enable='1' and memory_address=0x400000,
                -- the uart_wr signal in system.vhd is '1', which tells the UART
                -- transmitter to load memory_write_data(7:0) and start sending.
                when STORE =>
                    memory_write_enable   <= '0';         -- done writing
                    memory_address <= registers(15);    -- back to fetching instructions
                    memory_read_enable   <= '1';
                    state    <= FETCH;

                -- ── INTERRUPT_ENTRY ──────────────────────────────────────────
                -- EXEC pushed the return address onto the stack (write_enable='1').
                -- That write is completing during this cycle.
                -- Clear write_enable and redirect to the interrupt vector.
                when INTERRUPT_ENTRY =>
                    memory_write_enable <= '0';
                    memory_address      <= x"00000010";
                    memory_read_enable  <= '1';
                    state               <= FETCH;

            end case;
        end if;
    end process;

end architecture rtl;
