-- uart.vhd — Universal Asynchronous Receiver / Transmitter for M56 / Titania
--
-- UART is the standard term for a serial communication chip that sends and
-- receives data one bit at a time over a single wire in each direction.
-- "Asynchronous" means there is no shared clock between sender and receiver —
-- both sides agree on the speed (baud rate) in advance and stay in sync that way.
--
-- Translated from J1 CPU buart.v (James Bowman, BSD-2 Clause)
-- Original: https://github.com/jamesbowman/swapforth
--
-- Three entities in compilation order:
--   baud_generator   — fractional baud-rate generator (Bresenham / DDA)
--   transmitter   — transmitter
--   receiver    — receiver
--   uart     — top-level wrapper (use this one)
--
-- rx and tx are standard industry abbreviations: rx = receive, tx = transmit.
-- They appear as port and pin names throughout this file and in the XDC constraints.
--
-- Generic CLOCKFREQUENCY must match your board's clock in Hz.
-- Cmod A7-35T runs at 12 MHz, so the default is correct.
--
-- Connect baud to the constant x"0001_C200" (115200 decimal).
-- The baud_generator DDA converts this ratio to the right pulse frequency.

library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;

------------------------------------------------------------------------
-- baud_generator
--   Generates a single-cycle pulse on baud_tick at the baud rate.
--
--   The FPGA clock (12 MHz) and the baud rate (115200) don't divide
--   evenly, so a simple counter can't produce a perfectly regular pulse.
--
--   Instead, a running total is kept. Every clock tick, baud is added
--   to it. When the total reaches CLOCKFREQUENCY or above, a pulse is
--   fired and CLOCKFREQUENCY is subtracted, carrying the fractional
--   remainder forward into the next cycle. The error never grows -- it
--   just sloshes back and forth by less than one tick -- so pulses
--   average exactly the right rate over time.
--
--   Expressed as an algorithm:
--     counter = 0
--     every clock tick:
--         if counter >= 0:
--             fire pulse
--             counter = counter + baud - CLOCKFREQUENCY
--         else:
--             counter = counter + baud
--
--   The name "Bresenham" comes from the same idea used in Bresenham's
--   line-drawing algorithm: approximate a continuous slope on a discrete
--   grid by tracking accumulated error and rounding each step.
------------------------------------------------------------------------
entity baud_generator is
    generic (CLOCKFREQUENCY : integer := 12_000_000);
    port (
        clock    : in  STD_LOGIC;
        resetn   : in  STD_LOGIC;             -- reset signal; the trailing n is hardware convention for active low, meaning '1' = running normally, '0' = reset
        baud     : in  UNSIGNED(31 downto 0); -- desired baud rate in Hz (e.g. 115200)
        restart  : in  STD_LOGIC;             -- pulse high to reset the counter to zero
        baud_tick : out STD_LOGIC             -- one-cycle pulse at the baud rate
    );
end entity baud_generator;

architecture rtl of baud_generator is
    -- The computer is running at 12 MHz. The baud rate, i.e. the number of bits to send
    -- per second, must be kept exactly to ensure stable communication. The baud rate may
    -- not be divisible by 12 MHz. That is why we are creating a system that counts ticks,
    -- incrementing by the baud rate every tick. When it reaches 12 million it is time to
    -- send a transmission. The counter then restarts with the overflow value.
    --
    -- CLOCKFREQUENCY is stored as a signed 39-bit value so the arithmetic below stays
    -- signed. 39 bits gives safe headroom: baud is 32 bits, so signed arithmetic needs
    -- at least 33 bits. 39 is generous to avoid overflow at any reasonable clock/baud
    -- combination.
    constant CALCULATIONFREQUENCY : SIGNED(38 downto 0) := to_signed(CLOCKFREQUENCY, 39);

    -- counter is the running total. Bit 38 is the sign bit.
    -- When counter is negative (bit 38 = '1') we have not yet reached the threshold.
    -- When counter is zero or positive (bit 38 = '0') we have crossed the threshold
    -- and it is time to fire a pulse.
    signal counter               : SIGNED(38 downto 0) := (others => '0');

    -- increment is how much to add to counter each tick.
    -- If counter is still negative: just add baud (keep climbing toward zero).
    -- If counter went non-negative: add baud and subtract CLOCKFREQUENCY (fire a pulse,
    -- carry the remainder forward so the fractional part is never lost).
    signal increment             : SIGNED(38 downto 0);

    -- next_counter_value is the value counter will take on the next rising clock edge,
    -- computed combinationally this cycle so it is ready the moment the edge arrives.
    signal next_counter_value    : SIGNED(38 downto 0);
