# echo.s — UART echo firmware for Titania / FemtoRV32
#
# Reads bytes from UART and echoes them back.
# Also adds 1 to letters (A→B, a→b) to prove the CPU is running,
# not just a hardware loopback.
#
# UART register at 0x400000:
#   read:  bit 9 = TX busy, bit 8 = RX valid, bits 7:0 = received byte
#   write: bits 7:0 = byte to transmit
#
# Build: make  (see Makefile)

.section .text
.global _start

_start:
    lui  t0, 0x400          # t0 = 0x400000 (UART address)

wait_rx:
    lw   t1, 0(t0)          # read UART — also pulses rd, clearing valid
    andi t2, t1, 0x100      # bit 8: RX valid?
    beq  t2, zero, wait_rx  # no → keep waiting

    andi t1, t1, 0xFF       # extract received byte from this read

wait_tx:
    lw   t2, 0(t0)          # read UART status
    andi t3, t2, 0x200      # bit 9: TX busy?
    bne  t3, zero, wait_tx  # yes → wait

    sw   t1, 0(t0)          # transmit byte
    j    wait_rx
