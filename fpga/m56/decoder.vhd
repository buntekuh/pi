-- decoder.vhd — M56 instruction decoder (purely combinational, no clock)
--
-- Fixed field layout for every instruction:
--
--   31..27  opcode  (5 bits)
--   26..23  mode    (4 bits)  — addressing mode, or cond for jmp/jpr
--   22..19  reg     (4 bits)  — Rsrc / Rdst / Rcmp depending on instruction
--   18..0   imm19   (19 bits) — immediate, offset, or sub-fields
--
-- For jmp / jpr:
--   26      jmp_sub  — 1 = push return address before jumping (subroutine call)
--   25..23  jmp_cond — condition code (000=al, 001=z, 010=nz, 011=n, 100=nn)
--   22..19  reg      — Rcmp (compare register); ignored when cond = al

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity M56_Decoder is
    port (
        instr    : in  std_logic_vector(31 downto 0);

        -- Raw fields
        opcode   : out std_logic_vector(4 downto 0);
        mode     : out std_logic_vector(3 downto 0);
        reg      : out std_logic_vector(3 downto 0);
        imm19    : out std_logic_vector(18 downto 0);
        imm32    : out std_logic_vector(31 downto 0);  -- imm19 sign-extended

        -- One-hot opcode signals
        is_mov   : out std_logic;   -- opcode  0
        is_mvb   : out std_logic;   -- opcode  1
        is_alu   : out std_logic;   -- opcodes 2..6  (add sub and orr xor)
        is_not   : out std_logic;   -- opcode  7
        is_shf   : out std_logic;   -- opcode  8
        is_sar   : out std_logic;   -- opcode  9
        is_jmp   : out std_logic;   -- opcode 10  absolute jump
        is_jpr   : out std_logic;   -- opcode 11  relative jump
        is_wfi   : out std_logic;   -- opcode 12
        is_eai   : out std_logic;   -- opcode 13
        is_dai   : out std_logic;   -- opcode 14

        -- Jump sub-fields (valid when is_jmp = '1' or is_jpr = '1')
        jmp_sub  : out std_logic;                       -- subroutine flag
        jmp_cond : out std_logic_vector(2 downto 0)     -- condition code
    );
end entity M56_Decoder;

architecture rtl of M56_Decoder is
    signal op : std_logic_vector(4 downto 0);
begin

    -- Field extraction
    op     <= instr(31 downto 27);
    opcode <= op;
    mode   <= instr(26 downto 23);
    reg    <= instr(22 downto 19);
    imm19  <= instr(18 downto 0);
    imm32  <= (31 downto 19 => instr(18)) & instr(18 downto 0);

    -- One-hot opcode decode
    is_mov <= '1' when op = "00000" else '0';
    is_mvb <= '1' when op = "00001" else '0';
    is_alu <= '1' when unsigned(op) >= 2 and unsigned(op) <= 6 else '0';
    is_not <= '1' when op = "00111" else '0';
    is_shf <= '1' when op = "01000" else '0';
    is_sar <= '1' when op = "01001" else '0';
    is_jmp <= '1' when op = "01010" else '0';
    is_jpr <= '1' when op = "01011" else '0';
    is_wfi <= '1' when op = "01100" else '0';
    is_eai <= '1' when op = "01101" else '0';
    is_dai <= '1' when op = "01110" else '0';

    -- Jump sub-fields
    jmp_sub  <= instr(26);           -- cond bit 3
    jmp_cond <= instr(25 downto 23); -- cond bits 2:0

end architecture rtl;
