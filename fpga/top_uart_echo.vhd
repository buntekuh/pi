-- top_uart_echo.vhd — UART loopback test for Cmod A7-35T
--
-- Flash this before integrating with M56 to verify the UART works.
-- Open a serial terminal (115200 8N1) and type — you should see each
-- character echoed back immediately.
--
-- BTN0 = active-high reset (mapped to resetn via inversion below)
-- LED0 = lit when UART RX has data waiting
-- LED1 = lit while UART TX is busy

library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;

entity top_uart_echo is
    port (
        -- Cmod A7 12 MHz oscillator
        clk         : in  STD_LOGIC;

        -- USB-UART via FT2232HQ on Cmod A7
        -- Verify pin assignments against Digilent master XDC before synthesis
        uart_rxd_in  : in  STD_LOGIC;   -- data arriving from PC
        uart_txd_out : out STD_LOGIC;   -- data going to PC

        -- Buttons (active high on Cmod A7)
        btn          : in  STD_LOGIC_VECTOR(1 downto 0);

        -- LEDs (active high)
        led          : out STD_LOGIC_VECTOR(1 downto 0)
    );
end entity top_uart_echo;

architecture rtl of top_uart_echo is

    constant BAUD : UNSIGNED(31 downto 0) := to_unsigned(115200, 32);

    signal resetn  : STD_LOGIC;
    signal valid   : STD_LOGIC;
    signal busy    : STD_LOGIC;
    signal rx_data : STD_LOGIC_VECTOR(7 downto 0);
    signal rd      : STD_LOGIC;
    signal wr      : STD_LOGIC;

begin
    resetn <= not btn(0);  -- BTN0 held = reset

    uart0: entity work.buart
        generic map (CLKFREQ => 12_000_000)
        port map (
            clk     => clk,
            resetn  => resetn,
            baud    => BAUD,
            rx      => uart_rxd_in,
            tx      => uart_txd_out,
            rd      => rd,
            wr      => wr,
            valid   => valid,
            busy    => busy,
            tx_data => rx_data,   -- echo: feed received byte straight back
            rx_data => rx_data
        );

    -- Echo: when a byte arrives and TX is free, transmit it and ack the RX
    rd  <= valid and not busy;
    wr  <= valid and not busy;

    led(0) <= valid;  -- RX data waiting
    led(1) <= busy;   -- TX transmitting

end architecture rtl;
