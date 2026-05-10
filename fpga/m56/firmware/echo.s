; echo.s — UART echo with BTN1 interrupt buffer replay
;
; Normal operation: reads bytes from the UART, echoes them immediately,
; and stores each byte into a RAM buffer.
;
; BTN1 press: an interrupt fires.  The handler replays the entire buffer
; back to the UART a second time, proving:
;   (a) the interrupt fired and the handler ran
;   (b) the handler returned correctly and normal operation resumed
;
; BTN1 is level-sensitive: the interrupt fires on every EXEC cycle while
; the button is held.  Each handler run replays the buffer once and returns.
; Release the button to stop.
;
; ─── Memory layout ────────────────────────────────────────────────────────
;
;   0x000000   jpr main          reset entry — skip past the handler
;   0x000004   (reserved)        three spare instruction slots before
;   0x000008   (reserved)        the interrupt vector
;   0x00000C   (reserved)
;   0x000010   handler           interrupt vector — CPU jumps here on interrupt
;   0x000080   main              normal program
;   0x000100   buffer            one byte stored per 32-bit word
;
; ─── Registers (main loop) ────────────────────────────────────────────────
;
;   R4   UART address (0x400000) — constant
;   R5   buffer base address (0x000100) — constant
;   R6   buffer write pointer — starts at R5, advances by 4 per byte stored
;   R7   byte count in buffer
;
; ─── Registers (handler) ──────────────────────────────────────────────────
;
;   R0, R1, R2 are saved on the stack and used freely.
;   R13 is repurposed as the UART address during the handler body;
;       it is loaded with the return address via pop at the end, then rti jumps to it.

; ── Reset entry (0x000000) ───────────────────────────────────────────────
        jpr     main

; Three reserved instruction slots (0x000004 – 0x00000C).
; Must not be executed; exist only to pad to the interrupt vector at 0x000010.
        add     R0, #0
        add     R0, #0
        add     R0, #0

; ── Interrupt handler (0x000010) ─────────────────────────────────────────
; On entry: PC has been pushed to the stack by the CPU,
;           R13 = irq_status (bit 1 set = BTN1 fired),
;           interrupts are disabled.
handler:
        sub     R14, #4
        mov     R0, [R14]           ; push R0
        sub     R14, #4
        mov     R1, [R14]           ; push R1
        sub     R14, #4
        mov     R2, [R14]           ; push R2

        ; R5 = buffer base (set in main, not modified here)
        ; R7 = byte count  (set in main, not modified here)
        mov-h   #0x200, R13         ; R13 = 0x400000 — UART address, used throughout body
        mov     R5, R0              ; R0 = read pointer, starts at buffer base
        mov     R7, R1              ; R1 = bytes remaining
        jpr.z   R1, irq_done        ; nothing in buffer, skip replay

irq_tx:
        ; wait for UART transmitter to be free, then send next byte
        mov     [R13], R2           ; R2 = UART status word
        and     R2, #0x200          ; isolate bit 9: TX busy
        jpr.nz  R2, irq_tx          ; busy — retry (also serves as outer loop head)

         mov     R7, [R13]
;        mov     [R0], R2            ; R2 = 32-bit word from buffer (byte in bits 7..0)
;        and     R2, #0xFF           ; keep only the byte
;        mov     R2, [R13]           ; transmit: write R2 to UART address

;        add     R0, #4              ; advance read pointer by one word
;        sub     R1, #1              ; one fewer byte to send
;        jpr.nz  R1, irq_tx          ; more bytes remain — loop back to TX wait

irq_done:
        ; restore caller's registers in reverse order
        mov     [R14], R2
        add     R14, #4             ; pop R2
        mov     [R14], R1
        add     R14, #4             ; pop R1
        mov     [R14], R0
        add     R14, #4             ; pop R0

        ; return: load the PC that was pushed by hardware into R13, then rti
        mov     [R14], R13          ; R13 = return address (pushed by CPU on interrupt entry)
        add     R14, #4             ; SP now restored to its pre-interrupt value
        rti                         ; enable interrupts and jump to R13

; ── Main program (0x000080) ──────────────────────────────────────────────
main:
        mov-h   #0x200, R4          ; R4 = 0x400000  (UART address)
        and     R5, #0              ; R5 = 0
        orr     R5, #0x100          ; R5 = 0x000100  (buffer base)
        mov     R5, R6              ; R6 = write pointer = buffer base
        and     R7, #0              ; R7 = 0          (buffer empty)
        eai                         ; enable interrupts — BTN1 can now fire

wait_rx:
        mov     [R4], R0            ; R0 = UART status word
        mov     R0, R1              ; R1 = copy for bit test
        and     R1, #0x100          ; bit 8: RX valid?
        jpr.z   R1, wait_rx         ; not ready — keep waiting

        and     R0, #0xFF           ; R0 = received byte

wait_tx:
        mov     [R4], R1            ; R1 = UART status
        and     R1, #0x200          ; bit 9: TX busy?
        jpr.nz  R1, wait_tx         ; busy — keep waiting

        mov     R0, [R4]            ; echo: transmit the received byte
        mov     R0, [R6]            ; store byte to buffer at write pointer
        add     R6, #4              ; advance write pointer
        add     R7, #1              ; one more byte in buffer
        jpr     wait_rx             ; loop forever
