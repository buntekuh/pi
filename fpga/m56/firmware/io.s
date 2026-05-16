; io.s — Titania M56: interrupt-driven UART I/O
;
; Provides:
;   putc  R0        — transmit single byte, blocks on TX busy
;   puts  R0        — transmit null-terminated string (one char per word)
;   getc  → R0      — block until RX buffer has a byte, return it
;
; Interrupt handler dispatches on irq_status (R13 on entry):
;   bit 0 = uart_rx_valid  → read byte into rxbuf
;   bit 1 = btn1           → ignored for now
;
; ─── Memory layout ───────────────────────────────────────────────────────────
;
;   0x000000   reset vector   bar main
;   0x000010   handler        interrupt vector
;   (handler, putc, puts, getc, main follow in order)
;   (rxbuf_wptr, rxbuf_rptr, rxbuf[64], greeting at end of binary)
;
; ─── Stack ───────────────────────────────────────────────────────────────────
;
;   R14 (SP) is initialised to the top of BRAM by the CPU at reset.
;   The stack grows downward; code and data grow upward from 0x000000.
;   They meet in the middle as both expand — there is no hardware guard and
;   no overflow detection.  A stack that grows into data or code corrupts
;   silently.
;
; ─── Calling convention ──────────────────────────────────────────────────────
;
;   R0–R2   scratch / arguments  (caller-saved, callee may overwrite freely)
;   R3–R12  callee-saved         (push on entry, pop before return if used)
;   R13     interrupt status     (written by hardware on interrupt entry)
;   R14     SP (stack pointer, grows downward)
;   R15     PC (program counter)

; ── Reset vector (0x000000) ─────────────────────────────────────────────────
        bar     main
        nop
        nop
        nop

; ── Interrupt handler (0x000010) ────────────────────────────────────────────
; On entry: return PC on stack, R13 = irq_status, interrupts disabled.
handler:
        psh     R0
        psh     R1
        psh     R2

        ; UART RX? (irq_status bit 0)
        mov     R13, R0
        and     R0, #1
        bar.z   R0, irq_btn1

        ; Read byte from UART — also clears uart_rx_valid
        mov-h   #0x400, R1          ; R1 = 0x400000
        mov     [R1], R0            ; R0 = status word (bits 7:0 = byte)
        and     R0, #0xFF

        ; Store byte in receive buffer
        mov     #rxbuf_wptr, R1
        mov     [R1], R2            ; R2 = write pointer
        mvb     R0, [R2]            ; write byte to buffer
        add     R2, #4
        mov     R2, [R1]            ; save updated write pointer

irq_btn1:
        ; BTN1 (irq_status bit 1) — reserved for future use

irq_done:
        pop     R2
        pop     R1
        pop     R0
        pop     R13                 ; return PC (pushed by CPU on interrupt entry)
        rti

; ── putc ─────────────────────────────────────────────────────────────────────
; Transmit byte in R0. Blocks until UART TX is ready.
; Clobbers R0–R2.
putc:
        mov-h   #0x400, R1          ; R1 = 0x400000 (UART)
putc_wait:
        mov     [R1], R2
        and     R2, #0x200          ; bit 9: TX busy
        bar.nz  R2, putc_wait
        mvb     R0, [R1]
        ret

; ── puts ─────────────────────────────────────────────────────────────────────
; Transmit null-terminated string. R0 = base address (one char per word).
; Clobbers R0–R2.
puts:
        mov-h   #0x400, R1
puts_loop:
        mov     [R1], R2            ; wait for TX ready
        and     R2, #0x200
        bar.nz  R2, puts_loop
        mvb     [R0], R2            ; read next char
        bar.z   R2, puts_done       ; null terminator
        mvb     R2, [R1]            ; transmit
        add     R0, #4
        bar     puts_loop
puts_done:
        ret

; ── getc ─────────────────────────────────────────────────────────────────────
; Block until RX buffer has a byte. Returns byte in R0.
; Clobbers R0–R2.
getc:
        mov     #rxbuf_rptr, R2     ; R2 = &rxbuf_rptr (constant through loop)
getc_wait:
        mov     [R2], R0            ; R0 = read pointer
        mov     #rxbuf_wptr, R1
        mov     [R1], R1            ; R1 = write pointer
        sub     R1, R0              ; R1 = wptr - rptr (0 if empty)
        bar.nz  R1, getc_data
        wfi                         ; sleep until next interrupt adds to buffer
        bar     getc_wait
getc_data:
        mvb     [R0], R1            ; R1 = byte at read pointer
        add     R0, #4
        mov     R0, [R2]            ; save updated read pointer
        mov     R1, R0              ; return byte in R0
        ret

; ── main ─────────────────────────────────────────────────────────────────────
main:
        ; Initialise RX buffer pointers to buffer base address
        mov     #rxbuf, R0
        mov     #rxbuf_wptr, R1
        mov     R0, [R1]
        mov     #rxbuf_rptr, R1
        mov     R0, [R1]

        eai                         ; enable interrupts

        mov     #greeting, R0
        cal     puts

echo_loop:
        cal     getc                ; R0 = received byte
        cal     putc                ; echo it back
        bar     echo_loop

; ── Data ─────────────────────────────────────────────────────────────────────
rxbuf_wptr:
        .word   0
rxbuf_rptr:
        .word   0
rxbuf:
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
        .word   0
rxbuf_end:

greeting:
        .str    "Titania M56\r\n"
