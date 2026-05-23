; tests.s — Titania M56: comprehensive hardware test suite
;
; Called as a subroutine from main.s (e.g. on button press).
;
; Output format per test:
;   <12-char label> exp:<8-hex> got:<8-hex> ok\r\n
;                                            FAIL\r\n
;
; check entry contract:
;   R3 = pointer to .str label (12 chars space-padded + NUL)
;   R4 = expected value
;   R5 = actual value
;   Clobbers R0-R2. Preserves R3-R5.

; ── run_tests — run all tests and print summary, then return ─────────────────
run_tests:
        mov     #pass_count, R0
        mov     #0, R1
        mov     R1, [R0]
        mov     #fail_count, R0
        mov     R1, [R0]

        cal     test_sd
        cal     test_alu
        cal     test_shift
        cal     test_mov
        cal     test_branch
        cal     test_carry
        cal     test_stack
        cal     test_sram
        cal     test_math

        mov     #str_pass, R0
        cal     puts
        mov     #pass_count, R0
        mov     [R0], R0
        cal     print_decimal
        mov     #str_spacefail, R0
        cal     puts
        mov     #fail_count, R0
        mov     [R0], R0
        cal     print_decimal
        mov     #str_crlf, R0
        cal     puts

        ret

; ── check ────────────────────────────────────────────────────────────────────
; R3=label ptr, R4=expected, R5=actual. Clobbers R0-R2. Preserves R3-R7.
check:
        psh     R6
        psh     R7
        mov     R4, R6
        mov     R5, R7

        mov     R3, R0
        cal     puts

        mov     #str_exp, R0
        cal     puts
        mov     R6, R0
        cal     print_hex_word

        mov     #str_got, R0
        cal     puts
        mov     R7, R0
        cal     print_hex_word

        sub     R7, R6
        bar.nz  R7, check_fail
        mov     #str_ok, R0
        cal     puts
        mov     #pass_count, R0
        mov     [R0], R1
        add     R1, #1
        mov     R1, [R0]
        bar     check_ret
check_fail:
        mov     #str_fail_msg, R0
        cal     puts
        mov     #fail_count, R0
        mov     [R0], R1
        add     R1, #1
        mov     R1, [R0]
check_ret:
        pop     R7
        pop     R6
        ret

; ── print_decimal ─────────────────────────────────────────────────────────────
; Print R0 as unsigned decimal. Clobbers R0-R2. Preserves R3-R5.
print_decimal:
        psh     R3
        psh     R4
        psh     R5
        mov     R0, R3
        mov     #pd_buf_end, R4
        mov     R4, R5

pd_loop:
        mov     R3, R0
        mov     #10, R1
        mod     R0, R1
        add     R0, #'0'
        sub     R5, #4
        mov     R0, [R5]
        mov     R3, R0
        mov     #10, R1
        div     R0, R1
        mov     R0, R3
        bar.nz  R3, pd_loop

pd_print:
        mov     R5, R2
        sub     R2, R4
        bar.n   R2, pd_do
        bar     pd_done
pd_do:
        mov     [R5], R0
        and     R0, #0xFF
        cal     putc
        add     R5, #4
        bar     pd_print
pd_done:
        pop     R5
        pop     R4
        pop     R3
        ret

; ── test_sd ──────────────────────────────────────────────────────────────────
test_sd:
        psh     R3
        psh     R4
        psh     R5

        cal     sd_init
        mov     R0, R5
        mov     #lbl_sd_init, R3
        mov     #0, R4
        cal     check

        mov-h   #0x800, R0
        add     R0, #8
        mov     #14, R1
        mov     R1, [R0]

        mov     #135, R0
        mov-h   #0x042, R1
        cal     sd_read_sector
        mov     R0, R5
        mov     #lbl_sd_read, R3
        mov     #0, R4
        cal     check

        mov-h   #0x042, R0
        add     R0, #510
        mvb     [R0], R5
        mov     #lbl_sd_b510, R3
        mov     #0x55, R4
        cal     check

        mov-h   #0x042, R0
        add     R0, #511
        mvb     [R0], R5
        mov     #lbl_sd_b511, R3
        mov     #0xAA, R4
        cal     check

        pop     R5
        pop     R4
        pop     R3
        ret

