-- decoder.vhd — M56 instruction decoder
--
-- This module has NO clock — it is purely combinational (wires and gates,
-- no flip-flops).  Feed it a 32-bit instruction word and it instantly
-- outputs every field the CPU needs to execute that instruction.
--
-- Every M56 instruction has the same bit layout:
--
--   Bit  31..27   opcode  (5 bits) — which instruction is this?
--   Bit  26..24   mode    (3 bits) — addressing mode (modes 0-6 defined; 7 reserved)
--   Bit  23..20   regn    (4 bits) — register number (0-15)
--   Bit  19..0    imm20  (20 bits) — immediate value, offset, or 2nd register
--
-- For branch/call instructions (bra/bar/cal/car) the mode field carries
-- the condition code:
--   Bits 26..24: condition — 000=always 001=zero 010=nonzero 011=neg 100=non-neg
--   Bits 23..20: Rcmp — register to test against the condition
--
-- Whether the instruction is a subroutine call (saves return address) is
-- encoded in the opcode itself:
--   bra (10) / bar (11) — goto, no return address saved
--   cal (12) / car (13) — call, pushes return address onto stack

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity M56_Decoder is
    port (
        -- Input: the raw 32-bit instruction word from memory
        instruction : in  std_logic_vector(31 downto 0);

        -- Raw fields sliced straight out of the instruction
        opcode   : out std_logic_vector(4 downto 0);   -- bits 31..27
        mode     : out std_logic_vector(2 downto 0);   -- bits 26..24
        regn     : out std_logic_vector(3 downto 0);   -- bits 23..20
        imm20    : out std_logic_vector(19 downto 0);  -- bits 19..0
        imm32    : out std_logic_vector(31 downto 0);  -- imm20 sign-extended to 32 bits

        -- One flag per instruction family.
        -- Exactly one of these is '1' at any time; the rest are '0'.
        -- The CPU checks these instead of comparing the raw opcode number.
        is_mov   : out std_logic;   -- opcode  0 : move / load / store
        is_mvb   : out std_logic;   -- opcode  1 : move byte
        is_alu   : out std_logic;   -- opcode 2-6: add, sub, and, orr, xor
        is_not   : out std_logic;   -- opcode  7 : bitwise NOT
        is_shf   : out std_logic;   -- opcode  8 : logical shift
        is_sar   : out std_logic;   -- opcode  9 : arithmetic shift right
        is_bra   : out std_logic;   -- opcode 10 : absolute goto
        is_bar   : out std_logic;   -- opcode 11 : relative goto
        is_cal   : out std_logic;   -- opcode 12 : absolute subroutine call
        is_car   : out std_logic;   -- opcode 13 : relative subroutine call
        is_wfi   : out std_logic;   -- opcode 14 : wait for interrupt
        is_eai   : out std_logic;   -- opcode 15 : enable interrupts
        is_dai   : out std_logic;   -- opcode 16 : disable interrupts
        is_rti   : out std_logic;   -- opcode 17 : return from interrupt
        is_iba   : out std_logic;   -- opcode 18 : conditional indirect goto (target in register)
        is_ica   : out std_logic;   -- opcode 19 : conditional indirect call (target in register)

        -- Condition code for branch/call instructions (only meaningful when
        -- is_bra, is_bar, is_cal, is_car, is_iba, or is_ica is '1').
        bra_cond : out std_logic_vector(2 downto 0)    -- condition: 000=always 001=zero 010=nonzero
                                                       --            011=negative 100=non-negative
                                                       --            101=carry    110=no-carry
    );
end entity M56_Decoder;

architecture rtl of M56_Decoder is
    signal op : std_logic_vector(4 downto 0);  -- local copy of opcode bits
begin

    -- Slice the fixed fields directly out of the instruction word.
    -- In hardware this is literally just wires — no logic at all.
    op     <= instruction(31 downto 27);   -- top 5 bits = opcode
    opcode <= op;
    mode   <= instruction(26 downto 24);   -- next 3 bits = addressing mode
    regn   <= instruction(23 downto 20);   -- next 4 bits = register number
    imm20  <= instruction(19 downto 0);    -- bottom 20 bits = immediate / offset

    -- Sign-extend imm20 to 32 bits.
    -- If bit 19 (the MSB of imm20) is '1', the number is negative, so we fill
    -- the upper 12 bits with '1' to preserve its value in 32-bit arithmetic.
    imm32  <= (31 downto 20 => instruction(19)) & instruction(19 downto 0);

    -- One-hot decode: compare the opcode to each known value.
    is_mov <= '1' when op = "00000" else '0';   -- opcode  0
    is_mvb <= '1' when op = "00001" else '0';   -- opcode  1
    is_alu <= '1' when unsigned(op) >= 2        -- opcodes 2,3,4,5,6
                   and unsigned(op) <= 6 else '0';
    is_not <= '1' when op = "00111" else '0';   -- opcode  7
    is_shf <= '1' when op = "01000" else '0';   -- opcode  8
    is_sar <= '1' when op = "01001" else '0';   -- opcode  9
    is_bra <= '1' when op = "01010" else '0';   -- opcode 10
    is_bar <= '1' when op = "01011" else '0';   -- opcode 11
    is_cal <= '1' when op = "01100" else '0';   -- opcode 12
    is_car <= '1' when op = "01101" else '0';   -- opcode 13
    is_wfi <= '1' when op = "01110" else '0';   -- opcode 14
    is_eai <= '1' when op = "01111" else '0';   -- opcode 15
    is_dai <= '1' when op = "10000" else '0';   -- opcode 16
    is_rti <= '1' when op = "10001" else '0';   -- opcode 17
    is_iba <= '1' when op = "10010" else '0';   -- opcode 18
    is_ica <= '1' when op = "10011" else '0';   -- opcode 19

    -- The condition code is the 3-bit mode field — same field, always wired.
    -- The CPU only uses this when is_bra/is_bar/is_cal/is_car/is_iba/is_ica is asserted.
    bra_cond <= instruction(26 downto 24);

end architecture rtl;
