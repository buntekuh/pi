-- interrupt.vhd — M56 interrupt controller
--
-- Collects interrupt requests from peripherals and presents them to the CPU
-- as a pending signal and a status word.
--
-- ─── Single-priority interrupts ────────────────────────────────────────────
--
-- The M56 uses the simplest possible interrupt model: one priority level.
-- Any peripheral can raise a request. If the CPU has interrupts enabled
-- (set by the eai instruction), it will respond at the start of the next
-- EXEC cycle. There is no priority ranking between sources — they are equal.
--
-- ─── How an interrupt happens ──────────────────────────────────────────────
--
--   1. A peripheral (e.g. the UART) asserts its interrupt line.
--   2. The controller sets interrupt_pending = '1'.
--   3. At the start of the next EXEC cycle, the CPU notices interrupt_pending.
--   4. Instead of executing the decoded instruction, the CPU:
--        a. Pushes the return address (PC) onto the stack.
--        b. Writes irq_status to R13 — handler knows immediately which
--           source(s) fired without reading any extra register.
--        c. Disables further interrupts so the handler is not interrupted again.
--        d. Jumps to the interrupt vector at 0x00000010.
--   5. The handler reads R13 to dispatch per source, clears each source
--      (e.g. reads the UART byte so uart_rx_valid drops), then returns via rti.
--
-- ─── Edge detection ────────────────────────────────────────────────────────
--
-- BTN1 is edge-triggered: the interrupt fires once on the rising edge and
-- is held pending until the CPU acknowledges it (interrupts_enabled drops).
-- This prevents level-sensitive re-entry: without edge detection a held
-- button would re-fire the interrupt on every EXEC cycle after the handler
-- returned.
--
-- ─── irq_status bit layout ──────────────────────────────────────────────────
--
--   bit 0 = uart_rx_valid   (UART received a byte)
--   bit 1 = btn1            (button 1 rising edge)
--
-- ─── Adding more interrupt sources ─────────────────────────────────────────
--
--   Add a new input to the port list, OR it into interrupt_pending, and
--   assign it to the next free bit of irq_status.

library IEEE;
use IEEE.STD_LOGIC_1164.ALL;

entity interrupt_controller is
    port (
        clk                : in  STD_LOGIC;

        -- CPU feedback: '0' while the CPU is handling an interrupt.
        -- Used to clear the latch once the CPU has acknowledged.
        interrupts_enabled : in  STD_LOGIC;

        -- Interrupt sources.
        uart_rx_valid      : in  STD_LOGIC;   -- UART received a byte
        btn1               : in  STD_LOGIC;   -- second button

        -- To the CPU.
        interrupt_pending  : out STD_LOGIC;
        irq_status         : out STD_LOGIC_VECTOR(31 downto 0)
    );
end entity interrupt_controller;

architecture rtl of interrupt_controller is
    signal btn1_prev  : STD_LOGIC := '0';
    signal btn1_latch : STD_LOGIC := '0';
begin

    process(clk)
    begin
        if rising_edge(clk) then
            btn1_prev <= btn1;
            if interrupts_enabled = '0' then
                -- CPU is taking (or inside) an interrupt: clear the latch.
                btn1_latch <= '0';
            elsif btn1 = '1' and btn1_prev = '0' then
                -- Rising edge while interrupts are enabled: set the latch.
                btn1_latch <= '1';
            end if;
        end if;
    end process;

    interrupt_pending <= btn1_latch;

    -- irq_status reflects the live source levels so the handler can inspect
    -- which source(s) contributed even after the latch is cleared.
    irq_status <= (0 => uart_rx_valid, 1 => btn1, others => '0');

end architecture rtl;
