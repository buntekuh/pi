-- sram.vhd — IS61WV5128BLL 8-bit SRAM controller for M56 / Titania
--
-- The on-board SRAM is 512 KB: 524,288 × 8-bit bytes, 19-bit address bus.
-- The M56 CPU reads and writes 32-bit words, so each access requires four
-- consecutive byte transfers.  This controller performs those transfers and
-- presents a 32-bit interface to the memory bus.
--
-- ─── Byte order (big-endian) ─────────────────────────────────────────────────
-- The M56 is big-endian.  For a 32-bit word at byte address A:
--   SRAM[A]   = bits 31..24  (most significant byte, transferred first)
--   SRAM[A+1] = bits 23..16
--   SRAM[A+2] = bits 15..8
--   SRAM[A+3] = bits 7..0   (least significant byte)
--
-- ─── Timing (IS61WV5128BLL-10 at 12 MHz) ─────────────────────────────────────
-- The SRAM has a 10 ns read/write cycle time.  One clock period at 12 MHz is
-- 83.33 ns — 8× the minimum — so one byte transfer per clock is safe with
-- ample margin.
--
-- Reads:  5 cycles (IDLE + 4 READ states, one byte per state).
-- Writes: 9 cycles (IDLE detects + 4 PREP/EXEC pairs, one byte per pair).
-- The stall signal is combinatorial: it goes high the same cycle the CPU
-- presents a request, so the CPU never sees a false "ready."
--
-- ─── Write timing ────────────────────────────────────────────────────────────
-- For each byte, address is driven for one full cycle (WEn=1) before WEn is
-- lowered.  This guarantees tAW (7 ns address setup before WEn) with >>10×
-- margin regardless of inter-signal skew on the PCB.

library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;

entity sram_controller is
    port (
        clk              : in  STD_LOGIC;
        resetn           : in  STD_LOGIC;

        -- CPU bus interface (driven by system.vhd)
        cpu_select       : in  STD_LOGIC;                       -- '1' when CPU address is in SRAM range
        cpu_address      : in  STD_LOGIC_VECTOR(31 downto 0);
        cpu_write_data   : in  STD_LOGIC_VECTOR(31 downto 0);
        cpu_read_enable  : in  STD_LOGIC;
        cpu_write_enable : in  STD_LOGIC;
        cpu_read_data    : out STD_LOGIC_VECTOR(31 downto 0);
        stall            : out STD_LOGIC;

        -- Physical SRAM pins (IS61WV5128BLL)
        sram_addr        : out STD_LOGIC_VECTOR(18 downto 0);
        sram_data        : inout STD_LOGIC_VECTOR(7 downto 0);
        sram_cen         : out STD_LOGIC;   -- chip enable   (active low)
        sram_oen         : out STD_LOGIC;   -- output enable (active low)
        sram_wen         : out STD_LOGIC    -- write enable  (active low)
    );
end entity sram_controller;

architecture rtl of sram_controller is

    type state_type is (
        IDLE,
        READ_B0, READ_B1, READ_B2, READ_B3,
        WRITE_B0_PREP, WRITE_B0_EXEC,
        WRITE_B1_PREP, WRITE_B1_EXEC,
        WRITE_B2_PREP, WRITE_B2_EXEC,
        WRITE_B3_PREP, WRITE_B3_EXEC
    );
    signal state : state_type := IDLE;

    signal base_addr   : STD_LOGIC_VECTOR(18 downto 0);  -- byte address of word[31:24]
    signal write_word  : STD_LOGIC_VECTOR(31 downto 0);  -- write data latched in IDLE
    signal assembled   : STD_LOGIC_VECTOR(31 downto 0);  -- read result, built byte by byte

    signal data_out    : STD_LOGIC_VECTOR(7 downto 0);   -- data driven onto sram_data
    signal driving     : STD_LOGIC;                       -- '1' = FPGA drives sram_data