begin
    -- Choose the increment based on the sign of the current counter.
    -- SIGNED(resize(baud, 39)) widens baud from 32-bit unsigned to 39-bit signed
    -- so it can be used in signed arithmetic with counter and CALCULATIONFREQUENCY.
    increment <= SIGNED(resize(baud, 39)) when counter(38) = '1'           -- counter < 0: just add baud
                 else SIGNED(resize(baud, 39)) - CALCULATIONFREQUENCY;     -- counter >= 0: add baud, subtract CLOCKFREQUENCY

    -- If restart is pulsed (receiver detected a start bit), reset to zero
    -- so the pulse timing locks onto the incoming byte edge.
    -- Otherwise advance the counter.
    next_counter_value <= (others => '0') when restart = '1' else counter + increment;

    -- baud_tick fires (goes high for one cycle) when counter is non-negative.
    -- counter(38) is the sign bit: '0' means non-negative, so we invert it.
    baud_tick <= not counter(38);

    process(clock, resetn)
    begin
        if resetn = '0' then
            counter <= (others => '0');           -- clear counter on reset
        elsif rising_edge(clock) then
            counter <= next_counter_value;        -- advance counter every tick
        end if;
    end process;
end architecture rtl;


------------------------------------------------------------------------
-- transmitter
--   8N1 transmitter.
--
--   8N1 is the framing format. Every byte is sent as 10 bits in a row
--   on one wire:
--     1 start bit  (always 0) -- drops the wire low to tell the receiver
--                                 "a byte is coming"
--     8 data bits              -- the byte itself, sent lowest bit first
--     1 stop bit   (always 1) -- brings the wire back high
--   "No parity" (the N) means there is no extra error-checking bit.
--   The wire idles high, so the falling edge of the start bit is how
--   the receiver knows to start listening.
--
--   How to use: pulse wr high for exactly one clock cycle while tx_data
--   holds the byte to send. The transmitter loads it immediately and
--   starts shifting bits out. busy goes high at that moment and stays
--   high for the whole 10-bit transmission (~87 us at 115200 baud).
--   Check busy before sending the next byte.
------------------------------------------------------------------------
library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;

entity transmitter is
    generic (CLOCKFREQUENCY : integer := 12_000_000);
    port (
        clock    : in  STD_LOGIC;
        resetn   : in  STD_LOGIC;
        baud     : in  UNSIGNED(31 downto 0);          -- baud rate in Hz
        wr       : in  STD_LOGIC;                      -- pulse high for one cycle to send tx_data
        tx_data  : in  STD_LOGIC_VECTOR(7 downto 0);   -- byte to transmit
        tx       : out STD_LOGIC;                      -- serial output wire (to USB)
        busy     : out STD_LOGIC                       -- '1' while transmission is in progress
    );
end entity transmitter;