; ── test_alu ─────────────────────────────────────────────────────────────────
test_alu:
        psh     R3
        psh     R4
        psh     R5

        ; add imm: 100 + 23 = 123
        mov     #100, R5
        add     R5, #23
        mov     #lbl_add_imm, R3
        mov     #123, R4
        cal     check

        ; add reg: 200 + 55 = 255
        mov     #200, R0
        mov     #55, R1
        add     R0, R1
        mov     R0, R5
        mov     #lbl_add_reg, R3
        mov     #255, R4
        cal     check

        ; sub imm: 100 - 37 = 63
        mov     #100, R5
        sub     R5, #37
        mov     #lbl_sub_imm, R3
        mov     #63, R4
        cal     check

        ; sub reg: 300 - 100 = 200
        mov     #300, R0
        mov     #100, R1
        sub     R0, R1
        mov     R0, R5
        mov     #lbl_sub_reg, R3
        mov     #200, R4
        cal     check

        ; and imm: 0xFF & 0x0F = 0x0F
        mov     #0xFF, R5
        and     R5, #0x0F
        mov     #lbl_and_imm, R3
        mov     #0x0F, R4
        cal     check

        ; and reg: 0xABCD & 0xFF00 = 0xAB00
        mov     #0xABCD, R0
        mov     #0xFF00, R1
        and     R0, R1
        mov     R0, R5
        mov     #lbl_and_reg, R3
        mov     #0xAB00, R4
        cal     check

        ; orr imm: 0xF0 | 0x0F = 0xFF
        mov     #0xF0, R5
        orr     R5, #0x0F
        mov     #lbl_orr_imm, R3
        mov     #0xFF, R4
        cal     check

        ; orr reg: 0xAB00 | 0x00CD = 0xABCD
        mov     #0xAB00, R0
        mov     #0x00CD, R1
        orr     R0, R1
        mov     R0, R5
        mov     #lbl_orr_reg, R3
        mov     #0xABCD, R4
        cal     check

        ; xor imm: 0xFF ^ 0x0F = 0xF0
        mov     #0xFF, R5
        xor     R5, #0x0F
        mov     #lbl_xor_imm, R3
        mov     #0xF0, R4
        cal     check

        ; xor reg: 0xDEAD ^ 0xDEAD = 0
        mov     #0xDEAD, R0
        mov     #0xDEAD, R1
        xor     R0, R1
        mov     R0, R5
        mov     #lbl_xor_reg, R3
        mov     #0, R4
        cal     check

        ; not: ~0 = 0xFFFFFFFF
        mov     #0, R5
        not     R5
        mov     #lbl_not, R3
        mov     #0, R4
        not     R4
        cal     check

        pop     R5
        pop     R4
        pop     R3
        ret

; ── test_shift ───────────────────────────────────────────────────────────────
test_shift:
        psh     R3
        psh     R4
        psh     R5

        ; shl imm: 1 << 4 = 16
        mov     #1, R5
        shl     R5, #4
        mov     #lbl_shl_imm, R3
        mov     #16, R4
        cal     check

        ; shr imm: 0x80000000 >> 1 = 0x40000000 (logical)
        mov-h   #0x80000, R5
        shr     R5, #1
        mov     #lbl_shr_imm, R3
        mov-h   #0x40000, R4
        cal     check

        ; sar: 0x80000000 sar 1 = 0xC0000000 (sign bit propagates)
        mov-h   #0x80000, R5
        sar     R5, #1
        mov     #lbl_sar, R3
        mov-h   #0xC0000, R4
        cal     check

        ; shf reg: 1 << R1 where R1=8 = 256
        mov     #1, R5
        mov     #8, R1
        shf     R5, R1
        mov     #lbl_shf_reg, R3
        mov     #256, R4
        cal     check

        pop     R5
        pop     R4
        pop     R3
        ret

; ── test_mov ─────────────────────────────────────────────────────────────────
test_mov:
        psh     R3
        psh     R4
        psh     R5

        ; mov imm
        mov     #0x1234, R5
        mov     #lbl_mov_imm, R3
        mov     #0x1234, R4
        cal     check

        ; mov-h + orr: build 0xDEAD0000 | 0xBEEF
        mov-h   #0xDEAD0, R5
        orr     R5, #0xBEEF
        mov     #lbl_mov_h, R3
        mov-h   #0xDEAD0, R4
        orr     R4, #0xBEEF
        cal     check

        ; reg-to-reg
        mov     #0xCAFE, R0
        mov     R0, R5
        mov     #lbl_mov_rr, R3
        mov     #0xCAFE, R4
        cal     check

        ; indirect SRAM write + read
        mov-h   #0x041, R0
        mov     #0xBEEF, R1
        mov     R1, [R0]
        mov     [R0], R5
        mov     #lbl_mov_ind, R3
        mov     #0xBEEF, R4
        cal     check

        pop     R5
        pop     R4
        pop     R3
        ret