begin

    -- ── Output assignments ───────────────────────────────────────────────────

    cpu_read_data <= assembled;

    -- Tristate: FPGA drives the data bus during writes, releases it during reads.
    sram_data <= data_out when driving = '1' else (others => 'Z');

    -- stall is combinatorial so it goes high the same cycle a request arrives,
    -- before the state machine has had a chance to register the start.
    stall <= '0' when state = IDLE
                  and not (cpu_select = '1' and (cpu_read_enable = '1' or cpu_write_enable = '1'))
             else '1';

    -- ── State machine ────────────────────────────────────────────────────────
    process(clk, resetn)
    begin
        if resetn = '0' then
            state    <= IDLE;
            driving  <= '0';
            sram_cen <= '1';
            sram_oen <= '1';
            sram_wen <= '1';

        elsif rising_edge(clk) then
            case state is

                -- ── IDLE ────────────────────────────────────────────────────
                when IDLE =>
                    if cpu_select = '1' and cpu_read_enable = '1' then
                        -- Latch address, assert chip/output enable, start read.
                        -- Byte 0 (MSB) will be stable on DQ by the end of READ_B0.
                        base_addr <= cpu_address(18 downto 0);
                        sram_addr <= cpu_address(18 downto 0);
                        sram_cen  <= '0';
                        sram_oen  <= '0';
                        sram_wen  <= '1';
                        driving   <= '0';
                        state     <= READ_B0;

                    elsif cpu_select = '1' and cpu_write_enable = '1' then
                        -- Latch address and data.  Drive first byte address with WEn
                        -- still high — one cycle of address setup before the write pulse.
                        base_addr  <= cpu_address(18 downto 0);
                        write_word <= cpu_write_data;
                        sram_addr  <= cpu_address(18 downto 0);
                        data_out   <= cpu_write_data(31 downto 24);
                        driving    <= '1';
                        sram_cen   <= '0';
                        sram_wen   <= '1';
                        sram_oen   <= '1';
                        state      <= WRITE_B0_PREP;
                    end if;

                -- ── Read sequence ────────────────────────────────────────────
                -- Address was presented during the previous state; sram_data now
                -- holds the byte that was at that address.  Latch it, advance address.
                when READ_B0 =>
                    assembled(31 downto 24) <= sram_data;
                    sram_addr <= std_logic_vector(unsigned(base_addr) + 1);
                    state     <= READ_B1;

                when READ_B1 =>
                    assembled(23 downto 16) <= sram_data;
                    sram_addr <= std_logic_vector(unsigned(base_addr) + 2);
                    state     <= READ_B2;

                when READ_B2 =>
                    assembled(15 downto 8) <= sram_data;
                    sram_addr <= std_logic_vector(unsigned(base_addr) + 3);
                    state     <= READ_B3;

                when READ_B3 =>
                    assembled(7 downto 0) <= sram_data;
                    sram_cen <= '1';
                    sram_oen <= '1';
                    state    <= IDLE;

                -- ── Write sequence ───────────────────────────────────────────
                -- Each byte uses two states: PREP (WEn=1, address stable) then
                -- EXEC (WEn=0, write pulse).  This guarantees tAW timing.
                when WRITE_B0_PREP =>
                    sram_wen <= '0';
                    state    <= WRITE_B0_EXEC;

                when WRITE_B0_EXEC =>
                    sram_wen  <= '1';
                    sram_addr <= std_logic_vector(unsigned(base_addr) + 1);
                    data_out  <= write_word(23 downto 16);
                    state     <= WRITE_B1_PREP;

                when WRITE_B1_PREP =>
                    sram_wen <= '0';
                    state    <= WRITE_B1_EXEC;

                when WRITE_B1_EXEC =>
                    sram_wen  <= '1';
                    sram_addr <= std_logic_vector(unsigned(base_addr) + 2);
                    data_out  <= write_word(15 downto 8);
                    state     <= WRITE_B2_PREP;

                when WRITE_B2_PREP =>
                    sram_wen <= '0';
                    state    <= WRITE_B2_EXEC;

                when WRITE_B2_EXEC =>
                    sram_wen  <= '1';
                    sram_addr <= std_logic_vector(unsigned(base_addr) + 3);
                    data_out  <= write_word(7 downto 0);
                    state     <= WRITE_B3_PREP;

                when WRITE_B3_PREP =>
                    sram_wen <= '0';
                    state    <= WRITE_B3_EXEC;

                when WRITE_B3_EXEC =>
                    sram_wen  <= '1';
                    sram_cen  <= '1';
                    driving   <= '0';
                    state     <= IDLE;

            end case;
        end if;
    end process;

end architecture rtl;
