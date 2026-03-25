; hello.asm — first M56 test program
; Counts from 0 to 5 in R0, uses a subroutine to double R1

        LOAD #0, R0         ; R0 = 0  (counter)
        LOAD #5, R2         ; R2 = 5  (limit)

loop:
        ADD  #1, R0         ; R0 = R0 + 1
        LOAD R0, R1         ; R1 = R0
        CAL  AL, double     ; R1 = R1 * 2
        SUB  R2, R0         ; flags set: is R0 == R2?
        ADD  R2, R0         ; restore R0
        JMP  NZ, loop       ; keep going if not equal

        JMP  AL, done       ; finished

double:
        ADD  R1, R1         ; R1 = R1 + R1
        RET  AL

done:
        NOP                 ; R0 = 5, R1 = 10 here
