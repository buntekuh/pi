-- cpu.vhd — M56 CPU core
--
-- The CPU has 16 registers (R0-R15), each 32 bits wide.
-- R14 is the stack pointer (SP).  R15 is the program counter (PC).
--
-- The CPU talks to the outside world through a simple memory bus:
--   mem_addr  — the address the CPU wants to read from or write to
--   mem_rdat  — data coming back from memory (or a peripheral)
--   mem_wdat  — data the CPU wants to write
--   mem_we    — '1' for one clock cycle when writing
--   mem_re    — '1' for one clock cycle when reading
--
-- Everything in memory space is accessed through this same bus —
-- whether it is program code in BRAM, data in BRAM, or the UART register.
-- The top-level (top.vhd) decides which device to route the access to.
--
-- ─── Four-state execution cycle ────────────────────────────────────────────
--
--   FETCH  → present instruction address to BRAM, compute PC = addr + 4
--   EXEC   → BRAM data is ready; decode and execute the instruction
--   LOAD   → (indirect reads only) capture data from mem_rdat into a register
--   STORE  → (indirect writes only) clear write-enable, redirect to next fetch
--
-- Each instruction takes 2 clock cycles (FETCH + EXEC) for simple operations,
-- or 3 cycles (FETCH + EXEC + LOAD) for reading from memory/peripherals,
-- or 3 cycles (FETCH + EXEC + STORE) for writing to memory/peripherals.
--
-- ─── BRAM timing ────────────────────────────────────────────────────────────
--
-- The BRAM (program memory) is synchronous: you present an address this cycle
-- and get the data NEXT cycle.  That means the address for instruction N must
-- be on the bus during the cycle BEFORE we want to use the data.
--
-- The trick: EXEC puts the NEXT fetch address on mem_addr at the end of EXEC.
-- FETCH sees that address stable on the bus, BRAM reads it at the FETCH clock
-- edge, and data is ready when EXEC starts.  FETCH itself never changes
-- mem_addr — it just waits for the BRAM and computes PC.

library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;

entity m56_cpu is
    port (
        clk      : in  STD_LOGIC;
        resetn   : in  STD_LOGIC;             -- active-low reset (0 = reset, 1 = running)

        -- Memory / peripheral bus
        mem_addr : out STD_LOGIC_VECTOR(31 downto 0);  -- address to access
        mem_rdat : in  STD_LOGIC_VECTOR(31 downto 0);  -- data read back
        mem_wdat : out STD_LOGIC_VECTOR(31 downto 0);  -- data to write
        mem_we   : out STD_LOGIC;                      -- write enable pulse
        mem_re   : out STD_LOGIC                       -- read enable pulse
    );
end entity m56_cpu;

architecture rtl of m56_cpu is

    -- 16 × 32-bit register file.
    -- These are the CPU's working storage — everything the program computes
    -- lives here.  R14 = stack pointer, R15 = program counter.
    type regfile_t is array(0 to 15) of std_logic_vector(31 downto 0);
    signal regs : regfile_t := (
        14 => x"0007FFFC",   -- SP starts at top of RAM
        15 => x"00000000",   -- PC starts at address 0
        others => (others => '0')
    );

    -- The execution state machine.
    type state_t is (FETCH, EXEC, LOAD, STORE);
    signal state    : state_t := FETCH;
    signal load_dst : integer range 0 to 15;  -- which register LOAD will write into

    -- Decoder output signals — wired from the decoder module below.
    -- These are combinational: they update instantly whenever mem_rdat changes.
    -- During EXEC, mem_rdat holds the current instruction, so these signals
    -- describe that instruction throughout the EXEC cycle.
    signal d_opcode   : std_logic_vector(4 downto 0);  -- raw opcode number
    signal d_mode     : std_logic_vector(3 downto 0);  -- addressing mode
    signal d_reg      : std_logic_vector(3 downto 0);  -- register field
    signal d_imm19    : std_logic_vector(18 downto 0); -- 19-bit immediate
    signal d_imm32    : std_logic_vector(31 downto 0); -- imm19 sign-extended to 32 bits
    signal d_is_mov   : std_logic;  -- '1' if this is a mov instruction
    signal d_is_alu   : std_logic;  -- '1' if this is add/sub/and/orr/xor
    signal d_is_jpr   : std_logic;  -- '1' if this is a relative jump
    signal d_jmp_sub  : std_logic;  -- '1' if jump is a subroutine call
    signal d_jmp_cond : std_logic_vector(2 downto 0);  -- jump condition code

