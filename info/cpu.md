# M56 CPU

The M56 is a 32-bit RISC CPU. Instructions are 32 bits wide. All registers are
32-bit. The physical address space is 512 KB of SRAM — the full 32-bit address
range is wired to that, with addresses above 0x0007FFFF unmapped.

---

## Registers

16 general-purpose registers, all 32-bit. Two have a fixed role by convention:

| Name   | Alias | Notes |
|--------|-------|-------|
| R0     |       | Conventional scratch register                    |
| R1–R13 |       | General purpose                                  |
| R14    | SP    | Stack pointer. Stack grows downward.             |
| R15    | PC    | Program counter. Advances by 4 after each fetch. |

Writing to R15 redirects execution immediately. Before an instruction executes,
PC is advanced by 4, so reading R15 yields the address of the next instruction.
Writing to R14 moves the stack pointer.

A separate FLAGS register holds condition bits and the interrupt enable flag.
It is not part of the general register file but is readable and writable via
dedicated instructions.

### FLAGS

| Bit | Name | Set when |
|-----|------|----------|
| 0   | Z    | Result is zero |
| 1   | C    | Unsigned overflow / borrow |
| 2   | V    | Signed overflow |
| 3   | N    | Result bit 31 is set |
| 4   | IE   | Interrupts enabled |

---

## Memory Map

```
0x00000000              Reset vector (first instruction)
0x00000004–0x0000000F   Reserved
0x00000010              Interrupt vector (first instruction of handler)
0x00000014–0x00000FFF   OS scratch
0x00001000–0x0001FFFF   ROM — OS, assembler, Pi interpreter, runtime library
0x00020000–0x0007FFFF   RAM — heap and stack (stack grows down from 0x0007FFFC)
Not specified yet, needs to be confirmed later
```

### Kernel Call Table

The ROM exposes a stable jump table at the start of the ROM region. Programs
call these fixed addresses — the implementation behind them may change, but the
addresses never move.

```
0x00001000   _mul     Jump.Al  mul_impl   ; software multiply
0x00001004   _div     Jump.Al  div_impl   ; software divide
0x00001008   _mod     Jump.Al  mod_impl   ; software modulo
0x0000100C   ...
...
```

---

## Instruction Format

Every instruction is exactly **32 bits**, 4-byte aligned in memory.

```
Bit  31..27   opcode    (5 bits)   — 32 possible opcodes, 18 defined
Bit  26..23   mode      (4 bits)   — addressing mode
Bit  22..19   register  (4 bits)   — one explicit register
Bit  18..0    (...)    (19 bits)   — immediate, offset, or second register
```

The `mode` field means the same thing across all instructions that take a source
operand: Move, MoveB, and all ALU instructions (Add, Sub, And, Or, Xor) share
modes 0–5. The 19-bit field carries exactly what each mode needs — a full
immediate, a second register, an offset, or a combination. It is never split
arbitrarily.

---

## Opcodes

18 real opcodes. Everything else is an assembler macro or a ROM subroutine.

| Code | Mnemonic | Description |
|------|----------|-------------|
| 0    | Move     | 32-bit word load, store, and register-to-register |
| 1    | MoveB    | Byte load or store |
| 2    | Add      | Add |
| 3    | Sub      | Subtract |
| 4    | And      | Bitwise AND |
| 5    | Or       | Bitwise OR |
| 6    | Xor      | Bitwise XOR |
| 7    | Not      | Bitwise NOT (unary) |
| 8    | Shift    | Logical shift left or right |
| 9    | ShiftA   | Arithmetic shift right (sign-preserving) |
| 10   | Swap     | Swap high and low 16-bit halves of register |
| 11   | Jump     | Conditional register-relative offset |
| 12   | Call     | Conditional call (push PC, jump) |
| 13   | Ret      | Conditional return (pop PC) |
| 14   | RetI     | Return from interrupt (pop PC + FLAGS) |
| 15   | Halt     | Halt CPU |
| 16   | In       | Read I/O port into register (blocking) |
| 17   | Out      | Write register to I/O port |

Opcodes 18–31 are reserved for future use.

### Assembler Macros

Conveniences that expand to real instructions. Not in hardware.

```
Push src         →  Sub SP, #4 ; Move src, [SP]
Pop  dest        →  Move [SP], dest ; Add SP, #4
Nop              →  Add R0, #0
Clr  dest        →  Xor dest, dest
Inc  dest        →  Add dest, #1
Dec  dest        →  Sub dest, #1
EI               →  Or  FLAGS, #0x10
DI               →  And FLAGS, #~0x10
Jump.cond off    →  Jump R15, (cond, off)
Ret.cond         →  Ret  (cond)
Mul  dest, src   →  Call.Al _mul
Div  dest, src   →  Call.Al _div
```

### ROM Subroutines

Complex operations implemented once in ROM, called by convention:

```
_mul    software multiply   — shift-and-add
_div    software divide     — shift-and-subtract
_mod    software modulo

; Note: _mul, _div, _mod are leaf functions — candidates for a QuickCall/R13
; convention (return via R13 instead of stack) once calling conventions are settled.
```

---

## Move & MoveB — Addressing Modes

All Move and MoveB instructions share the same field layout:

```
Bit  31..27   opcode    (5 bits)
Bit  26..23   mode      (4 bits)
Bit  22..19   register  (4 bits)   — source or address register
Bit  18..0    (...)    (19 bits)   — destination register and/or offset
```

