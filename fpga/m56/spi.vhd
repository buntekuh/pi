-- spi.vhd — SPI master, Mode 0 (CPOL=0, CPHA=0)
--
-- Transmits and receives one byte per transfer.  The caller asserts 'start'
-- for one cycle with the byte to send in 'tx_data'.  'busy' goes high
-- immediately and falls when the last bit has been shifted in.  'rx_data'
-- holds the received byte once 'busy' falls.
--
-- MOSI idles high.  SCK idles low.  Data is shifted MSB first.
-- MISO is sampled on the last cycle of the SCK-high phase (maximum setup time).
--
-- SCK frequency = clk / (2 × (clk_div + 1))
-- At 12 MHz system clock:
--   clk_div = 14  →  SCK = 400 kHz   (SD card initialisation limit)
--   clk_div =  0  →  SCK =   6 MHz   (SD card data transfer)

library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;

entity spi_master is
    port (
        clk     : in  STD_LOGIC;
        resetn  : in  STD_LOGIC;
        -- CPU interface (word-level, connected via system.vhd registers)
        tx_data : in  STD_LOGIC_VECTOR(7 downto 0);
        rx_data : out STD_LOGIC_VECTOR(7 downto 0);
        clk_div : in  UNSIGNED(7 downto 0);   -- SCK half-period = clk_div+1 cycles
        start   : in  STD_LOGIC;              -- one-cycle pulse to begin transfer
        busy    : out STD_LOGIC;
        -- SPI pins
        sck     : out STD_LOGIC;
        mosi    : out STD_LOGIC;
        miso    : in  STD_LOGIC
    );
end entity spi_master;

architecture rtl of spi_master is

    type state_t is (IDLE, CLK_LOW, CLK_HIGH);
    signal state     : state_t;
    signal shift_reg : STD_LOGIC_VECTOR(7 downto 0);
    signal bit_cnt   : natural range 0 to 7;
    signal clk_cnt   : UNSIGNED(7 downto 0);
    signal sck_r     : STD_LOGIC;
    signal busy_r    : STD_LOGIC;

begin

    sck     <= sck_r;
    mosi    <= shift_reg(7);   -- MSB first; idles high because shift_reg resets to all-ones
    busy    <= busy_r;
    rx_data <= shift_reg;      -- valid (stable) once busy falls

    process(clk)
    begin
        if rising_edge(clk) then
            if resetn = '0' then
                state     <= IDLE;
                sck_r     <= '0';
                busy_r    <= '0';
                shift_reg <= (others => '1');
                bit_cnt   <= 0;
                clk_cnt   <= (others => '0');
            else
                case state is

                    when IDLE =>
                        if start = '1' then
                            shift_reg <= tx_data;
                            bit_cnt   <= 7;
                            clk_cnt   <= (others => '0');
                            busy_r    <= '1';
                            state     <= CLK_LOW;
                        end if;

                    when CLK_LOW =>
                        -- MOSI holds shift_reg(7); count half-period then raise SCK
                        if clk_cnt = clk_div then
                            sck_r   <= '1';
                            clk_cnt <= (others => '0');
                            state   <= CLK_HIGH;
                        else
                            clk_cnt <= clk_cnt + 1;
                        end if;

                    when CLK_HIGH =>
                        -- SCK high; sample MISO on last cycle (maximum setup time),
                        -- then lower SCK and shift the register
                        if clk_cnt = clk_div then
                            shift_reg <= shift_reg(6 downto 0) & miso;
                            sck_r     <= '0';
                            clk_cnt   <= (others => '0');
                            if bit_cnt = 0 then
                                busy_r <= '0';
                                state  <= IDLE;
                            else
                                bit_cnt <= bit_cnt - 1;
                                state   <= CLK_LOW;
                            end if;
                        else
                            clk_cnt <= clk_cnt + 1;
                        end if;

                end case;
            end if;
        end if;
    end process;

end architecture rtl;