; ── test_branch ──────────────────────────────────────────────────────────────
test_branch:
        psh     R3
        psh     R4
        psh     R5

        ; bar.z taken: R=0 → branch
        mov     #0, R0
        mov     #0, R5
        bar.z   R0, tbz1_in
        bar     tbz1_out
tbz1_in:
        mov     #1, R5
tbz1_out:
        mov     #lbl_bz_taken, R3
        mov     #1, R4
        cal     check

        ; bar.z not-taken: R=1 → no branch
        mov     #1, R0
        mov     #0, R5
        bar.z   R0, tbz2_skip
        mov     #1, R5
        bar     tbz2_out
tbz2_skip:
        mov     #0, R5
tbz2_out:
        mov     #lbl_bz_ntaken, R3
        mov     #1, R4
        cal     check

        ; bar.nz taken: R=1 → branch
        mov     #1, R0
        mov     #0, R5
        bar.nz  R0, tbnz1_in
        bar     tbnz1_out
tbnz1_in:
        mov     #1, R5
tbnz1_out:
        mov     #lbl_bnz_taken, R3
        mov     #1, R4
        cal     check

        ; bar.nz not-taken: R=0 → no branch
        mov     #0, R0
        mov     #0, R5
        bar.nz  R0, tbnz2_skip
        mov     #1, R5
        bar     tbnz2_out
tbnz2_skip:
        mov     #0, R5
tbnz2_out:
        mov     #lbl_bnz_ntaken, R3
        mov     #1, R4
        cal     check

        ; bar.n taken: R=0xFFFFFFFF (bit 31 set) → branch
        mov     #0, R0
        not     R0
        mov     #0, R5
        bar.n   R0, tbn1_in
        bar     tbn1_out
tbn1_in:
        mov     #1, R5
tbn1_out:
        mov     #lbl_bn_taken, R3
        mov     #1, R4
        cal     check

        ; bar.n not-taken: R=1 (bit 31 clear) → no branch
        mov     #1, R0
        mov     #0, R5
        bar.n   R0, tbn2_skip
        mov     #1, R5
        bar     tbn2_out
tbn2_skip:
        mov     #0, R5
tbn2_out:
        mov     #lbl_bn_ntaken, R3
        mov     #1, R4
        cal     check

        ; bar.nn taken: R=1 (bit 31 clear) → branch
        mov     #1, R0
        mov     #0, R5
        bar.nn  R0, tbnn1_in
        bar     tbnn1_out
tbnn1_in:
        mov     #1, R5
tbnn1_out:
        mov     #lbl_bnn_taken, R3
        mov     #1, R4
        cal     check

        ; bar.nn not-taken: R=0xFFFFFFFF (bit 31 set) → no branch
        mov     #0, R0
        not     R0
        mov     #0, R5
        bar.nn  R0, tbnn2_skip
        mov     #1, R5
        bar     tbnn2_out
tbnn2_skip:
        mov     #0, R5
tbnn2_out:
        mov     #lbl_bnn_ntaken, R3
        mov     #1, R4
        cal     check

        pop     R5
        pop     R4
        pop     R3
        ret

; ── test_carry ───────────────────────────────────────────────────────────────
test_carry:
        psh     R3
        psh     R4
        psh     R5

        ; add overflow: 0xFFFFFFFF + 1 → carry set, bar.c branches
        mov     #0, R0
        not     R0
        add     R0, #1
        mov     #0, R5
        bar.c   R0, tc_addov_in
        bar     tc_addov_out
tc_addov_in:
        mov     #1, R5
tc_addov_out:
        mov     #lbl_c_add_ov, R3
        mov     #1, R4
        cal     check

        ; add no overflow: 1 + 1 → carry clear, bar.nc branches
        mov     #1, R0
        add     R0, #1
        mov     #0, R5
        bar.nc  R0, tc_addnc_in
        bar     tc_addnc_out
tc_addnc_in:
        mov     #1, R5
