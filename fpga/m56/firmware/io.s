; io.s — Titania M56: interrupt-driven UART I/O
;
; Provides:
;   putc  R0        — transmit single byte, blocks on TX busy
;   puts  R0        — transmit null-terminated string (one char per word)
;   getc  → R0      — block until RX buffer has a byte, return it
;
; Interrupt dispatch table (irq_table):
;   entry 0 = bit 0 handler (UART RX — reads byte into rxbuf)
;   entry 1 = bit 1 handler (BTN1 — irq_nop by default)
; Use register_irq_handler(source, fn) to install handlers at runtime.
;
; ─── Memory layout ───────────────────────────────────────────────────────────
;
;   0x000000   reset vector        bar main
;   0x000010   handler             interrupt dispatch stub
;   (irq_nop, irq_uart_rx, irq_table, register_irq_handler follow)
;   (putc, puts, puts_sram, getc, main follow)
;   (rxbuf_wptr, rxbuf_rptr, rxbuf[64], greeting at end of binary)
;
; ─── Stack ───────────────────────────────────────────────────────────────────
;
;   R14 (SP) is initialised to 0x0BFFFC (top of SRAM) by the CPU at reset.
;   The stack lives in SRAM and grows downward.  Code and data live in BRAM
;   growing upward from 0x000000.  There is no hardware guard between them.
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

; ── Interrupt dispatch stub (0x000010) ──────────────────────────────────────
; On entry: return PC on stack, R13 = irq_status, interrupts disabled.
; Tests irq_status bits from 0 upward (bit 0 = highest priority).
; Calls the registered handler as a subroutine, then returns from interrupt.
handler:
        psh     R0
        psh     R1
        psh     R2

        mov     R13, R0
        and     R0, #1
        bar.z   R0, irq_bit1
        mov     #irq_table, R1
        mov     [R1], R2
        ica     R2
        bar     irq_done

irq_bit1:
        mov     R13, R0
        and     R0, #2
        bar.z   R0, irq_done
        mov     #irq_table, R1
        add     R1, #4
        mov     [R1], R2
        ica     R2

irq_done:
        pop     R2
        pop     R1
        pop     R0
        pop     R13                 ; return PC (pushed by CPU on interrupt entry)
        ret.i

; ── irq_nop — default no-op handler ─────────────────────────────────────────
irq_nop:
        ret

; ── irq_uart_rx — UART RX handler ───────────────────────────────────────────
; Called as subroutine by dispatch stub. R0-R2 saved by stub.
irq_uart_rx:
        mov-h   #0x400, R1          ; R1 = 0x400000 (UART)
        mov     [R1], R0            ; R0 = status word (bits 7:0 = received byte)
        and     R0, #0xFF
        mov     #rxbuf_wptr, R1
        mov     [R1], R2            ; R2 = write pointer
        mov     R0, [R2]            ; write byte to buffer (word write: byte in bits 7:0, upper bits zero)
        add     R2, #4
        mov     R2, [R1]            ; save updated write pointer
        ret

; ── irq_table — interrupt dispatch table ─────────────────────────────────────
; One word per interrupt source bit. Write handler address to install.
; Use register_irq_handler to update at runtime.
irq_table:
        .word   irq_uart_rx         ; bit 0 = UART RX
        .word   irq_nop             ; bit 1 = BTN1 (unhandled)

; ── register_irq_handler ─────────────────────────────────────────────────────
; R0 = interrupt source number (0, 1, ...), R1 = handler address.
; Clobbers R0, R2.
register_irq_handler:
        shf     R0, #2              ; R0 = source * 4 (word offset)
        mov     #irq_table, R2
        add     R2, R0              ; R2 = &irq_table[source]
        mov     R1, [R2]
        ret

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
; Word reads avoid the mvb BRAM byte-read hardware bug.
; Clobbers R0–R2. Preserves R3.
puts:
        psh     R3
        mov-h   #0x400, R3          ; R3 = 0x400000 (UART)
puts_loop:
        mov     [R0], R2            ; word-read next char from BRAM
        and     R2, #0xFF
        bar.z   R2, puts_done       ; null terminator
puts_txwait:
        mov     [R3], R1
        and     R1, #0x200          ; bit 9 = TX busy
        bar.nz  R1, puts_txwait
        mvb     R2, [R3]            ; transmit byte (UART write, not BRAM read)
        add     R0, #4
        bar     puts_loop
puts_done:
        pop     R3
        ret

; ── puts_sram ────────────────────────────────────────────────────────────────
; Transmit null-terminated packed byte string from SRAM.
; R0 = byte address in SRAM. Reads one byte at a time via mvb.
; Clobbers R0–R2. Preserves R3.
puts_sram:
        psh     R3
        mov-h   #0x400, R3          ; R3 = 0x400000 (UART)
puts_sram_loop:
        mvb     [R0], R2            ; byte read from SRAM
        bar.z   R2, puts_sram_done  ; null terminator
puts_sram_txwait:
        mov     [R3], R1
        and     R1, #0x200          ; bit 9 = TX busy
        bar.nz  R1, puts_sram_txwait
        mvb     R2, [R3]            ; transmit byte
        add     R0, #1              ; next byte
        bar     puts_sram_loop