begin

    -- ── Decoder ─────────────────────────────────────────────────────────────
    -- The decoder is always watching mem_rdat.  During EXEC, mem_rdat contains
    -- the instruction the BRAM returned.  The decoder's outputs (d_*) are
    -- therefore always valid and ready to use in EXEC.
    dec: entity work.M56_Decoder
        port map (
            instr    => mem_rdat,   -- instruction word from BRAM
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
            is_wfi   => open,       -- wait-for-interrupt not yet implemented
            is_eai   => open,       -- enable interrupts not yet implemented
            is_dai   => open,       -- disable interrupts not yet implemented
            jmp_sub  => d_jmp_sub,
            jmp_cond => d_jmp_cond
        );

    -- ── Main clocked process ─────────────────────────────────────────────────
    process(clk, resetn)
        variable vreg    : integer range 0 to 15;           -- register index from d_reg
        variable vrdst   : integer range 0 to 15;           -- destination register from imm19[3:0]
        variable take    : boolean;                         -- should this jump be taken?
        variable next_pc : std_logic_vector(31 downto 0);   -- computed branch target
    begin

        -- ── Reset ──────────────────────────────────────────────────────────
        -- BTN0 held pulls resetn low.  Everything goes to a known starting state.
        if resetn = '0' then
            regs     <= (
                14 => x"0007FFFC",   -- SP = top of RAM
                15 => x"00000000",   -- PC = address 0 (first instruction)
                others => (others => '0')
            );
            state    <= FETCH;
            mem_addr <= (others => '0');  -- address 0 for first fetch
            mem_wdat <= (others => '0');
            mem_we   <= '0';
            mem_re   <= '1';   -- tell BRAM to read immediately when reset releases

        -- ── Every rising clock edge ────────────────────────────────────────
        elsif rising_edge(clk) then

            case state is

                -- ── FETCH ───────────────────────────────────────────────────
                -- The BRAM is sampling mem_addr RIGHT NOW at this clock edge
                -- and will have data ready next cycle.
                -- Our only job here is:
                --   1. Compute PC = fetch address + 4  (so the program can read PC)
                --   2. Clear any write enable left over from the previous cycle
                --   3. Advance to EXEC
                --
                -- We deliberately do NOT change mem_addr here —
                -- it was already set to the right address by EXEC/LOAD/STORE.
                when FETCH =>
                    mem_we   <= '0';
                    regs(15) <= std_logic_vector(unsigned(mem_addr) + 4);
                    state    <= EXEC;

                -- ── EXEC ────────────────────────────────────────────────────
                -- The BRAM data (the instruction) is now in mem_rdat.
                -- The decoder has already broken it into fields (d_*).
                -- Execute the instruction and set up the next fetch address.
                when EXEC =>
                    mem_we <= '0';   -- default: no write this cycle
                    mem_re <= '0';   -- default: no read this cycle

                    -- Convert 4-bit register fields to integers for array indexing.
                    -- d_reg is the main register field (bits 22..19 of instruction).
                    -- vrdst comes from the low 4 bits of imm19 — used as a second
                    -- register number in instructions that need two registers.
                    vreg  := to_integer(unsigned(d_reg));
                    vrdst := to_integer(unsigned(d_imm19(3 downto 0)));

                    -- ── mov family ──────────────────────────────────────────
                    -- All load, store, and register-copy operations share opcode 0.
                    -- The mode field says which variant this is.
                    if d_is_mov = '1' then
                        case d_mode is

                            -- mov-h #imm19, Rdst  (mode 1)
                            -- Load a 19-bit value into the UPPER bits of a register.
                            -- The value lands at bits 31..13 and zeros bits 12..0.
                            -- Together with a plain mov #imm, you can load any 32-bit
                            -- constant into a register in two instructions.
                            -- Example: mov-h #0x200, R4 sets R4 = 0x00400000
                            --   because 0x200 shifted left 13 = 0x400000.
                            when "0001" =>
                                regs(vreg) <= d_imm19 & "0000000000000";  -- shift left 13
                                -- Set up the next instruction's address and return to FETCH.
                                mem_addr <= regs(15);
                                mem_re   <= '1';
                                state    <= FETCH;

                            -- mov Rsrc, Rdst  (mode 2)
                            -- Copy one register into another.  Completely straightforward.
                            when "0010" =>
                                regs(vrdst) <= regs(vreg);
                                mem_addr <= regs(15);
                                mem_re   <= '1';
                                state    <= FETCH;

                            -- mov [Rsrc], Rdst  (mode 3) — indirect READ
                            -- Read a 32-bit word from the address held in Rsrc.
                            -- This could be a BRAM address or a peripheral like the UART.
                            -- We put the address on mem_addr, assert mem_re, and go to
                            -- LOAD — which will capture mem_rdat one cycle later.
                            when "0011" =>
                                mem_addr <= regs(vreg);  -- address to read from
                                mem_re   <= '1';
                                load_dst <= vrdst;       -- remember which register gets the result
                                state    <= LOAD;

                            -- mov Rsrc, [Rdst]  (mode 4) — indirect WRITE
                            -- Write Rsrc to the address held in Rdst.
                            -- We put the address on mem_addr, the value on mem_wdat,
                            -- assert mem_we, and go to STORE.
                            -- STORE will clear mem_we and then redirect to the next fetch.
                            when "0100" =>
                                mem_addr <= regs(vrdst);  -- address to write to
                                mem_wdat <= regs(vreg);   -- value to write
                                mem_we   <= '1';
                                state    <= STORE;

                            when others =>
                                -- Unknown mode — skip and continue.
                                mem_addr <= regs(15);
                                mem_re   <= '1';
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
                                regs(vreg) <= std_logic_vector(unsigned(regs(vreg)) + unsigned(d_imm32));
                            when "00011" =>  -- sub Rdst, #imm
                                regs(vreg) <= std_logic_vector(unsigned(regs(vreg)) - unsigned(d_imm32));
                            when "00100" =>  -- and Rdst, #imm
                                regs(vreg) <= regs(vreg) and d_imm32;
                            when "00101" =>  -- orr Rdst, #imm
                                regs(vreg) <= regs(vreg) or  d_imm32;
                            when "00110" =>  -- xor Rdst, #imm
                                regs(vreg) <= regs(vreg) xor d_imm32;
                            when others  => null;
                        end case;
                        mem_addr <= regs(15);
                        mem_re   <= '1';
                        state    <= FETCH;

                    -- ── jpr — relative jump ──────────────────────────────────
                    -- Jump to (PC + offset) if a condition is met.
                    -- PC here is regs(15), which FETCH already set to
                    -- (instruction address + 4).  The assembler calculates
                    -- offsets relative to that same value, so they match.
                    --
                    -- Conditions: always / zero / nonzero / negative / non-negative.
                    -- "Zero" means the test register equals 0x00000000.
                    -- "Negative" means bit 31 of the test register is set.
                    elsif d_is_jpr = '1' then
                        take := false;
                        case d_jmp_cond is
                            when "000" => take := true;                          -- jpr    (always)
                            when "001" => take := (regs(vreg) = x"00000000");   -- jpr.z  (zero)
                            when "010" => take := (regs(vreg) /= x"00000000");  -- jpr.nz (nonzero)
                            when "011" => take := (regs(vreg)(31) = '1');       -- jpr.n  (negative)
                            when "100" => take := (regs(vreg)(31) = '0');       -- jpr.nn (non-negative)
                            when others => null;
                        end case;

                        if take then
                            -- Compute branch target = PC + signed offset.
                            -- d_imm32 is the sign-extended offset from the instruction.
                            next_pc  := std_logic_vector(unsigned(regs(15)) + unsigned(d_imm32));
                            mem_addr <= next_pc;  -- send the branch target to BRAM
                        else
                            mem_addr <= regs(15); -- no branch: next instruction as normal
                        end if;
                        mem_re <= '1';
                        state  <= FETCH;

                    -- ── Unknown / unimplemented instruction ──────────────────
                    -- Quietly skip it and continue.  This handles wfi, eai, dai, etc.
                    -- that are not yet wired up.
                    else
                        mem_addr <= regs(15);
                        mem_re   <= '1';
                        state    <= FETCH;
                    end if;

                -- ── LOAD ────────────────────────────────────────────────────
                -- One cycle after EXEC issued a read request (mem_re='1'),
                -- mem_rdat now contains the data from memory or a peripheral.
                -- Capture it into the destination register.
                --
                -- For a UART read: mem_rdat = { 22'b0, TX_busy, RX_valid, rx_byte }
                --   bit 9 = TX busy (currently transmitting)
                --   bit 8 = RX valid (a byte has arrived and is waiting)
                --   bits 7..0 = the received byte
                --
                -- Pre-load the NEXT fetch address so FETCH can do its job.
                when LOAD =>
                    regs(load_dst) <= mem_rdat;   -- store the result
                    mem_addr <= regs(15);          -- next instruction address for BRAM
                    mem_re   <= '1';
                    state    <= FETCH;

                -- ── STORE ───────────────────────────────────────────────────
                -- EXEC asserted mem_we='1' and put a peripheral/memory address
                -- on mem_addr.  During THIS cycle, that write enable is HIGH
                -- and the peripheral (e.g. UART) sees it and acts on it.
                -- Our job here is to clear mem_we so it only pulses for ONE cycle,
                -- and redirect mem_addr to the next fetch address.
                --
                -- For a UART write: while mem_we='1' and mem_addr=0x400000,
                -- the uart_wr signal in top.vhd is '1', which tells the UART
                -- transmitter to load mem_wdat(7:0) and start sending.
                when STORE =>
                    mem_we   <= '0';         -- done writing
                    mem_addr <= regs(15);    -- back to fetching instructions
                    mem_re   <= '1';
                    state    <= FETCH;

            end case;
        end if;
    end process;

end architecture rtl;