architecture rtl of transmitter is
    -- bitcount counts down from 10 to 0 as bits are sent.
    -- 0 means idle; anything else means a transmission is in progress.
    signal bitcount  : UNSIGNED(3 downto 0) := (others => '0');

    -- shifter holds the bits waiting to be sent.
    -- Layout at load time: [ data[7:0], start_bit=0 ] — 9 bits total.
    -- Each baud_tick the current lowest bit goes out on tx, the whole register
    -- shifts right by one, and a '1' fills in from the top. So the bits go
    -- out lowest-first, and as each bit leaves, the next one moves into
    -- position. Once all data bits are gone, only the '1's remain, which
    -- hold the line high as the stop bit.
    signal shifter   : STD_LOGIC_VECTOR(8 downto 0) := (others => '1');

    signal baud_tick : STD_LOGIC;   -- baud-rate tick from baud_generator
    signal sending   : STD_LOGIC;   -- '1' while bitcount > 0
    signal starting  : STD_LOGIC;   -- '1' when wr is pulsed and we are not already sending
begin
    sending  <= '1' when bitcount /= 0 else '0';  -- are we mid-transmission?
    busy     <= sending;                           -- expose sending state to the outside
    starting <= wr and not sending;                -- only start if idle (ignore wr when busy)

    -- baud_generator produces one pulse per bit period at the requested baud rate.
    -- restart is tied to '0': the transmitter runs at a free-running rate,
    -- unlike the receiver which must re-lock onto each incoming start bit.
    baud_generator: entity work.baud_generator
        generic map (CLOCKFREQUENCY => CLOCKFREQUENCY)
        port map (
            clock     => clock,
            resetn    => resetn,
            baud      => baud,
            restart   => '0',          -- transmitter runs free, no need to resync
            baud_tick => baud_tick
        );

    process(clock, resetn)
    begin
        if resetn = '0' then              -- resetn is active on 0
            tx       <= '1';              -- idle line is high
            bitcount <= (others => '0');  -- not sending
            shifter  <= (others => '1');  -- all ones = line high
        elsif rising_edge(clock) then

            -- Load a new byte when wr is pulsed and we are idle.
            -- Pack the byte and start bit into the shifter as [ data, 0 ].
            -- The '0' at the lowest bit position is the start bit — it goes out first.
            if starting = '1' then
                shifter  <= tx_data & '0';           -- [bit7..bit0, start=0]
                bitcount <= to_unsigned(10, 4);      -- 1 start + 8 data + 1 stop = 10 bits
            end if;

            -- On each baud tick, shift one bit out.
            -- tx gets the lowest bit of the shifter (the next bit to send).
            -- A '1' is shifted in from the top — this becomes the stop bit
            -- after all 8 data bits have been sent.
            -- bitcount decrements toward zero; when it reaches zero, sending goes low.
            if sending = '1' and baud_tick = '1' then
                tx       <= shifter(0);                   -- send the next bit
                shifter  <= '1' & shifter(8 downto 1);   -- shift right, '1' fills from top
                bitcount <= bitcount - 1;
            end if;

        end if;
    end process;
end architecture rtl;


------------------------------------------------------------------------
-- receiver
--   8N1 receiver.
--
--   Receiving is harder than transmitting because the receiver does not
--   know exactly when the sender will start. The strategy is:
--
--   1. Watch the rx line while idle. The line normally sits high.
--      A falling edge (1 -> 0) is the start of a start bit.
--
--   2. Re-lock the baud_generator counter to that edge, then run baud_generator
--      at 2x the baud rate. At 2x rate, each bit period is two ticks.
--      Sampling at tick 3, 5, 7, ... (odd ticks, 2x rate) lands in the
--      middle of each bit, where the signal is most stable.
--
--   3. The rx line passes through a 3-stage shift register (receive_filter)
--      before being used. This is a metastability filter: if rx changes at
--      almost the same moment as the clock edge, the first flip-flop
--      may briefly output an invalid value. By the third stage it has
--      settled. The middle stage (receive_filter(1)) is what gets sampled.
--
--   4. After 8 data bits have been sampled, valid goes high and data
--      holds the received byte. Pulse rd for one clock to acknowledge
--      and clear valid, making the receiver ready for the next byte.
------------------------------------------------------------------------
library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;