tc_addnc_out:
        mov     #lbl_c_add_nc, R3
        mov     #1, R4
        cal     check

        ; sub borrow: 0 - 1 → carry set, bar.c branches
        mov     #0, R0
        sub     R0, #1
        mov     #0, R5
        bar.c   R0, tc_subbw_in
        bar     tc_subbw_out
tc_subbw_in:
        mov     #1, R5
tc_subbw_out:
        mov     #lbl_c_sub_bw, R3
        mov     #1, R4
        cal     check

        ; sub no borrow: 5 - 3 → carry clear, bar.nc branches
        mov     #5, R0
        sub     R0, #3
        mov     #0, R5
        bar.nc  R0, tc_subnc_in
        bar     tc_subnc_out
tc_subnc_in:
        mov     #1, R5
tc_subnc_out:
        mov     #lbl_c_sub_nc, R3
        mov     #1, R4
        cal     check

        pop     R5
        pop     R4
        pop     R3
        ret

; ── test_stack ───────────────────────────────────────────────────────────────
test_stack:
        psh     R3
        psh     R4
        psh     R5

        ; push/pop roundtrip
        mov     #0xABCD, R0
        psh     R0
        mov     #0, R0
        pop     R0
        mov     R0, R5
        mov     #lbl_stk_pp, R3
        mov     #0xABCD, R4
        cal     check

        ; nested: push 1, push 2, pop→2, pop→1, sum=3
        mov     #1, R0
        psh     R0
        mov     #2, R0
        psh     R0
        pop     R0
        pop     R1
        add     R0, R1
        mov     R0, R5
        mov     #lbl_stk_nest, R3
        mov     #3, R4
        cal     check

        ; cal/ret roundtrip
        cal     stk_leaf
        mov     R0, R5
        mov     #lbl_stk_cal, R3
        mov     #0x42, R4
        cal     check

        pop     R5
        pop     R4
        pop     R3
        ret

stk_leaf:
        mov     #0x42, R0
        ret

; ── test_sram ────────────────────────────────────────────────────────────────
test_sram:
        psh     R3
        psh     R4
        psh     R5

        ; mvb write + read at 0x041100
        mov-h   #0x041, R0
        add     R0, #0x100
        mov     #0xA5, R1
        mvb     R1, [R0]
        mvb     [R0], R5
        mov     #lbl_sram_rw, R3
        mov     #0xA5, R4
        cal     check

        ; adjacent bytes don't alias: byte 0x041200=0x11, byte 0x041201=0x22, read 0x041200
        mov-h   #0x041, R0
        add     R0, #0x200
        mov     #0x11, R1
        mvb     R1, [R0]
        add     R0, #1
        mov     #0x22, R1
        mvb     R1, [R0]
        sub     R0, #1
        mvb     [R0], R5
        mov     #lbl_sram_adj, R3
        mov     #0x11, R4
        cal     check

        pop     R5
        pop     R4
        pop     R3
        ret

; ── test_math ────────────────────────────────────────────────────────────────
test_math:
        psh     R3
        psh     R4
        psh     R5

        ; mul pos*pos: 17 * 13 = 221
        mov     #17, R0
        mov     #13, R1
        mul     R0, R1
        mov     R0, R5
        mov     #lbl_mul_pp, R3
        mov     #221, R4
        cal     check

        ; mul neg*pos: -7 * 6 = -42
        mov     #0, R0
        sub     R0, #7
        mov     #6, R1
        mul     R0, R1
        mov     R0, R5
        mov     #lbl_mul_np, R3
        mov     #0, R4
        sub     R4, #42
        cal     check

        ; mul neg*neg: -5 * -8 = 40
        mov     #0, R0
        sub     R0, #5
        mov     #0, R1
        sub     R1, #8
        mul     R0, R1
        mov     R0, R5
        mov     #lbl_mul_nn, R3
        mov     #40, R4
        cal     check

        ; div pos: 100 / 7 = 14
        mov     #100, R0
        mov     #7, R1
        div     R0, R1
        mov     R0, R5
        mov     #lbl_div_pos, R3
        mov     #14, R4
        cal     check

        ; div neg: -100 / 7 = -14
        mov     #0, R0
        sub     R0, #100
        mov     #7, R1
        div     R0, R1
        mov     R0, R5
        mov     #lbl_div_neg, R3
        mov     #0, R4
        sub     R4, #14
        cal     check

        ; mod pos: 100 mod 7 = 2
        mov     #100, R0
        mov     #7, R1
        mod     R0, R1
        mov     R0, R5
        mov     #lbl_mod_pos, R3
        mov     #2, R4
        cal     check

        ; mod neg dividend: -100 mod 7 = -2
        mov     #0, R0
        sub     R0, #100
        mov     #7, R1
        mod     R0, R1
        mov     R0, R5
        mov     #lbl_mod_neg, R3
        mov     #0, R4
        sub     R4, #2
        cal     check

        ; combined: 300*400/500%7 = 2
        mov     #300, R0
        mov     #400, R1
        mul     R0, R1
        mov     #500, R1
        div     R0, R1
        mov     #7, R1
        mod     R0, R1
        mov     R0, R5
        mov     #lbl_math_comb, R3
        mov     #2, R4
        cal     check

        pop     R5
        pop     R4
        pop     R3
        ret

