; echo.s — UART echo firmware for Titania / M56
;
; Reads bytes from UART and echoes them back.
; Proves the CPU is executing: a hardware loopback would not need instructions.
;
; UART at 0x400000:
;   read:  bit 9 = TX busy, bit 8 = RX valid, bits 7:0 = received byte
;   write: bits 7:0 = byte to transmit

_start:
    mov-h  #0x200, R4       ; R4 = 0x400000  (0x200 << 13 = 0x400000)

wait_rx:
    mov    [R4], R0         ; R0 = UART status word
    mov    R0, R1           ; R1 = copy — and destroys the register it operates on
    and    R1, #0x100       ; isolate bit 8: RX valid?
    jpr.z  R1, wait_rx      ; not ready → keep waiting

    and    R0, #0xFF        ; R0 = received byte (from the earlier read)

wait_tx:
    mov    [R4], R1         ; R1 = UART status
    and    R1, #0x200       ; isolate bit 9: TX busy?
    jpr.nz R1, wait_tx      ; busy → keep waiting

    mov    R0, [R4]         ; transmit byte
    jpr    wait_rx          ; loop forever
