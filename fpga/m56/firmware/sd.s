; sd.s — SD card SPI driver for Titania M56
;
; SPI peripheral at 0x800000 (bit 23 = 1, needs mov-h to reach):
;   0x800000  DATA  write = send byte + start transfer
;                   read  = bit 8 (busy) | bits 7:0 (last received byte)
;   0x800004  CS#   bit 0: 0 = card selected, 1 = deselected
;   0x800008  DIV   N: SCK = 12 MHz / (2*(N+1)) — 14 = 400 kHz, 0 = 6 MHz
;
; ── Public interface ──────────────────────────────────────────────────────────
;
;   sd_init             → R0 = 0 (success), R0 = 1 (error)
;   sd_read_sector      R0 = sector number, R1 = destination word address
;                       → R0 = 0 (success), R0 = 1 (error)
;
; ── Global state ──────────────────────────────────────────────────────────────
;
;   sd_is_hc  1 = SDHC (block addressing), 0 = SDSC (byte addressing)
;   Set by sd_init; read by sd_read_sector.

; ── spi_byte ─────────────────────────────────────────────────────────────────
; Send byte in R0, return received byte in R0. Clobbers R1, R2.
spi_byte:
        mov-h   #0x800, R1          ; R1 = 0x800000
        mov     R0, [R1]            ; write DATA → start transfer
spi_byte_wait:
        mov     [R1], R2            ; read DATA: bit 8 = busy
        and     R2, #0x100
        bar.nz  R2, spi_byte_wait
        mov     [R1], R0
        and     R0, #0xFF           ; return received byte
        ret

; ── spi_cs_assert ────────────────────────────────────────────────────────────
; Drive CS# low (select card). Clobbers R1, R2.
spi_cs_assert:
        mov-h   #0x800, R1
        add     R1, #4              ; R1 = 0x800004 (CS#)
        mov     #0, R2
        mov     R2, [R1]
        ret

; ── spi_cs_deassert ──────────────────────────────────────────────────────────
; Drive CS# high (deselect card). Clobbers R1, R2.
spi_cs_deassert:
        mov-h   #0x800, R1
        add     R1, #4
        mov     #1, R2
        mov     R2, [R1]
        ret

; ── sd_wait_r1 ───────────────────────────────────────────────────────────────
; Clock up to 8 bytes; return first non-0xFF byte in R0 (response).
; Returns 0xFF if card never responds. Clobbers R1, R2.
sd_wait_r1:
        psh     R3
        mov     #8, R3
sd_wait_r1_lp:
        mov     #0xFF, R0
        cal     spi_byte
        mov     R0, R2
        sub     R2, #0xFF           ; 0 if still 0xFF
        bar.nz  R2, sd_wait_r1_done
        dec     R3
        bar.nz  R3, sd_wait_r1_lp
sd_wait_r1_done:
        pop     R3
        ret

; ── sd_send_cmd ──────────────────────────────────────────────────────────────
; Send a 6-byte SD SPI command and return the R1 response byte in R0.
; R3 = command index (0–63), R4 = 32-bit argument, R5 = CRC byte.
; Clobbers R0, R1, R2.
sd_send_cmd:
        ; byte 0: 0x40 | cmd
        mov     R3, R0
        orr     R0, #0x40
        cal     spi_byte
        ; byte 1: arg[31:24]
        mov     R4, R0
        shr     R0, #24
        and     R0, #0xFF
        cal     spi_byte
        ; byte 2: arg[23:16]
        mov     R4, R0
        shr     R0, #16
        and     R0, #0xFF
        cal     spi_byte
        ; byte 3: arg[15:8]
        mov     R4, R0
        shr     R0, #8
        and     R0, #0xFF
        cal     spi_byte
        ; byte 4: arg[7:0]
        mov     R4, R0
        and     R0, #0xFF
        cal     spi_byte
        ; byte 5: CRC
        mov     R5, R0
        cal     spi_byte
        ; read R1 response (card may clock 0xFF for up to 8 bytes first)
        cal     sd_wait_r1
        ret

; ── sd_init ──────────────────────────────────────────────────────────────────
; Initialise SD card in SPI mode.  Sets sd_is_hc.
; Returns R0 = 0 on success, R0 = 1 on error.
sd_init:
        psh     R3
        psh     R4
        psh     R5
        psh     R6
        psh     R7

        ; Slow clock: DIV = 14 → 400 kHz (SD spec: ≤ 400 kHz during init)
        mov-h   #0x800, R1
        add     R1, #8              ; 0x800008 (DIV)
        mov     #14, R2
        mov     R2, [R1]

        cal     spi_cs_deassert     ; CS# high during dummy clocks

        ; Send ≥ 74 dummy clocks (80 = 10 bytes of 0xFF) before CMD0
        mov     #10, R3
sd_dummy:
        mov     #0xFF, R0
        cal     spi_byte
        dec     R3
        bar.nz  R3, sd_dummy

        cal     spi_cs_assert

        ; CMD0 — GO_IDLE_STATE (CRC = 0x95)
        ; Expected R1 = 0x01 (card entered idle state)
        mov     #0, R3
        mov     #0, R4
        mov     #0x95, R5
        cal     sd_send_cmd         ; R0 = R1 response
        mov     R0, R6
        sub     R6, #1              ; 0 if R0 = 0x01
        bar.nz  R6, sd_init_fail

        ; CMD8 — SEND_IF_COND (arg = 0x000001AA, CRC = 0x87)
        ; Identifies SDv2.  SDv1 cards return 0x05 (illegal command).
        ; We support both; HCS flag in ACMD41 is harmless for SDv1.
        mov     #8, R3
        mov     #0x1AA, R4
        mov     #0x87, R5
        cal     sd_send_cmd         ; R0 = R1 (0x01=SDv2, 0x05=SDv1, either OK)
        ; Discard 4 trailing R7 bytes
        mov     #0xFF, R0
        cal     spi_byte
        mov     #0xFF, R0
        cal     spi_byte
        mov     #0xFF, R0
        cal     spi_byte
        mov     #0xFF, R0
        cal     spi_byte

        ; ACMD41 loop — repeat CMD55 + ACMD41 until card reports ready (R1 = 0x00)
        ; Timeout counter: at 400 kHz each iteration is ~280 µs; 2000 = ~560 ms
        mov     #2000, R6