puts_sram_done:
        pop     R3
        ret

; ── print_hex_byte ───────────────────────────────────────────────────────────
; Print byte in R0 as two uppercase hex digits.
; Clobbers R0–R2. Uses R3, R4 internally (saves and restores them).
print_hex_byte:
        psh     R3
        psh     R4
        mov     R0, R4              ; R4 = original byte
        mov     R4, R3
        shr     R3, #4
        and     R3, #0xF            ; R3 = high nibble
        cal     print_nibble
        mov     R4, R3
        and     R3, #0xF            ; R3 = low nibble
        cal     print_nibble
        pop     R4
        pop     R3
        ret

; print_nibble — print nibble (0–15) in R3 as one hex char. Clobbers R0–R2.
print_nibble:
        mov     R3, R0
        sub     R0, #10
        bar.n   R0, pn_digit        ; nibble < 10 → '0'–'9'
        mov     R3, R0
        add     R0, #55             ; nibble ≥ 10: 'A'-'F'
        cal     putc
        ret
pn_digit:
        mov     R3, R0
        add     R0, #48             ; '0' + nibble
        cal     putc
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
        mov     [R0], R1            ; R1 = word at read pointer (byte in bits 7:0)
        and     R1, #0xFF           ; mask to byte
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

        ; SRAM test: write 0xABCD to 0x040000, read back, print S or F
        mov     #0xABCD, R0
        mov-h   #0x040, R1          ; R1 = 0x040000 (SRAM base)
        mov     R0, [R1]            ; write to SRAM
        mov     [R1], R2            ; read back
        sub     R2, R0
        bar.z   R2, sram_ok
        mov     #'F', R0
        cal     putc
        bar     sram_done
sram_ok:
        mov     #'S', R0
        cal     putc
sram_done:

        ; Packed-byte SRAM test: write "Sram ready.\r\n" byte-by-byte, read back via mvb
        mov-h   #0x040, R1          ; R1 = 0x040100 (byte string area, past word test)
        add     R1, #0x100
        mov     R1, R2              ; R2 = write pointer
        mov     #'r', R0
        mvb     R0, [R2]
        add     R2, #1
        mov     #'a', R0
        mvb     R0, [R2]
        add     R2, #1
        mov     #'m', R0
        mvb     R0, [R2]
        add     R2, #1
        mov     #' ', R0
        mvb     R0, [R2]
        add     R2, #1
        mov     #'r', R0
        mvb     R0, [R2]
        add     R2, #1
        mov     #'e', R0
        mvb     R0, [R2]
        add     R2, #1
        mov     #'a', R0
        mvb     R0, [R2]
        add     R2, #1
        mov     #'d', R0
        mvb     R0, [R2]
        add     R2, #1
        mov     #'y', R0
        mvb     R0, [R2]
        add     R2, #1
        mov     #'.', R0
        mvb     R0, [R2]
        add     R2, #1
        mov     #13, R0
        mvb     R0, [R2]
        add     R2, #1
        mov     #10, R0
        mvb     R0, [R2]
        add     R2, #1
        mov     #0, R0
        mvb     R0, [R2]
        mov     R1, R0              ; R0 = base of packed string
        cal     puts_sram

        mov     #greeting, R0
        cal     puts

        ; SD card test: init, read sector 0, hexdump first 16 bytes
        cal     sd_init
        bar.nz  R0, sd_fail
        mov     #'I', R0            ; init ok
        cal     putc
        ; sd_init switches to 6 MHz; drop back to 400 kHz for Pmod signal integrity
        mov-h   #0x800, R1
        add     R1, #8              ; SPI DIV register
        mov     #14, R2
        mov     R2, [R1]
        mov     #135, R0            ; sector 135 = FAT16 VBR (partition start)
        mov-h   #0x042, R1          ; destination: SRAM 0x042000
        cal     sd_read_sector
        bar.nz  R0, sd_fail
        ; hexdump 16 bytes
        psh     R3
        psh     R4
        mov-h   #0x042, R3          ; R3 = byte pointer into buffer
        mov     #16, R4
sd_hex_loop:
        mvb     [R3], R0
        cal     print_hex_byte
        mov     #' ', R0
        cal     putc
        add     R3, #1
        dec     R4
        bar.nz  R4, sd_hex_loop
        pop     R4
        pop     R3
        mov     #13, R0
        cal     putc
        mov     #10, R0
        cal     putc
        bar     sd_done
sd_fail:
        mov     #'E', R0
        cal     putc
sd_done:

        ; Math test: 300 * 400 / 500 % 7 = 2 (left-to-right evaluation)
        mov     #300, R0
        mov     #400, R1
        mul     R0, R1          ; R0 = 120000
        mov     #500, R1
        div     R0, R1          ; R0 = 240
        mov     #7, R1
        mod     R0, R1          ; R0 = 2
        add     R0, #'0'        ; ASCII digit
        cal     putc
        mov     #13, R0
        cal     putc
        mov     #10, R0
        cal     putc

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
        .str    "Titania M56 Peter Panther.\r\n"
