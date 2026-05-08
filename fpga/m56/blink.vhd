-- blink.vhd — minimal Cmod A7 test: BTN0 lights LED0
-- No CPU, no UART, no BRAM.  Pure combinational wiring.
-- If this works, the toolchain and board programming are confirmed good.

library IEEE;
use IEEE.STD_LOGIC_1164.ALL;

entity SOC is
    port (
        clk          : in  STD_LOGIC;
        uart_rxd_in  : in  STD_LOGIC;
        uart_txd_out : out STD_LOGIC;
        btn          : in  STD_LOGIC_VECTOR(1 downto 0);
        led          : out STD_LOGIC_VECTOR(1 downto 0)
    );
end entity SOC;

architecture rtl of SOC is
begin
    led(0)       <= btn(0);
    led(1)       <= btn(1);
    uart_txd_out <= uart_rxd_in;   -- loopback: echo without CPU
end architecture rtl;
