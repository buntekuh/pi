; shell.asm — minimal M56 shell
;
; Prints a prompt, reads a line from the terminal, echoes it back.
; Loops forever. A starting point for a real command interpreter.
;
; Syscalls used (T46 I/O ports):
;   PORT_T46_ARG0 = 0x02   set character to print
;   PORT_T46_CMD  = 0x01   fire command (0x02 = CMD_PRINT)
;   PORT_T46_KEY  = 0x06   read one character (blocks)

        JMP  AL, main

; ---------------------------------------------------------------
; print_str: print null-terminated string at address in R7
; Clobbers R5, R6
; ---------------------------------------------------------------
print_str:
        LOAD  [R7], R6
        AND   #0xFF, R6
        JMP   Z, ps_done
        OUT   #0x02, R6         ; ARG0 = char
        LOAD  #0x02, R5
        OUT   #0x01, R5         ; CMD_PRINT
        ADD   #1, R7
        JMP   AL, print_str
ps_done:
        RET   AL

; ---------------------------------------------------------------
; print_char: print single char in R6
; Clobbers R5
; ---------------------------------------------------------------
print_char:
        OUT   #0x02, R6
        LOAD  #0x02, R5
        OUT   #0x01, R5
        RET   AL

; ---------------------------------------------------------------
; read_line: read characters into buffer at R0, max R1 chars.
; Stops on newline (newline not stored). Null-terminates.
; Returns length in R2.
; ---------------------------------------------------------------
read_line:
        LOAD  #0, R2            ; length = 0
rl_loop:
        IN    R6, #0x06         ; blocking read from terminal
        AND   #0xFF, R6
        JMP   Z, rl_done        ; 0 = closed
        LOAD  #10, R5           ; newline?
        SUB   R5, R6
        JMP   Z, rl_done
        ADD   R5, R6            ; restore R6 (undo SUB)
        LOAD  R6, [R0]          ; store char in buffer
        ADD   #1, R0
        ADD   #1, R2
        SUB   #1, R1
        JMP   Z, rl_done        ; buffer full
        JMP   AL, rl_loop
rl_done:
        LOAD  #0, R6
        LOAD  R6, [R0]          ; null-terminate
        RET   AL

; ---------------------------------------------------------------
; main
; ---------------------------------------------------------------
main:
        LA    R7, prompt
        CAL   AL, print_str

        LA    R0, input_buf     ; buffer address
        LOAD  #127, R1          ; max chars
        CAL   AL, read_line

        ; echo ">> <input>\n"
        LA    R7, echo_msg
        CAL   AL, print_str

        LA    R7, input_buf
        CAL   AL, print_str

        LOAD  #10, R6           ; newline
        CAL   AL, print_char

        JMP   AL, main          ; loop

; ---------------------------------------------------------------
; Data
; ---------------------------------------------------------------
prompt:
        .DB "M56> ", 0

echo_msg:
        .DB ">> ", 0

input_buf:
        .DS 128                 ; 128-byte input buffer
