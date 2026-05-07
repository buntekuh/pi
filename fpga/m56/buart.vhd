-- buart.vhd — UART for M56 / Titania
-- Translated from J1 CPU buart.v (James Bowman, BSD-2 Clause)
-- Original: https://github.com/jamesbowman/swapforth
--
-- Three entities in compilation order:
--   baudgen   — fractional baud-rate generator (Bresenham / DDA)
--   uart_tx   — transmitter
--   rxuart    — receiver
--   buart     — top-level wrapper (use this one)
--
-- Generic CLKFREQ must match your board's clock in Hz.
-- Cmod A7-35T runs at 12 MHz, so the default is correct.
--
-- Connect baud to the constant x"0001_C200" (115200 decimal).
-- The baudgen DDA converts this ratio to the right pulse frequency.

library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;

------------------------------------------------------------------------
-- baudgen
--   Generates a single-cycle pulse on ser_clk at the requested rate.
--   Uses a Bresenham accumulator: add baud each tick, subtract CLKFREQ
--   when the accumulator goes positive, so pulses average baud/CLKFREQ.
------------------------------------------------------------------------
entity baudgen is
    generic (CLKFREQ : integer := 12_000_000);
    port (
        clk     : in  STD_LOGIC;
        resetn  : in  STD_LOGIC;   -- active-low synchronous-style, async here
        baud    : in  UNSIGNED(31 downto 0);
        restart : in  STD_LOGIC;
        ser_clk : out STD_LOGIC
    );
end entity baudgen;

architecture rtl of baudgen is
    constant ACLKFREQ : SIGNED(38 downto 0) := to_signed(CLKFREQ, 39);
    signal d    : SIGNED(38 downto 0) := (others => '0');
    signal dInc : SIGNED(38 downto 0);
    signal dN   : SIGNED(38 downto 0);
begin
    dInc    <= SIGNED(resize(baud, 39)) when d(38) = '1'
               else SIGNED(resize(baud, 39)) - ACLKFREQ;
    dN      <= (others => '0') when restart = '1' else d + dInc;
    ser_clk <= not d(38);

    process(clk, resetn)
    begin
        if resetn = '0' then
            d <= (others => '0');
        elsif rising_edge(clk) then
            d <= dN;
        end if;
    end process;
end architecture rtl;


------------------------------------------------------------------------
-- uart_tx
--   8N1 transmitter. Assert wr for one clock with tx_data valid.
--   Busy goes high immediately and stays high until the stop bit is done.
------------------------------------------------------------------------
library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;

entity uart_tx is
    generic (CLKFREQ : integer := 12_000_000);
    port (
        clk     : in  STD_LOGIC;
        resetn  : in  STD_LOGIC;
        baud    : in  UNSIGNED(31 downto 0);
        wr      : in  STD_LOGIC;
        tx_data : in  STD_LOGIC_VECTOR(7 downto 0);
        tx      : out STD_LOGIC;
        busy    : out STD_LOGIC
    );
end entity uart_tx;

architecture rtl of uart_tx is
    signal bitcount : UNSIGNED(3 downto 0) := (others => '0');
    signal shifter  : STD_LOGIC_VECTOR(8 downto 0) := (others => '1');
    signal ser_clk  : STD_LOGIC;
    signal sending  : STD_LOGIC;
    signal starting : STD_LOGIC;
begin
    sending  <= '1' when bitcount /= 0 else '0';
    busy     <= sending;
    starting <= wr and not sending;

    bg: entity work.baudgen
        generic map (CLKFREQ => CLKFREQ)
        port map (
            clk     => clk,
            resetn  => resetn,
            baud    => baud,
            restart => '0',
            ser_clk => ser_clk
        );

    process(clk, resetn)
    begin
        if resetn = '0' then
            tx       <= '1';
            bitcount <= (others => '0');
            shifter  <= (others => '1');
        elsif rising_edge(clk) then
            if starting = '1' then
                -- Shifter layout: [data[7:0], start_bit=0]
                -- Shift right each ser_clk; tx gets LSB; 1s fill from MSB (stop bits)
                shifter  <= tx_data & '0';
                bitcount <= to_unsigned(10, 4);  -- 1 start + 8 data + 1 stop
            end if;
            if sending = '1' and ser_clk = '1' then
                tx      <= shifter(0);
                shifter <= '1' & shifter(8 downto 1);
                bitcount <= bitcount - 1;
            end if;
        end if;
    end process;
end architecture rtl;


------------------------------------------------------------------------
-- rxuart
--   8N1 receiver with metastability filter (3-stage rx pipeline).
--   Samples at 2x baud rate, locks onto falling start-bit edge,
--   then samples at bit-centre positions 3,5,7,...,17.
--   Assert rd for one clock to acknowledge a received byte and clear valid.
------------------------------------------------------------------------
library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;

