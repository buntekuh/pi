; io_hello.asm
; Prints "Hello!" to the terminal, reads a line, echoes it back.

T46_CMD   = 0x01
T46_ARG0  = 0x02
T46_PRINT = 0x02
T46_KEY   = 0x06

        JMP  AL, main

; -------------------------
; print_str: print null-terminated string
; R7 = pointer to string (must be loaded with LA)
; clobbers R5, R6
; -------------------------
print_str:
        LOAD [R7], R6       ; read word; low byte = char
        AND  #0xFF, R6      ; mask to byte
        JMP  Z, ps_done     ; null terminator
        OUT  #0x02, R6      ; T46_ARG0 = char
        LOAD #0x02, R5
        OUT  #0x01, R5      ; T46_CMD = PRINT
        ADD  #1, R7
        JMP  AL, print_str
ps_done:
        RET  AL

; -------------------------
; main
; -------------------------
main:
        LA   R7, msg
        CAL  AL, print_str

        ; Read a line char by char, echo each one
echo_loop:
        IN   R0, #0x06      ; block until next char
        OUT  #0x02, R0      ; echo it
        LOAD #0x02, R5
        OUT  #0x01, R5
        SUB  #10, R0        ; was it '\n'?
        JMP  NZ, echo_loop  ; no: keep reading

        HALT

; -------------------------
msg:
        .DB 72   ; H
        .DB 101  ; e
        .DB 108  ; l
        .DB 108  ; l
        .DB 111  ; o
        .DB 32   ; space
        .DB 87   ; W
        .DB 101  ; e
        .DB 108  ; l
        .DB 116  ; t
        .DB 33   ; !
        .DB 10   ; \n
        .DB 0    ; null terminator