; ── Data — counters ──────────────────────────────────────────────────────────
pass_count:
        .word   0
fail_count:
        .word   0

; ── Data — summary/check strings ─────────────────────────────────────────────
str_pass:
        .str    "Pass: "
str_spacefail:
        .str    "  Fail: "
str_crlf:
        .str    "\r\n"
str_exp:
        .str    " exp:"
str_got:
        .str    " got:"
str_ok:
        .str    " ok\r\n"
str_fail_msg:
        .str    " FAIL\r\n"

; ── Data — print_decimal scratch (16 words, enough for 10 decimal digits) ────
pd_buf:
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
pd_buf_end:

; ── Data — 12-char space-padded test labels (.str, one char per word + NUL) ──
lbl_sd_init:
        .str    "sd_init     "
lbl_sd_read:
        .str    "sd_read     "
lbl_sd_b510:
        .str    "sd_byte510  "
lbl_sd_b511:
        .str    "sd_byte511  "
lbl_add_imm:
        .str    "add_imm     "
lbl_add_reg:
        .str    "add_reg     "
lbl_sub_imm:
        .str    "sub_imm     "
lbl_sub_reg:
        .str    "sub_reg     "
lbl_and_imm:
        .str    "and_imm     "
lbl_and_reg:
        .str    "and_reg     "
lbl_orr_imm:
        .str    "orr_imm     "
lbl_orr_reg:
        .str    "orr_reg     "
lbl_xor_imm:
        .str    "xor_imm     "
lbl_xor_reg:
        .str    "xor_reg     "
lbl_not:
        .str    "not         "
lbl_shl_imm:
        .str    "shl_imm     "
lbl_shr_imm:
        .str    "shr_imm     "
lbl_sar:
        .str    "sar         "
lbl_shf_reg:
        .str    "shf_reg     "
lbl_mov_imm:
        .str    "mov_imm     "
lbl_mov_h:
        .str    "mov_h       "
lbl_mov_rr:
        .str    "mov_rr      "
lbl_mov_ind:
        .str    "mov_ind     "
lbl_bz_taken:
        .str    "bz_taken    "
lbl_bz_ntaken:
        .str    "bz_ntaken   "
lbl_bnz_taken:
        .str    "bnz_taken   "
lbl_bnz_ntaken:
        .str    "bnz_ntaken  "
lbl_bn_taken:
        .str    "bn_taken    "
lbl_bn_ntaken:
        .str    "bn_ntaken   "
lbl_bnn_taken:
        .str    "bnn_taken   "
lbl_bnn_ntaken:
        .str    "bnn_ntaken  "
lbl_c_add_ov:
        .str    "c_add_ov    "
lbl_c_add_nc:
        .str    "c_add_nc    "
lbl_c_sub_bw:
        .str    "c_sub_bw    "
lbl_c_sub_nc:
        .str    "c_sub_nc    "
lbl_stk_pp:
        .str    "stk_pp      "
lbl_stk_nest:
        .str    "stk_nest    "
lbl_stk_cal:
        .str    "stk_cal     "
lbl_sram_rw:
        .str    "sram_rw     "
lbl_sram_adj:
        .str    "sram_adj    "
lbl_mul_pp:
        .str    "mul_pp      "
lbl_mul_np:
        .str    "mul_np      "
lbl_mul_nn:
        .str    "mul_nn      "
lbl_div_pos:
        .str    "div_pos     "
lbl_div_neg:
        .str    "div_neg     "
lbl_mod_pos:
        .str    "mod_pos     "
lbl_mod_neg:
        .str    "mod_neg     "
lbl_math_comb:
        .str    "math_comb   "