entity rxuart is
    generic (CLKFREQ : integer := 12_000_000);
    port (
        clk    : in  STD_LOGIC;
        resetn : in  STD_LOGIC;
        baud   : in  UNSIGNED(31 downto 0);
        rx     : in  STD_LOGIC;
        rd     : in  STD_LOGIC;
        valid  : out STD_LOGIC;
        data   : out STD_LOGIC_VECTOR(7 downto 0)
    );
end entity rxuart;

architecture rtl of rxuart is
    signal bitcount  : UNSIGNED(4 downto 0) := (others => '1');
    signal shifter   : STD_LOGIC_VECTOR(7 downto 0) := (others => '0');
    signal hh        : STD_LOGIC_VECTOR(2 downto 0) := "111";
    signal hhN       : STD_LOGIC_VECTOR(2 downto 0);
    signal ser_clk   : STD_LOGIC;
    signal idle      : STD_LOGIC;
    signal valid_s   : STD_LOGIC;
    signal startbit  : STD_LOGIC;
    signal sample    : STD_LOGIC;
    signal bitcountN : UNSIGNED(4 downto 0);
    signal baud2     : UNSIGNED(31 downto 0);
begin
    hhN     <= hh(1 downto 0) & rx;
    idle    <= '1' when bitcount = "11111" else '0';
    valid_s <= '1' when bitcount = to_unsigned(18, 5) else '0';
    startbit <= '1' when idle = '1' and hhN(2 downto 1) = "10" else '0';  -- falling edge on rx

    -- baudgen runs at 2x baud so we can detect the start-bit centre
    baud2 <= baud(30 downto 0) & '0';

    -- Sample at odd bitcount positions 3,5,7,...,17 (bit centres at 2x rate)
    sample <= '1' when (bitcount > 2) and (bitcount(0) = '1')
                       and (valid_s = '0') and (ser_clk = '1')
              else '0';

    valid <= valid_s;
    data  <= shifter;

    bitcountN <= to_unsigned(0, 5) when startbit = '1' else
                 bitcount + 1      when idle = '0' and valid_s = '0' and ser_clk = '1' else
                 "11111"           when valid_s = '1' and rd = '1' else
                 bitcount;

    bg: entity work.baudgen
        generic map (CLKFREQ => CLKFREQ)
        port map (
            clk     => clk,
            resetn  => resetn,
            baud    => baud2,
            restart => startbit,
            ser_clk => ser_clk
        );

    process(clk, resetn)
    begin
        if resetn = '0' then
            hh       <= "111";
            bitcount <= "11111";
            shifter  <= (others => '0');
        elsif rising_edge(clk) then
            hh       <= hhN;
            bitcount <= bitcountN;
            if sample = '1' then
                shifter <= hh(1) & shifter(7 downto 1);  -- LSB first
            end if;
        end if;
    end process;
end architecture rtl;


------------------------------------------------------------------------
-- buart — top-level wrapper
--
-- Instantiate this in your top-level or M56 bus decoder.
--
-- Typical usage at 115200 bps:
--   uart0: entity work.buart
--       generic map (CLKFREQ => 12_000_000)
--       port map (
--           clk     => clk,
--           resetn  => resetn,
--           baud    => to_unsigned(115200, 32),
--           rx      => uart_rxd,
--           tx      => uart_txd,
--           rd      => uart_rd,
--           wr      => uart_wr,
--           valid   => uart_valid,
--           busy    => uart_busy,
--           tx_data => tx_byte,
--           rx_data => rx_byte
--       );
------------------------------------------------------------------------
library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;

entity buart is
    generic (CLKFREQ : integer := 12_000_000);
    port (
        clk     : in  STD_LOGIC;
        resetn  : in  STD_LOGIC;
        baud    : in  UNSIGNED(31 downto 0);
        rx      : in  STD_LOGIC;
        tx      : out STD_LOGIC;
        rd      : in  STD_LOGIC;
        wr      : in  STD_LOGIC;
        valid   : out STD_LOGIC;
        busy    : out STD_LOGIC;
        tx_data : in  STD_LOGIC_VECTOR(7 downto 0);
        rx_data : out STD_LOGIC_VECTOR(7 downto 0)
    );
end entity buart;

architecture rtl of buart is
begin
    rx_inst: entity work.rxuart
        generic map (CLKFREQ => CLKFREQ)
        port map (
            clk    => clk,
            resetn => resetn,
            baud   => baud,
            rx     => rx,
            rd     => rd,
            valid  => valid,
            data   => rx_data
        );

    tx_inst: entity work.uart_tx
        generic map (CLKFREQ => CLKFREQ)
        port map (
            clk     => clk,
            resetn  => resetn,
            baud    => baud,
            wr      => wr,
            tx_data => tx_data,
            tx      => tx,
            busy    => busy
        );
end architecture rtl;
