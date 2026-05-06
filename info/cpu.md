# M56 CPU

> **Open question:**
> **Memory map** — ROM size unknown; peripheral I/O region address is provisional.

The M56 is a 32-bit RISC CPU. Instructions are 32 bits wide. All registers are
32-bit. The physical address space is 512 KB of SRAM — the full 32-bit address
range is wired to that, with addresses above 0x0007FFFF unmapped.

---

## Registers

16 general-purpose registers, all 32-bit. Two have a fixed role by hardware; the rest are convention:

| Name   | Alias | Notes |
|--------|-------|-------|
| R0–R2  |       | Scratch registers                                |
| R3     |       | Leaf return address (by convention)              |
| R4–R13 |       | General purpose                                  |
| R14    | SP    | Stack pointer. Stack grows downward.             |
| R15    | PC    | Program counter. Advances by 4 after each fetch. |

Writing to R15 redirects execution immediately. Before an instruction executes,
PC is advanced by 4, so reading R15 yields the address of the next instruction.
Writing to R14 moves the stack pointer.

There is no FLAGS register. Conditions are evaluated directly in branch instructions.
Interrupt enable is controlled by the `eai` and `dai` opcodes.

---

## Memory Map

```
0x00000000              Reset vector (first instruction)
0x00000004–0x0000000F   Reserved
0x00000010              Interrupt vector (first instruction of handler)
0x00000014–0x00000FFF   OS scratch
0x00001000–0x0001FFFF   ROM — OS, assembler, Pi interpreter, runtime library
0x00020000–0x0007FFFF   RAM — heap and stack (stack grows down from 0x0007FFFC)
```

### Kernel Call Table

The ROM exposes a stable jump table at the start of the ROM region. Programs
call these fixed addresses — the implementation behind them may change, but the
addresses never move.

```
0x00001000   _mul      jmp  mul_impl    ; software multiply
0x00001004   _div      jmp  div_impl    ; software divide
0x00001008   _mod      jmp  mod_impl    ; software modulo
0x0000100C   _print    jmp  print_impl  ; print null-terminated string — Rsrc = pointer
0x00001010   _printnum jmp  printnum_impl ; print integer to UART — Rsrc = value
...
```

---

## Instruction Format

Every instruction is exactly **32 bits**, 4-byte aligned in memory.

```
Bit  31..27   opcode    (5 bits)   — 32 possible opcodes, 15 defined
Bit  26..23   mode      (4 bits)   — addressing mode
Bit  22..19   register  (4 bits)   — one explicit register
Bit  18..0    (...)    (19 bits)   — immediate, offset, or second register
```

The `mode` field means the same thing across all instructions that take a source
operand: Move, MoveB, ALU, and shift instructions share modes 0–2. The 19-bit field
carries exactly what each mode needs. It is never split arbitrarily.

---

## Opcodes

15 real opcodes. Everything else is an assembler macro or a ROM subroutine.

| Code | Mnemonic | Description |
|------|----------|-------------|
| 0    | mov      | 32-bit word load, store, and register-to-register |
| 1    | mvb      | Byte load or store |
| 2    | add      | Add |
| 3    | sub      | Subtract |
| 4    | and      | Bitwise AND |
| 5    | orr      | Bitwise OR |
| 6    | xor      | Bitwise XOR |
| 7    | not      | Bitwise NOT (unary, in place) |
| 8    | shf      | Logical shift — signed count, positive=left, negative=right |
| 9    | sar      | Arithmetic shift right — sign bit replicated |
| 10   | jmp      | Conditional absolute jump — unsigned address |
| 11   | jpr      | Conditional relative jump — signed PC-relative offset |
| 12   | wfi      | Wait for interrupt — suspends execution until an interrupt fires |
| 13   | eai      | Enable interrupts |
| 14   | dai      | Disable interrupts |

Opcodes 15–31 are reserved for future use.

The `-s` suffix on any jump saves the return address (address of the instruction
after the jump) onto the stack before jumping, turning it into a subroutine call:

| Mnemonic | Description |
|----------|-------------|
| jmp      | absolute jump |
| jmp-s    | absolute subroutine call |
| jpr      | relative jump |
| jpr-s    | relative subroutine call |

### Assembler Macros

Conveniences that expand to real instructions. Not in hardware.

```
jmp    label          →  jmp.al  label
jmp-s  label          →  jmp-s.al label
jpr    label          →  jpr.al  label
jpr-s  label          →  jpr-s.al label
psh Rsrc              →  sub SP, #4 ; mov Rsrc, [SP]
pop Rdst              →  mov [SP], Rdst ; add SP, #4
cal label             →  jmp-s label
ret                   →  pop R15
rti                   →  pop R15 ; eai
nop                   →  add R0, #0
clr Rdst              →  xor Rdst, Rdst
inc Rdst              →  add Rdst, #1
dec Rdst              →  sub Rdst, #1
mul Rsrc, Rdst        →  jmp-s _mul
div Rsrc, Rdst        →  jmp-s _div
shl Rsrc, #n          →  shf Rsrc, #n
shr Rsrc, #n          →  shf Rsrc, #-n
```