### Mode 0 — Immediate
```
Move #imm19, dest
```
Load 19-bit unsigned immediate into dest, zero-extended to 32 bits.
```
opcode | mode=0 | dest | (imm19)
```

### Mode 1 — Register to Register
```
Move src, dest
```
Copy src into dest.
```
opcode | mode=1 | src | (dest)
```

### Mode 2 — Indirect Read
```
Move [src], dest
```
Read 32-bit word at address in src into dest.
```
opcode | mode=2 | src | (dest)
```

### Mode 3 — Indirect Write
```
Move src, [dest]
```
Write src to address held in dest.
```
opcode | mode=3 | src | (dest)
```

### Mode 4 — Indexed Read
```
Move [src+off], dest
```
Read 32-bit word at (src + off) into dest.
```
opcode | mode=4 | src | (dest[18:15], offset[14:0])
```

### Mode 5 — Indexed Write
```
Move src, [dest+off]
```
Write src to (dest + off).
```
opcode | mode=5 | src | (dest[18..15], offset[14..0])
```

Modes 6–15 are reserved for future use.

MoveB uses the same mode encoding as Move. Modes 2 and 4 read a byte
(zero-extended). Modes 3 and 5 write the low byte of the register.

---

## ALU Instructions

Add, Sub, And, Or, Xor use the same `mode` field as Move to select the source
operand. The `register` field is always the destination (and left-hand operand).
Modes 3 and 5 (indirect write) are not valid — the result always goes to a register.

| Mode | Source operand         |
|------|------------------------|
| 0    | 19-bit immediate       |
| 1    | register               |
| 2    | word at [src]          |
| 4    | word at [src+off]      |

Result written to the register field. FLAGS updated after every ALU operation.

```
Add  dest, #imm19      →  dest = dest + imm19
Add  dest, src         →  dest = dest + src
Add  dest, [src]       →  dest = dest + mem[src]
Add  dest, [src+off]   →  dest = dest + mem[src+off]
```

(Sub, And, Or, Xor follow the same pattern.)

Multiply and divide are ROM subroutines, not hardware opcodes. The assembler
macros `Mul` and `Div` expand to `Call.Al _mul` and `Call.Al _div`.

---

## Unary Instructions

### Not
```
Not dest    →  dest = ~dest
```
Updates Z and N flags.

### Shift — Logical Shift
```
Shift dest, #n
```
Bits [4:0] of the 19-bit field hold a 5-bit signed shift count.
- Positive → shift left
- Negative (bit 4 set) → logical shift right

### ShiftA — Arithmetic Shift Right
```
ShiftA dest, #n
```
Right shift by n bits, sign bit (bit 31) replicated.

### Swap
```
Swap dest    →  dest = ((dest & 0xFFFF) << 16) | (dest >> 16)
```
Swaps high and low 16-bit halves.

---

## Condition Codes

Used in Jump, Call, and Ret via bits [18:16] of the 19-bit field.

| Code | Name | Condition |
|------|------|-----------|
| 0    | Z    | Zero set — equal |
| 1    | Nz   | Zero clear — not equal |
| 2    | C    | Carry set — unsigned below |
| 3    | Nc   | Carry clear — unsigned above or equal |
| 4    | N    | Negative set |
| 5    | Nn   | Negative clear |
| 6    | V    | Overflow set |
| 7    | Al   | Always — unconditional |

---

## Interrupts

The M56 has a single interrupt line and single priority level.

When an interrupt fires and IE (FLAGS bit 4) is set:
1. The current instruction completes
2. FLAGS is pushed onto the stack
3. PC is pushed onto the stack
4. IE is cleared (interrupts disabled for the duration of the handler)
5. PC jumps to the interrupt vector at `0x00000010`

Return from interrupt is via the `RetI` opcode: pops PC then FLAGS, restoring IE to its pre-interrupt state.

---

## I/O

Ports are 8-bit numbers. The I/O bus connects the CPU to peripherals.
All I/O is synchronous; In blocks until data is available.

*Note: port-based I/O vs memory-mapped I/O is an open decision, pending
review of the hardware implementation. Out and In are placeholder opcodes.*

### In
```
In dest, #port    ; read port into dest (blocking)
```

### Out
```
Out #port, src    ; write src to port
```

### T46 Terminal Ports

| Port | Direction | Purpose |
|------|-----------|---------|
| 0x01 | Out | Execute terminal command |
| 0x02 | Out | Argument 0 |
| 0x03 | Out | Argument 1 |
| 0x04 | Out | Argument 2 |
| 0x05 | Out | Argument 3 |
| 0x06 | In  | Read next keycode (blocks until key pressed) |

### T46 Commands

| Code | Name  | Arguments |
|------|-------|-----------|
| 0x01 | Cls   | — |
| 0x02 | Print | arg0 = character code |
| 0x03 | Pen   | arg0 = palette colour index |
| 0x04 | Plot  | arg0 = x, arg1 = y |
| 0x05 | Line  | arg0 = x1, arg1 = y1, arg2 = x2, arg3 = y2 |
| 0x06 | Fill  | arg0 = x, arg1 = y |
| 0x07 | Rect  | arg0 = x, arg1 = y, arg2 = w, arg3 = h |
| 0x08 | Mode  | arg0 = 0 (text) or 1 (graphics) |

---

## Reset

On reset:
- R15 (PC) = 0x00000000
- R14 (SP) = 0x0007FFFC
- FLAGS     = 0x00000010  (IE set — interrupts enabled from the start)
- All other registers = 0
