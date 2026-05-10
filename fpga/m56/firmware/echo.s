; echo.s — UART echo with BTN1 interrupt buffer replay
;
; Normal operation: reads bytes from the UART, echoes each byte immediately,
; and appends it to a RAM buffer (one byte per 32-bit word).
;
; BTN1 press: an interrupt fires.  The handler replays the entire buffer back
; to the UART, proving that the interrupt fired, the handler ran correctly,
; and that normal operation resumes on return.
;
; BTN1 is level-sensitive.  Each handler invocation replays the buffer once;
; release the button to stop.
;
; ─── Memory layout ───────────────────────────────────────────────────────────
;
;   0x000000   reset vector   jpr main — skip past the interrupt vector area
;   0x000010   handler        interrupt vector (CPU jumps here on any IRQ)
;   0x000080   main           handler is exactly 28 instructions (0x70 bytes)
;   0x000100   buffer         one byte stored per 32-bit word
;
; ─── Registers (main) ────────────────────────────────────────────────────────
;
;   R4   UART address constant  (0x400000)
;   R5   buffer base constant   (0x000100)
;   R6   buffer write pointer   (advances by 4 per byte stored)
;   R7   byte count in buffer
;
; ─── Registers (handler) ─────────────────────────────────────────────────────
;
;   R0   read pointer (initialised from R5)           saved / restored
;   R1   bytes remaining (initialised from R7)        saved / restored
;   R2   UART address   (0x400000)                    saved / restored
;   R3   scratch — UART status word, buffer word      not saved (main never uses R3)

; ── Reset vector (0x000000) ─────────────────────────────────────────────────
        jpr     main
        nop                         ; } three reserved slots:
        nop                         ; } must not execute, exist only to
        nop                         ; } pad to the interrupt vector at 0x000010

; ── Interrupt handler (0x000010) ────────────────────────────────────────────
; On entry: return PC is on top of the stack (pushed by hardware),
;           R13 = irq_status (bit 1 = BTN1), interrupts are disabled.
handler:
        psh     R0
        psh     R1
        psh     R2

        mov     R5, R0              ; R0 = read pointer = buffer base
        mov     R7, R1              ; R1 = bytes remaining
        mov-h   #0x200, R2          ; R2 = 0x400000 (UART address)
        jpr.z   R1, irq_done        ; buffer empty — nothing to replay

irq_tx:
        mov     [R2], R3            ; R3 = UART status word
        and     R3, #0x200          ; bit 9: TX busy?
        jpr.nz  R3, irq_tx          ; busy — spin

        mov     [R0], R3            ; R3 = 32-bit word from buffer (byte in bits 7..0)
        and     R3, #0xFF           ; strip upper 24 bits
        mov     R3, [R2]            ; transmit the byte
        add     R0, #4              ; advance read pointer by one word
        sub     R1, #1              ; one fewer byte to replay
        jpr.nz  R1, irq_tx          ; loop until buffer is drained

irq_done:
        pop     R2
        pop     R1
        pop     R0
        pop     R13                 ; return PC pushed by CPU on interrupt entry
        rti                         ; re-enable interrupts and jump to R13

; ── Main program (0x000080) ─────────────────────────────────────────────────
main:
        mov-h   #0x200, R4          ; R4 = 0x400000 (UART address)
        clr     R5
        orr     R5, #0x100          ; R5 = 0x000100 (buffer base)
        mov     R5, R6              ; R6 = write pointer = buffer base
        clr     R7                  ; R7 = 0 (buffer empty)
        eai                         ; enable interrupts — BTN1 can now fire

wait_rx:
        mov     [R4], R0            ; R0 = UART status word
        mov     R0, R1              ; R1 = copy for bit tests
        and     R1, #0x100          ; bit 8: RX valid?
        jpr.z   R1, wait_rx         ; not yet — spin

        and     R0, #0xFF           ; R0 = received byte (strip status bits)

wait_tx:
        mov     [R4], R1            ; R1 = UART status
        and     R1, #0x200          ; bit 9: TX busy?
        jpr.nz  R1, wait_tx         ; busy — spin

        mov     R0, [R4]            ; echo: write received byte to UART
        mov     R0, [R6]            ; store byte to buffer at write pointer
        add     R6, #4              ; advance write pointer
        inc     R7                  ; one more byte in buffer
        jpr     wait_rx             ; loop forever