### ROM Subroutines

Complex operations implemented once in ROM, called by convention:

```
_mul      software multiply    — shift-and-add
_div      software divide      — shift-and-subtract
_mod      software modulo
_print    print null-terminated string to UART — Rsrc = string pointer
_printnum print integer as decimal to UART    — Rsrc = value
```

---

## Move & MoveB — Addressing Modes

All Move and MoveB instructions share the same field layout:

```
Bit  31..27   opcode    (5 bits)
Bit  26..23   mode      (4 bits)
Bit  22..19   Rsrc/Rdst (4 bits)   — source or address register
Bit  18..0    (...)    (19 bits)   — destination register and/or offset
```

### Mode 0 — Immediate
```
mov #imm19, Rdst
```
Load 19-bit immediate into Rdst, sign-extended to 32 bits. Range: -262144 to +262143.
```
opcode | mode=0 | Rdst | (imm19)
```

### Mode 1 — Move High Immediate
```
mov-h #imm19, Rdst
```
Load 19-bit immediate into the upper bits of Rdst (bits 31..13), zeroing the lower 13 bits.
Combined with mode 0, any 32-bit constant can be loaded in two instructions:
```asm
mov-h  #0x7FFFF, R0    ; R0 = 0xFFFFE000
mov    #0x1FFF,  R0    ; R0 = 0xFFFFFFFF
```
```
opcode | mode=1 | Rdst | (imm19)
```

### Mode 2 — Register to Register
```
mov Rsrc, Rdst
```
Copy Rsrc into Rdst.
```
opcode | mode=2 | Rsrc | (Rdst)
```

### Mode 3 — Indirect Read
```
mov [Rsrc], Rdst
```
Read 32-bit word at address in Rsrc into Rdst.
```
opcode | mode=3 | Rsrc | (Rdst)
```

### Mode 4 — Indirect Write
```
mov Rsrc, [Rdst]
```
Write Rsrc to address held in Rdst.
```
opcode | mode=4 | Rsrc | (Rdst)
```

### Mode 5 — Indexed Read
```
mov [Rsrc+off], Rdst
```
Read 32-bit word at (Rsrc + off) into Rdst.
```
opcode | mode=5 | Rsrc | (Rdst[18:15], offset[14:0])
```

### Mode 6 — Indexed Write
```
mov Rsrc, [Rdst+off]
```
Write Rsrc to (Rdst + off).
```
opcode | mode=6 | Rsrc | (Rdst[18:15], offset[14:0])
```

Modes 7–15 are reserved for future use.

MoveB uses the same mode encoding as Move. Modes 3 and 5 read a byte
(zero-extended). Modes 4 and 6 write the low byte of the register.

---

## ALU Instructions

Add, Sub, And, Orr, Xor use the same `mode` field as Move to select the source
operand. The register field is always Rdst (the destination and left-hand operand).
Only modes 0, 1 and 2 are valid — the ALU never accesses memory directly.

| Mode | Source operand                   |
|------|----------------------------------|
| 0    | 19-bit immediate (sign-extended) |
| 1    | 19-bit high immediate            |
| 2    | register                         |

Result written back to Rdst.

```
add  Rdst, #imm19      →  Rdst = Rdst + sign_extend(imm19)
add  Rdst, Rsrc        →  Rdst = Rdst + Rsrc
```

(sub, and, orr, xor follow the same pattern.)

Multiply and divide are ROM subroutines, not hardware opcodes. The assembler
macros `mul` and `div` expand to `jmp-s _mul` and `jmp-s _div`.

---

## Unary and Shift Instructions

### not
```
not Rsrc    →  Rsrc = ~Rsrc
```
In-place bitwise NOT. No second operand.
```
opcode | 0000 | Rsrc | 0...0
```
Non-destructive NOT: `mov Rsrc, Rdst` then `not Rdst`.

### shf — Logical Shift
```
shf Rsrc, #count       ; mode 0 — immediate signed count
shf Rsrc, Rcounter     ; mode 2 — register signed count
```
Positive count shifts left; negative count shifts right. Result written back to Rsrc.
```
opcode | mode | Rsrc | (#count or Rcounter)
```
Assembler aliases: `shl Rsrc, #n` → `shf Rsrc, #n` and `shr Rsrc, #n` → `shf Rsrc, #-n`.

### sar — Arithmetic Shift Right
```
sar Rsrc, #count       ; mode 0 — immediate signed count
sar Rsrc, Rcounter     ; mode 2 — register signed count
```
Shifts Rsrc right by |count| bits, replicating sign bit (bit 31). Uses the same signed count
convention as `shf`: negative count means right. Positive counts are unused — `shf` handles
left shifts. Result written back to Rsrc.
```
opcode | mode | Rsrc | (#count or Rcounter)
```

---

