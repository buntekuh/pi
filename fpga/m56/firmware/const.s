; const.s — Titania M56: system-wide constants
;
; Included first in every build so all subsequent files can use these names.
; No words are emitted — .equ definitions are assembler-only symbols.

; ── Memory map ───────────────────────────────────────────────────────────────
.equ sram_base,     0x040000    ; base of on-board SRAM (IS61WV5128BLL, 512 KB)
.equ sram_top,      0x0BFFFC    ; top of SRAM — initial stack pointer
.equ uart_reg,      0x400000    ; UART status/data register
.equ spi_data,      0x800000    ; SPI shift register (write=start, read=busy+byte)
.equ spi_cs,        0x800004    ; SPI chip-select register (bit 0: 0=assert, 1=deassert)
.equ spi_div,       0x800008    ; SPI clock divider (SCK = clk / (2*(N+1)))

; ── UART bit masks ───────────────────────────────────────────────────────────
.equ uart_tx_busy,  0x200       ; bit 9 of UART status word
.equ uart_rx_valid, 0x100       ; bit 8 of UART status word

; ── IRQ status bits ──────────────────────────────────────────────────────────
.equ irq_rx,        0x1         ; bit 0: UART RX byte ready
.equ irq_btn1,      0x2         ; bit 1: BTN1 pressed
