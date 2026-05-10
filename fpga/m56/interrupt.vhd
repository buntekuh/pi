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
-- ─── Memory layout convention ──────────────────────────────────────────────
--
--   0x000000:  jmp main        ; first instruction — skip past the handler
--   0x000004:  (reserved)      ; three spare instruction slots
--   0x000008:  (reserved)
--   0x00000C:  (reserved)
--   0x000010:  [handler]       ; interrupt vector — CPU jumps here on interrupt
--              push R0         ; save scratch registers
--              push R1
--              push R2
--              push R13        ; save irq_status before subroutine calls clobber it
--              ...             ; dispatch on R13 bits, service sources
--              pop  R13        ; restore irq_status (rti will overwrite R13 anyway)
--              pop  R2
--              pop  R1
--              pop  R0
--              pop  R13        ; load return address from stack into R13
--              rti             ; enable interrupts and jump to R13
--   main:
--              eai             ; enable interrupts for the first time
--              ...             ; normal program
--
-- ─── irq_status bit layout ──────────────────────────────────────────────────
--
--   bit 0 = uart_rx_valid   (UART received a byte)
--   bit 1 = (next source)
--   ...
--
-- ─── Adding more interrupt sources ─────────────────────────────────────────
--
--   Add a new input to the port list, OR it into interrupt_pending, and
--   assign it to the next free bit of irq_status.

library IEEE;
use IEEE.STD_LOGIC_1164.ALL;

entity interrupt_controller is
    port (
        -- Interrupt sources.
        -- Each line is '1' while the peripheral is requesting attention.
        uart_rx_valid    : in  STD_LOGIC;   -- UART received a byte (not yet used as interrupt source)
        btn1             : in  STD_LOGIC;   -- second button — level high while pressed

        -- To the CPU.
        interrupt_pending : out STD_LOGIC;                      -- '1' = at least one source is requesting
        irq_status        : out STD_LOGIC_VECTOR(31 downto 0)  -- one bit per source; written to R13 on entry
    );
end entity interrupt_controller;

architecture rtl of interrupt_controller is
begin

    -- btn1 fires interrupts; uart_rx_valid is tracked in the status word but does
    -- not yet trigger interrupts — the echo firmware still polls the UART directly.
    -- When UART becomes interrupt-driven, add:  interrupt_pending <= btn1 or uart_rx_valid;
    interrupt_pending <= btn1;

    -- One bit per source.  The CPU writes this to R13 on interrupt entry
    -- so the handler can dispatch without any extra memory reads.
    --   bit 0 = uart_rx_valid
    --   bit 1 = btn1
    irq_status <= (0 => uart_rx_valid, 1 => btn1, others => '0');

end architecture rtl;
