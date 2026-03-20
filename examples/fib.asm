; fib.asm — Fibonacci sequence, pushing each term onto the stack
;
; Computes fib(0)..fib(N-1) and pushes each result.
; After completion the stack holds the sequence with fib(N-1) on top.
;
; Registers:
;   R0 — current fib term  (F_n)
;   R1 — previous fib term (F_n-1)
;   R2 — loop counter (counts down from N)
;   R3 — scratch (holds R0 before update)
;
; Result on stack (top → bottom): fib(9) fib(8) ... fib(1) fib(0)

        LOAD #10, R2        ; compute 10 terms
        LOAD #0,  R0        ; F_0 = 0
        LOAD #1,  R1        ; F_1 = 1

loop:
        PUSH R0             ; push current term onto stack
        LOAD R0,  R3        ; R3 = R0  (save before overwrite)
        ADD  R1,  R0        ; R0 = R0 + R1  (next term)
        LOAD R3,  R1        ; R1 = old R0   (slide window)
        SUB  #1,  R2        ; R2 = R2 - 1
        JMP  NZ,  loop      ; repeat until counter hits zero

        HALT                ; done — stack holds fib(0)..fib(9), fib(9) on top
