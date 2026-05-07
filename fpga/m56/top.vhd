-- top.vhd — Titania M56 top level for Cmod A7-35T
--
-- Entity name SOC matches the learn-fpga run_cmod_a7.sh convention.
-- Build: bash build.sh  (assembles firmware, runs ghdl → yosys → nextpnr)
--
-- Address decode:
--   mem_addr[22] = '0'  →  BRAM    (0x000000 – 0x3FFFFF)
--   mem_addr[22] = '1'  →  UART    (0x400000)
--
-- UART word (read):  bit 9 = TX busy, bit 8 = RX valid, bits 7:0 = received byte
-- UART word (write): bits 7:0 = byte to transmit
--
-- BTN0 held = reset.  LED0 = RX waiting.  LED1 = TX busy.

library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;
use work.firmware_pkg.ALL;

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

    constant BAUD : UNSIGNED(31 downto 0) := to_unsigned(115200, 32);

    signal resetn : STD_LOGIC;

    -- CPU bus
    signal mem_addr : STD_LOGIC_VECTOR(31 downto 0);
    signal mem_rdat : STD_LOGIC_VECTOR(31 downto 0);
    signal mem_wdat : STD_LOGIC_VECTOR(31 downto 0);
    signal mem_we   : STD_LOGIC;
    signal mem_re   : STD_LOGIC;

    -- Address decode
    signal sel_uart : STD_LOGIC;

    -- BRAM initialised from assembled firmware package
    signal bram      : bram_init_t := FIRMWARE;
    signal bram_rdat : STD_LOGIC_VECTOR(31 downto 0);

    -- UART
    signal uart_valid   : STD_LOGIC;
    signal uart_busy    : STD_LOGIC;
    signal uart_rx_data : STD_LOGIC_VECTOR(7 downto 0);

begin

    resetn   <= not btn(0);
    sel_uart <= mem_addr(22);

    mem_rdat <= bram_rdat when sel_uart = '0' else
                (31 downto 10 => '0') & uart_busy & uart_valid & uart_rx_data;

    -- Synchronous BRAM — 1-cycle read latency
    process(clk)
    begin
        if rising_edge(clk) then
            if sel_uart = '0' then
                if mem_we = '1' then
                    bram(to_integer(unsigned(mem_addr(16 downto 2)))) <= mem_wdat;
                end if;
                if mem_re = '1' then
                    bram_rdat <= bram(to_integer(unsigned(mem_addr(16 downto 2))));
                end if;
            end if;
        end if;
    end process;

    -- UART: mem_re/mem_we are one-cycle pulses from the CPU
    uart0: entity work.buart
        generic map (CLKFREQ => 12_000_000)
        port map (
            clk     => clk,
            resetn  => resetn,
            baud    => BAUD,
            rx      => uart_rxd_in,
            tx      => uart_txd_out,
            rd      => mem_re and sel_uart and not mem_we,
            wr      => mem_we and sel_uart,
            valid   => uart_valid,
            busy    => uart_busy,
            tx_data => mem_wdat(7 downto 0),
            rx_data => uart_rx_data
        );

    cpu0: entity work.m56_cpu
        port map (
            clk      => clk,
            resetn   => resetn,
            mem_addr => mem_addr,
            mem_rdat => mem_rdat,
            mem_wdat => mem_wdat,
            mem_we   => mem_we,
            mem_re   => mem_re
        );

    led(0) <= uart_valid;
    led(1) <= uart_busy;

end architecture rtl;