entity receiver is
    generic (CLOCKFREQUENCY : integer := 12_000_000);
    port (
        clock  : in  STD_LOGIC;
        resetn : in  STD_LOGIC;
        baud   : in  UNSIGNED(31 downto 0);          -- baud rate in Hz
        rx     : in  STD_LOGIC;                      -- serial input wire (from PC)
        rd     : in  STD_LOGIC;                      -- pulse high for one cycle to clear valid
        valid  : out STD_LOGIC;                      -- '1' when a complete byte is in data
        data   : out STD_LOGIC_VECTOR(7 downto 0)    -- the received byte
    );
end entity receiver;

architecture rtl of receiver is
    -- bitcount counts up from 0 as bits are received, at 2x baud rate.
    -- 31 ("11111") is the idle sentinel — means we are waiting for a start bit.
    -- When a start bit is detected it resets to 0.
    -- byte_ready fires when bitcount reaches 18 (all 8 data bits captured).
    signal bitcount            : UNSIGNED(4 downto 0) := (others => '1');

    -- shifter accumulates the received bits, lowest bit first.
    -- After 8 samples it holds the complete byte.
    signal shifter             : STD_LOGIC_VECTOR(7 downto 0) := (others => '0');

    -- receive_filter is the 3-stage metastability filter for the rx line.
    -- receive_filter(0) = oldest sample, receive_filter(2) = newest (just captured).
    -- receive_filter(1) is the settled value used for edge detection and sampling.
    signal receive_filter      : STD_LOGIC_VECTOR(2 downto 0) := "111";
    signal next_receive_filter : STD_LOGIC_VECTOR(2 downto 0);

    signal baud_tick           : STD_LOGIC;   -- 2x baud tick from baud_generator
    signal idle                : STD_LOGIC;   -- '1' when waiting for a start bit
    signal byte_ready          : STD_LOGIC;   -- '1' when all 8 data bits have been received
    signal start_edge          : STD_LOGIC;   -- '1' on the cycle a falling edge is detected
    signal sample              : STD_LOGIC;   -- '1' when it is time to capture a data bit
    signal next_bitcount       : UNSIGNED(4 downto 0);     -- next value of bitcount
    signal double_baud         : UNSIGNED(31 downto 0);    -- baud * 2 fed to baud_generator
begin
    -- Advance the metastability pipeline: shift rx in from the right.
    next_receive_filter <= receive_filter(1 downto 0) & rx;

    -- idle is true when bitcount is at its sentinel value (all ones = 31).
    idle      <= '1' when bitcount = "11111" else '0';

    -- byte_ready fires when bitcount reaches 18.
    -- At 2x baud rate: start bit takes counts 0-1, then 8 data bits take
    -- counts 2-17 (2 counts per bit), so count 18 means all data is in.
    byte_ready <= '1' when bitcount = to_unsigned(18, 5) else '0';

    -- Detect the falling edge of the start bit: we were idle, and the
    -- last two filtered rx samples are "1 then 0" (next_receive_filter[2:1] = "10").
    start_edge <= '1' when idle = '1' and next_receive_filter(2 downto 1) = "10" else '0';

    -- Double the baud rate by shifting left one bit (multiply by 2).
    -- baud_generator runs at 2x so we get two ticks per bit and can sample
    -- at the centre of each bit rather than the edge.
    double_baud <= baud(30 downto 0) & '0';

    -- Sample the data bit when:
    --   bitcount > 2        (past the start bit)
    --   bitcount is odd     (we are at a bit centre in the 2x timing)
    --   byte_ready = '0'    (we have not already finished)
    --   baud_tick = '1'     (this is a baud tick)
    sample <= '1' when (bitcount > 2) and (bitcount(0) = '1')
                       and (byte_ready = '0') and (baud_tick = '1')
              else '0';

    -- Pass valid and data to the outside world.
    valid <= byte_ready;
    data  <= shifter;

    -- Compute the next bitcount:
    --   start bit detected      → reset to 0 (begin counting this byte)
    --   mid-reception tick      → increment
    --   byte complete + rd      → return to idle sentinel (31)
    --   otherwise               → hold current value
    next_bitcount <= to_unsigned(0, 5) when start_edge = '1' else
                     bitcount + 1      when idle = '0' and byte_ready = '0' and baud_tick = '1' else
                     "11111"           when byte_ready = '1' and rd = '1' else
                     bitcount;

    -- baud_generator runs at 2x baud and is restarted on each start-bit edge
    -- so the sampling stays locked to the incoming byte.
    baud_generator: entity work.baud_generator
        generic map (CLOCKFREQUENCY => CLOCKFREQUENCY)
        port map (
            clock     => clock,
            resetn    => resetn,
            baud      => double_baud,    -- 2x baud rate
            restart   => start_edge,     -- re-lock to each start bit
            baud_tick => baud_tick
        );

    process(clock, resetn)
    begin
        if resetn = '0' then
            receive_filter <= "111";           -- rx line idles high
            bitcount       <= "11111";         -- idle sentinel
            shifter        <= (others => '0');
        elsif rising_edge(clock) then
            receive_filter <= next_receive_filter;   -- advance the metastability filter
            bitcount       <= next_bitcount;         -- advance the bit counter

            -- On each sample tick, shift the settled rx value (receive_filter(1)) into
            -- the high end of the shifter. Bits arrive lowest-first, so shifting into
            -- the top and right-shifting reconstructs the byte correctly.
            if sample = '1' then
                shifter <= receive_filter(1) & shifter(7 downto 1);
            end if;
        end if;
    end process;