## Jump and Subroutine

Two jump opcodes: `jmp` (absolute, unsigned address) and `jpr` (relative, signed offset).
The `-s` suffix saves the return address onto the stack before jumping.

Encoding: `opcode(5) | cond(4) | Rcmp(4) | address/offset(19)`

The condition field (4 bits):

```
Bit 3:     subroutine flag — 0 = jump only, 1 = push return address before jumping
Bits 2..0: condition
```

### Condition Codes

| Bits 3..0 | Suffix   | Condition |
|-----------|----------|-----------|
| 0         | .al      | Always (unconditional) |
| 1         | .z       | Rcmp equals zero |
| 2         | .nz      | Rcmp not equal to zero |
| 3         | .n       | Rcmp bit 31 set (negative) |
| 4         | .nn      | Rcmp bit 31 clear (non-negative) |
| 8         | -s.al    | Always (unconditional subroutine) |
| 9         | -s.z     | Rcmp equals zero |
| 10        | -s.nz    | Rcmp not equal to zero |
| 11        | -s.n     | Rcmp bit 31 set (negative) |
| 12        | -s.nn    | Rcmp bit 31 clear (non-negative) |

Rcmp is a register operand. When condition is `.al`, Rcmp is unused; the assembler writes zeros.

```asm
jmp      label           ; absolute jump, unconditional
jmp.z    Rcmp, label     ; absolute jump if Rcmp == 0
jmp.nz   Rcmp, label     ; absolute jump if Rcmp != 0
jmp.n    Rcmp, label     ; absolute jump if Rcmp < 0
jmp.nn   Rcmp, label     ; absolute jump if Rcmp >= 0

jmp-s    label           ; absolute subroutine call, unconditional
jmp-s.z  Rcmp, label     ; absolute subroutine call if Rcmp == 0

jpr      label           ; relative jump, unconditional
jpr.z    Rcmp, label     ; relative jump if Rcmp == 0
jpr.nz   Rcmp, label     ; relative jump if Rcmp != 0
jpr.n    Rcmp, label     ; relative jump if Rcmp < 0
jpr.nn   Rcmp, label     ; relative jump if Rcmp >= 0

jpr-s    label           ; relative subroutine call, unconditional
jpr-s.z  Rcmp, label     ; relative subroutine call if Rcmp == 0
```

For computed jumps (function pointers, dispatch tables), write directly to R15:
```asm
mov  Rsrc, R15           ; jump to address in Rsrc
```

---

## Interrupts

The M56 has a single interrupt line and single priority level.

Interrupts are enabled and disabled with dedicated opcodes:
```
eai    ; enable interrupts
dai    ; disable interrupts
```

`wfi`, `eai`, and `dai` carry no operands. All bits after the opcode are zero.
```
opcode | 0...0(27)
```

When an interrupt fires and interrupts are enabled:
1. The current instruction completes
2. PC is pushed onto the stack
3. Interrupts are disabled automatically
4. PC jumps to the interrupt vector at `0x00000010`

Return from interrupt via the `rti` assembler macro: `pop R15 ; eai`

---

## Memory-Mapped Peripherals

*Note: peripheral addresses below are provisional. A contiguous I/O region of at least 256 bytes (64 × 32-bit registers) should be reserved once the ROM size is known.*

Peripherals are accessed via ordinary `mov` instructions to fixed addresses.
Reading an address returns the peripheral's current state; writing sends a command or data.
The CPU has no knowledge of whether an address is SRAM or a peripheral.

### UART — 0x400000

| Access | Bits    | Meaning |
|--------|---------|---------|
| read   | 9       | TX busy |
| read   | 8       | RX valid |
| read   | 7..0    | Received byte |
| write  | 7..0    | Byte to transmit |

### T46 Terminal — 0x500000

| Address    | Access | Purpose |
|------------|--------|---------|
| 0x500000   | write  | Execute terminal command |
| 0x500004   | write  | Argument 0 |
| 0x500008   | write  | Argument 1 |
| 0x50000C   | write  | Argument 2 |
| 0x500010   | write  | Argument 3 |
| 0x500014   | read   | Read next keycode (blocks until key pressed) |

### T46 Commands

| Code | Name  | Arguments |
|------|-------|-----------|
| 0x01 | cls   | — |
| 0x02 | print | arg0 = character code |
| 0x03 | pen   | arg0 = palette colour index |
| 0x04 | plot  | arg0 = x, arg1 = y |
| 0x05 | line  | arg0 = x1, arg1 = y1, arg2 = x2, arg3 = y2 |
| 0x06 | fill  | arg0 = x, arg1 = y |
| 0x07 | rect  | arg0 = x, arg1 = y, arg2 = w, arg3 = h |
| 0x08 | mode  | arg0 = 0 (text) or 1 (graphics) |

---

## Reset

On reset:
- R15 (PC) = 0x00000000
- R14 (SP) = 0x0007FFFC
- Interrupts disabled
- All other registers = 0
