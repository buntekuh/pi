# Assembly Programming on the M56

## Hello World

The simplest useful program: print a string to the terminal and halt.

```asm
; Hello World
; Prints "Hello, World!" via the UART and halts.

        mov  #msg, R1       ; R1 = address of first character

loop:   mvb  [R1], R0       ; read byte at R1 into R0 (zero-extended)
        jmp.z done          ; if zero byte, end of string
        cal.al _print_char  ; print character in R0 via ROM routine
        add  R1, #1         ; advance pointer to next byte
        jmp.al loop         ; repeat

done:   hlt                 ; stop

msg:    .byte "Hello, World!", 0
```

### What each line teaches

| Line | Concept |
|------|---------|
| `mov #msg, R1` | Immediate load — `msg` is an address, a 32-bit word like any other |
| `mvb [R1], R0` | Indirect byte read — R1 holds an address, `mvb` fetches the byte there |
| `jmp.z done` | Conditional jump — the Z flag was set if R0 is zero (null terminator) |
| `cal.al _print_char` | Subroutine call — jumps to ROM, saves return address on the stack |
| `add R1, #1` | Pointer arithmetic — advancing one byte through memory |
| `jmp.al loop` | Unconditional jump — `.al` means Always |
| `hlt` | Halt — stops the CPU |
| `.byte "...", 0` | Data directive — places bytes in memory at this address |

### The same program in Titania-0

```c
print("Hello, World!")
```

The compiler generates exactly the assembly above. Nothing is hidden —
the loop, the pointer, the null check are all there. The compiler just
writes them so you do not have to.

---

## Registers

The M56 has 16 registers, R0–R15. Two have fixed roles:

- **R14** (SP) — stack pointer, used by `cal` and `ret`
- **R15** (PC) — program counter, used by `jmp` and `cal`

By convention:
- **R0** — scratch register, return values
- **R1** — first argument to ROM routines (string pointer, value)

---

## Condition suffixes

Every `jmp`, `cal`, and `ret` takes a condition suffix:

| Suffix | Meaning |
|--------|---------|
| `.al` | Always — unconditional |
| `.z`  | Zero flag set — equal, or result was zero |
| `.nz` | Zero flag clear — not equal |
| `.c`  | Carry set — unsigned below |
| `.nc` | Carry clear — unsigned above or equal |
| `.n`  | Negative flag set |
| `.nn` | Negative flag clear |
| `.v`  | Overflow flag set |

---

## The kernel call table

ROM routines live at fixed addresses. Call them by name — the assembler
resolves the address.

| Name | Address | Does |
|------|---------|------|
| `_mul` | 0x00001000 | R0 = R0 * R1 |
| `_div` | 0x00001004 | R0 = R0 / R1 |
| `_mod` | 0x00001008 | R0 = R0 % R1 |
| `_print` | 0x0000100C | print null-terminated string at R1 to UART |
| `_printnum` | 0x00001010 | print integer in R1 as decimal to UART |