sd_acmd41:
        ; CMD55 — APP_CMD (precedes any ACMD)
        mov     #55, R3
        mov     #0, R4
        mov     #1, R5
        cal     sd_send_cmd
        ; ACMD41 — SD_SEND_OP_COND, HCS=1 (supports SDHC)
        mov     #41, R3
        mov-h   #0x40000, R4        ; 0x40000 << 12 = 0x40000000 (HCS bit)
        mov     #1, R5
        cal     sd_send_cmd         ; R0 = R1
        bar.z   R0, sd_acmd41_done  ; 0x00 → card ready
        dec     R6
        bar.nz  R6, sd_acmd41
        bar     sd_init_fail        ; timed out

sd_acmd41_done:
        ; CMD58 — READ_OCR: inspect CCS bit to distinguish SDHC from SDSC
        mov     #58, R3
        mov     #0, R4
        mov     #1, R5
        cal     sd_send_cmd         ; R0 = R1 (expect 0x00)
        ; OCR byte 0 (bits 31:24): bit 6 = CCS
        mov     #0xFF, R0
        cal     spi_byte
        mov     R0, R7              ; save OCR[31:24]
        ; Discard remaining 3 OCR bytes
        mov     #0xFF, R0
        cal     spi_byte
        mov     #0xFF, R0
        cal     spi_byte
        mov     #0xFF, R0
        cal     spi_byte

        ; Write sd_is_hc flag
        and     R7, #0x40           ; isolate CCS
        mov     #sd_is_hc, R1
        bar.z   R7, sd_sdsc
        mov     #1, R0
        mov     R0, [R1]            ; SDHC: block addressing
        bar     sd_init_fast
sd_sdsc:
        mov     #0, R0
        mov     R0, [R1]            ; SDSC: byte addressing

sd_init_fast:
        ; Switch to fast clock: DIV = 0 → 6 MHz
        mov-h   #0x800, R1
        add     R1, #8
        mov     #0, R2
        mov     R2, [R1]

        cal     spi_cs_deassert
        mov     #0, R0              ; success
        bar     sd_init_ret

sd_init_fail:
        cal     spi_cs_deassert
        mov     #1, R0              ; error

sd_init_ret:
        pop     R7
        pop     R6
        pop     R5
        pop     R4
        pop     R3
        ret

; ── sd_read_sector ────────────────────────────────────────────────────────────
; Read one 512-byte sector into a buffer (one byte per word, word-aligned).
; R0 = sector number, R1 = destination base address.
; Returns R0 = 0 on success, R0 = 1 on error.
sd_read_sector:
        psh     R3
        psh     R4
        psh     R5
        psh     R6
        psh     R7

        mov     R0, R6              ; R6 = sector number
        mov     R1, R7              ; R7 = destination address

        ; Build CMD17 argument: SDHC uses block number, SDSC uses byte address
        mov     #sd_is_hc, R1
        mov     [R1], R0
        bar.nz  R0, sd_rd_hc
        mov     R6, R4
        shl     R4, #9              ; SDSC: byte address = sector × 512
        bar     sd_rd_cmd
sd_rd_hc:
        mov     R6, R4              ; SDHC: argument is the sector number directly

sd_rd_cmd:
        cal     spi_cs_assert

        ; CMD17 — READ_SINGLE_BLOCK
        mov     #17, R3
        mov     #1, R5              ; dummy CRC
        cal     sd_send_cmd         ; R0 = R1 response
        bar.z   R0, sd_rd_token     ; 0x00 → command accepted
        bar     sd_rd_fail

sd_rd_token:
        ; Poll for data token 0xFE (card sends 0xFF while preparing data)
        mov     #0xFFFF, R6
sd_rd_token_lp:
        mov     #0xFF, R0
        cal     spi_byte
        mov     R0, R2
        sub     R2, #0xFE
        bar.z   R2, sd_rd_data      ; got 0xFE → data follows
        dec     R6
        bar.nz  R6, sd_rd_token_lp
        bar     sd_rd_fail          ; timed out waiting for token

sd_rd_data:
        ; Read 512 bytes, storing one byte per word at destination
        mov     #512, R6
sd_rd_loop:
        mov     #0xFF, R0
        cal     spi_byte
        mvb     R0, [R7]            ; store byte to SRAM (true byte write)
        add     R7, #1              ; next byte address
        dec     R6
        bar.nz  R6, sd_rd_loop

        ; Discard 2 CRC bytes
        mov     #0xFF, R0
        cal     spi_byte
        mov     #0xFF, R0
        cal     spi_byte

        cal     spi_cs_deassert
        mov     #0, R0              ; success
        bar     sd_rd_ret

sd_rd_fail:
        cal     spi_cs_deassert
        mov     #1, R0              ; error

sd_rd_ret:
        pop     R7
        pop     R6
        pop     R5
        pop     R4
        pop     R3
        ret

; ── Data ─────────────────────────────────────────────────────────────────────
sd_is_hc:
        .word   0                   ; 1 = SDHC (block addr), 0 = SDSC (byte addr)
