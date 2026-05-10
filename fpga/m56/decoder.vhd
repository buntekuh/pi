-- decoder.vhd — M56 instruction decoder
--
-- This module has NO clock — it is purely combinational (wires and gates,
-- no flip-flops).  Feed it a 32-bit instruction word and it instantly
-- outputs every field the CPU needs to execute that instruction.
--
-- Every M56 instruction has the same bit layout:
--
--   Bit  31..27   opcode  (5 bits) — which instruction is this?
--   Bit  26..23   mode    (4 bits) — how are the operands addressed?
--   Bit  22..19   reg     (4 bits) — register number (0-15)
--   Bit  18..0    imm19  (19 bits) — immediate value, offset, or 2nd register
--
-- For jump instructions (jmp / jpr) the mode field is reused:
--   Bit  26       jmp_sub — 1 means "save return address" (subroutine call)
--   Bit  25..23   jmp_cond — which condition must be true to jump?
--   Bit  22..19   reg     — register to test against the condition

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity M56_Decoder is
    port (
        -- Input: the raw 32-bit instruction word from memory
        instruction : in  std_logic_vector(31 downto 0);

        -- Raw fields sliced straight out of the instruction
        opcode   : out std_logic_vector(4 downto 0);   -- bits 31..27
        mode     : out std_logic_vector(3 downto 0);   -- bits 26..23
        reg      : out std_logic_vector(3 downto 0);   -- bits 22..19
        imm19    : out std_logic_vector(18 downto 0);  -- bits 18..0
        imm32    : out std_logic_vector(31 downto 0);  -- imm19 sign-extended to 32 bits
                                                       -- (negative numbers keep their sign)

        -- One flag per instruction family.
        -- Exactly one of these is '1' at any time; the rest are '0'.
        -- The CPU checks these instead of comparing the raw opcode number.
        is_mov   : out std_logic;   -- opcode  0 : move / load / store
        is_mvb   : out std_logic;   -- opcode  1 : move byte (not yet wired in CPU)
        is_alu   : out std_logic;   -- opcode 2-6: add, sub, and, orr, xor
        is_not   : out std_logic;   -- opcode  7 : bitwise NOT (not yet wired)
        is_shf   : out std_logic;   -- opcode  8 : logical shift (not yet wired)
        is_sar   : out std_logic;   -- opcode  9 : arithmetic shift right (not yet wired)
        is_jmp   : out std_logic;   -- opcode 10 : absolute jump (not yet wired)
        is_jpr   : out std_logic;   -- opcode 11 : relative jump — used by echo.s
        is_wfi   : out std_logic;   -- opcode 12 : wait for interrupt
        is_eai   : out std_logic;   -- opcode 13 : enable interrupts
        is_dai   : out std_logic;   -- opcode 14 : disable interrupts
        is_rti   : out std_logic;   -- opcode 15 : return from interrupt (enable interrupts, jump to R13)

        -- Jump-specific sub-fields (only meaningful when is_jmp or is_jpr is '1')
        jmp_sub  : out std_logic;                      -- '1' = subroutine call (save return address)
        jmp_cond : out std_logic_vector(2 downto 0)    -- condition: 000=always 001=zero 010=nonzero
                                                       --            011=negative 100=non-negative
    );
end entity M56_Decoder;

architecture rtl of M56_Decoder is
    signal op : std_logic_vector(4 downto 0);  -- local copy of opcode bits
begin

    -- Slice the fixed fields directly out of the instruction word.
    -- In hardware this is literally just wires — no logic at all.
    op     <= instruction(31 downto 27);   -- top 5 bits = opcode
    opcode <= op;
    mode   <= instruction(26 downto 23);   -- next 4 bits = usually addressing mode
    reg    <= instruction(22 downto 19);   -- next 4 bits = usually register number
    imm19  <= instruction(18 downto 0);    -- bottom 19 bits = immediate / offset

    -- Sign-extend imm19 to 32 bits.
    -- If bit 18 (the MSB of imm19) is '1', the number is negative, so we fill
    -- the upper 13 bits with '1' to preserve its value in 32-bit arithmetic.
    -- If bit 18 is '0', we fill with '0' (positive number, no change).
    -- Example: imm19 = 0x7FFD8 (= -40 in 19-bit two's complement)
    --          imm32 = 0xFFFFFFD8 (= -40 in 32-bit two's complement)
    imm32  <= (31 downto 19 => instruction(18)) & instruction(18 downto 0);

    -- One-hot decode: compare the opcode to each known value.
    -- Produces a single '1' flag for whichever instruction family matches.
    is_mov <= '1' when op = "00000" else '0';   -- opcode 0
    is_mvb <= '1' when op = "00001" else '0';   -- opcode 1
    is_alu <= '1' when unsigned(op) >= 2        -- opcodes 2,3,4,5,6
                   and unsigned(op) <= 6 else '0';
    is_not <= '1' when op = "00111" else '0';   -- opcode 7
    is_shf <= '1' when op = "01000" else '0';   -- opcode 8
    is_sar <= '1' when op = "01001" else '0';   -- opcode 9
    is_jmp <= '1' when op = "01010" else '0';   -- opcode 10
    is_jpr <= '1' when op = "01011" else '0';   -- opcode 11
    is_wfi <= '1' when op = "01100" else '0';   -- opcode 12
    is_eai <= '1' when op = "01101" else '0';   -- opcode 13
    is_dai <= '1' when op = "01110" else '0';   -- opcode 14
    is_rti <= '1' when op = "01111" else '0';   -- opcode 15

    -- For jumps, slice the condition code out of the mode field.
    -- Bit 26 is the "subroutine" flag (call vs plain jump).
    -- Bits 25..23 are the condition (always / zero / nonzero / negative / non-negative).
    jmp_sub  <= instruction(26);
    jmp_cond <= instruction(25 downto 23);

end architecture rtl;
