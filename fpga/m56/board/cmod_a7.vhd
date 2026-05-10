-- board/cmod_a7.vhd — Hardware constants for the Digilent Cmod A7-35T
--
-- This package collects every value that is specific to this board.
-- To port the M56 system to a different board, replace this file and
-- the accompanying cmod_a7.xdc pin constraints — nothing else should
-- need to change.
--
-- The Cmod A7-35T carries a Xilinx Artix-7 XC7A35T FPGA running from
-- a 12 MHz on-board crystal oscillator.

library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;

package board_pkg is

    -- Clock frequency of the on-board crystal oscillator in Hz.
    -- All timing-sensitive modules (UART baud generator) derive their
    -- timing from this value.
    constant CLOCK_FREQUENCY : integer := 12_000_000;

    -- UART baud rate in bits per second.
    -- 115200 is the universally supported default for USB-serial adapters.
    -- Both sides (board and PC terminal) must agree on this value.
    constant BAUD_RATE : integer := 115_200;

    -- Program memory size in 32-bit words.
    -- 1024 words = 4 KB. Large enough for firmware, small enough to fit
    -- comfortably in the block RAM of the Artix-7 35T.
    constant BLOCK_RAM_WORDS : integer := 1024;

end package board_pkg;
