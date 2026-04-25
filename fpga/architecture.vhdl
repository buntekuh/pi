library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;

entity M56_CPU is
    Port (
        clk : in STD_LOGIC;
        rst : in STD_LOGIC;
        interrupt : in STD_LOGIC
    );
end M56_CPU;

architecture Behavioral of M56_CPU is

    -- Define registers, memory map, and instruction fields
    constant REG_SIZE : integer := 32;
    type reg_file_type is array(0 to 15) of std_logic_vector(REG_SIZE - 1 downto 0);

    signal reg_file : reg_file_type := (others => (others => '0'));
    signal PC, nextPC : unsigned(31 downto 0);
    signal SP, nextSP : unsigned(31 downto 0);
    
    -- FLAGS register
    type flags_type is record
        Z, C, V, N, IE : std_logic;
    end record;

    signal FLAGS, nextFLAGS : flags_type;

    constant RESET_VECTOR : unsigned(31 downto 0) := x"00000004";
    constant INT_VECTOR : unsigned(31 downto 0) := x"00000010";

    -- Instruction fields
    signal opcode, mode, reg : std_logic_vector(3 downto 0);
    signal operand : std_logic_vector(18 downto 0);

    type state_type is (FETCH, DECODE, EXECUTE, INTERRUPT);
    signal state : state_type := FETCH;

begin

    -- Process to handle the CPU pipeline
    process(clk, rst)
    begin
        if rst = '1' then
            -- Initialize registers, PC, SP, FLAGS, etc.
            reg_file <= (others => (others => '0'));
            nextPC <= RESET_VECTOR;
            nextSP <= x"0007FFFC";
            state <= FETCH;
            
            FLAGS.Z <= '0';
            FLAGS.C <= '0';
            FLAGS.V <= '0';
            FLAGS.N <= '0';
            FLAGS.IE <= '1';

        elsif rising_edge(clk) then
            case state is
                when FETCH =>
                    -- Fetch instruction from memory using PC
                    -- Update nextPC here
                    state <= DECODE;
                
                when DECODE =>
                    -- Decode opcode, mode, register, operand fields
                    -- Set control signals based on decoded instruction
                    state <= EXECUTE;

                when EXECUTE =>
                    -- Execute the instruction
                    -- Update registers, memory, etc. based on the instruction
                    if interrupt = '1' and FLAGS.IE = '1' then
                        state <= INTERRUPT;
                    else
                        state <= FETCH;  -- Go back to fetch next instruction
                    end if;

                when INTERRUPT =>
                    -- Push current PC onto stack
                    -- Disable interrupts (clear IE)
                    -- Jump to interrupt vector
                    FLAGS.IE <= '0';
                    reg_file(14) <= std_logic_vector(nextSP);
                    state <= FETCH;
            end case;
        end if;
    end process;

end Behavioral;