end architecture rtl;


------------------------------------------------------------------------
-- uart — top-level wrapper
--
-- Instantiate this in your top-level or M56 bus decoder.
--
-- Typical usage at 115200 bps:
--   uart0: entity work.uart
--       generic map (CLOCKFREQUENCY => 12_000_000)
--       port map (
--           clock    => clock,
--           resetn   => resetn,
--           baud     => to_unsigned(115200, 32),
--           rx       => uart_rxd,
--           tx       => transmitterd,
--           rd       => uart_rd,
--           wr       => uart_wr,
--           valid    => uart_valid,
--           busy     => uart_busy,
--           tx_data  => tx_byte,
--           rx_data  => rx_byte
--       );
------------------------------------------------------------------------
library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;

entity uart is
    generic (CLOCKFREQUENCY : integer := 12_000_000);
    port (
        clock    : in  STD_LOGIC;
        resetn   : in  STD_LOGIC;
        baud     : in  UNSIGNED(31 downto 0);          -- baud rate in Hz (e.g. 115200)
        rx       : in  STD_LOGIC;                      -- serial input  (from PC)
        tx       : out STD_LOGIC;                      -- serial output (to PC)
        rd       : in  STD_LOGIC;                      -- pulse to acknowledge received byte
        wr       : in  STD_LOGIC;                      -- pulse to transmit tx_data
        valid    : out STD_LOGIC;                      -- '1' when rx_data holds a new byte
        busy     : out STD_LOGIC;                      -- '1' while transmitting
        tx_data  : in  STD_LOGIC_VECTOR(7 downto 0);   -- byte to send
        rx_data  : out STD_LOGIC_VECTOR(7 downto 0)    -- byte received
    );
end entity uart;

architecture rtl of uart is
begin
    -- Wire up the receiver.
    receiver: entity work.receiver
        generic map (CLOCKFREQUENCY => CLOCKFREQUENCY)
        port map (
            clock  => clock,
            resetn => resetn,
            baud   => baud,
            rx     => rx,
            rd     => rd,
            valid  => valid,
            data   => rx_data
        );

    -- Wire up the transmitter.
    transmitter: entity work.transmitter
        generic map (CLOCKFREQUENCY => CLOCKFREQUENCY)
        port map (
            clock   => clock,
            resetn  => resetn,
            baud    => baud,
            wr      => wr,
            tx_data => tx_data,
            tx      => tx,
            busy    => busy
        );
end architecture rtl;
