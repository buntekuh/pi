; math.s — Titania M56: software multiply, divide, modulo
;
; T-code pseudo-opcodes 28/29/30 expand to cal these entry points on M56.
;
; Calling convention (M56 standard):
;   R0 = first argument  (left-hand operand / dividend)
;   R1 = second argument (right-hand operand / divisor)
;   R0 = result (on return)
;   R2 clobbers; R3–R12 preserved.
;
; All three routines implement the signed operation.
;
; Limitation: inputs must be strictly less than 2^31 in magnitude.
; INT_MIN (-2^31) as an input produces an undefined result.

; ── _mul ─────────────────────────────────────────────────────────────────────
; R0 = R0 * R1  (signed 32-bit, lower 32 bits of product)
; Shift-and-add over the 32 bits of the multiplier.
; Clobbers R0–R2.  Preserves R3–R5.
_mul:
        psh     R3
        psh     R4
        psh     R5

        ; Sign: result negative iff exactly one operand is negative (XOR of signs).
        mov     R0, R3
        xor     R3, R1          ; R3 bit 31 = result sign
        psh     R3

        bar.nn  R0, mul_pos_a
        not     R0
        add     R0, #1          ; R0 = |R0|
mul_pos_a:
        bar.nn  R1, mul_pos_b
        not     R1
        add     R1, #1          ; R1 = |R1|
mul_pos_b:
        mov     #0, R3          ; R3 = accumulator
        mov     #32, R4         ; R4 = bit counter
        mov     R0, R5          ; R5 = current multiplicand (shifts left)

mul_loop:
        mov     R1, R2
        and     R2, #1          ; R2 = LSB of multiplier
        bar.z   R2, mul_skip
        add     R3, R5          ; accumulate when multiplier bit is set
mul_skip:
        shr     R1, #1          ; advance to next multiplier bit
        shl     R5, #1          ; double the multiplicand
        dec     R4
        bar.nz  R4, mul_loop

        pop     R4              ; R4 = result sign
        bar.nn  R4, mul_done
        not     R3
        add     R3, #1          ; negate
mul_done:
        mov     R3, R0

        pop     R5
        pop     R4
        pop     R3
        ret

; ── _div ─────────────────────────────────────────────────────────────────────
; R0 = R0 / R1  (signed, truncates toward zero)
; Restoring division: process 32 bits of dividend MSB-first.
; Clobbers R0–R2.  Preserves R3–R6.
;
; How it works: R6 holds the remaining dividend bits.  Each iteration shifts
; R6 left; the MSB that was in R6 becomes the next bit fed into the partial
; remainder R4.  We test R6's MSB BEFORE the shift via bar.nn (branches when
; bit 31 is clear).  After trial-subtracting the divisor, bit 31 of R4 set
; means unsigned underflow — restore the remainder.
_div:
        psh     R3
        psh     R4
        psh     R5
        psh     R6

        mov     R0, R3
        xor     R3, R1          ; R3 bit 31 = result sign
        psh     R3

        bar.nn  R0, div_pos_a
        not     R0
        add     R0, #1
div_pos_a:
        bar.nn  R1, div_pos_b
        not     R1
        add     R1, #1
div_pos_b:
        mov     #0, R3          ; R3 = quotient
        mov     #0, R4          ; R4 = partial remainder
        mov     #32, R5         ; R5 = bit counter
        mov     R0, R6          ; R6 = dividend (shifts left each round)

div_loop:
        shl     R4, #1          ; remainder <<= 1
        bar.nn  R6, div_no_bit  ; if MSB of dividend = 0 → no bit to bring in
        orr     R4, #1          ; bring MSB of dividend into LSB of remainder
div_no_bit:
        shl     R6, #1          ; consume that dividend bit
        shl     R3, #1          ; quotient <<= 1
        sub     R4, R1          ; trial subtract
        bar.n   R4, div_restore ; bit 31 set → unsigned underflow → restore
        orr     R3, #1          ; subtract succeeded: set quotient bit
        bar     div_next
div_restore:
        add     R4, R1
div_next:
        dec     R5
        bar.nz  R5, div_loop

        pop     R5              ; R5 = result sign
        bar.nn  R5, div_done
        not     R3
        add     R3, #1
div_done:
        mov     R3, R0

        pop     R6
        pop     R5
        pop     R4
        pop     R3
        ret

; ── _mod ─────────────────────────────────────────────────────────────────────
; R0 = R0 mod R1  (signed: sign of result matches sign of dividend, like C '%')
; Same algorithm as _div but returns the remainder (R4) rather than quotient.
; Clobbers R0–R2.  Preserves R3–R6.
_mod:
        psh     R3
        psh     R4
        psh     R5
        psh     R6

        mov     R0, R3
        psh     R3              ; save dividend sign for remainder sign

        bar.nn  R0, mod_pos_a
        not     R0
        add     R0, #1
mod_pos_a:
        bar.nn  R1, mod_pos_b
        not     R1
        add     R1, #1
mod_pos_b:
        mov     #0, R3          ; R3 = quotient (discarded)
        mov     #0, R4          ; R4 = partial remainder
        mov     #32, R5
        mov     R0, R6

mod_loop:
        shl     R4, #1
        bar.nn  R6, mod_no_bit
        orr     R4, #1
mod_no_bit:
        shl     R6, #1
        shl     R3, #1
        sub     R4, R1
        bar.n   R4, mod_restore
        orr     R3, #1
        bar     mod_next
mod_restore:
        add     R4, R1
mod_next:
        dec     R5
        bar.nz  R5, mod_loop

        pop     R5              ; R5 = dividend sign
        bar.nn  R5, mod_done
        not     R4
        add     R4, #1          ; negate remainder to match dividend sign
mod_done:
        mov     R4, R0

        pop     R6
        pop     R5
        pop     R4
        pop     R3
        ret
