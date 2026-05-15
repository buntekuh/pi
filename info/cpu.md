# M56 CPU

The M56 is a 32-bit RISC CPU. Instructions are 32 bits wide. All registers are
32-bit. The physical address space covers 1 MB (imm20 range), mapped as follows:

---

## Registers

16 general-purpose registers, all 32-bit. Two have a fixed role by hardware; the rest are convention:

| Name   | Alias | Notes |
|--------|-------|-------|
| R0–R2  |       | Scratch registers                                |
| R3     |       | Leaf return address (by convention)              |
| R4–R12 |       | General purpose                                  |
| R13    | LR    | Interrupt link register — hardware saves PC here on interrupt entry |
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
0x000000              Reset vector (first instruction)
0x000004–0x00000F     Reserved
0x000010              Interrupt vector (first instruction of handler)
0x000014–0x03FFFF     BRAM — kernel, runtime, filesystem (225 KB used of 256 KB window)
0x040000–0x0BFFFF     SRAM — heap and stack (stack grows down from 0x0BFFFC)
0x0C0000–0x0FFFFF     Unused address space (256 KB, above SRAM)
0x400000              UART (peripheral, above imm20 range — needs two instructions)
```

BRAM and SRAM are distinguished by bit 18 of the address:
- bit 18 = 0 → BRAM (system space, 0x000000–0x03FFFF)
- bit 18 = 1 → SRAM (user space, 0x040000–0x0BFFFF)

All of BRAM and SRAM is within the 20-bit immediate range and is directly
addressable with a single `mov` instruction. Peripherals sit above 0x0FFFFF
and always require two instructions to reach.

### Kernel Call Table

The BRAM exposes a stable jump table at a known address. Programs call these
fixed addresses — the implementation behind them may change, but the addresses
never move.

```
0x001000   _mul      jmp  mul_impl    ; software multiply
0x001004   _div      jmp  div_impl    ; software divide
0x001008   _mod      jmp  mod_impl    ; software modulo
0x00100C   _print    jmp  print_impl  ; print null-terminated string — Rsrc = pointer
0x001010   _printnum jmp  printnum_impl ; print integer to UART — Rsrc = value
...
```

---

## Instruction Format

Every instruction is exactly **32 bits**, 4-byte aligned in memory.

```
Bit  31..27   opcode    (5 bits)   — 32 possible opcodes, 18 defined
Bit  26..24   mode      (3 bits)   — addressing mode (modes 0–6 used; 7 reserved)
Bit  23..20   register  (4 bits)   — one explicit register
Bit  19..0    imm20    (20 bits)   — immediate, offset, or second register
```

The `mode` field means the same thing across all instructions that take a source
operand: Move, MoveB, ALU, and shift instructions share modes 0–6. The 20-bit
field carries exactly what each mode needs. It is never split arbitrarily.

---

## Opcodes

18 real opcodes. Everything else is an assembler macro or a ROM subroutine.

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
| 10   | jmp      | Conditional absolute jump — goto, no return address saved |
| 11   | jpr      | Conditional relative jump — goto, PC-relative offset |
| 12   | bra      | Conditional absolute branch — subroutine call, saves return address |
| 13   | bar      | Conditional relative branch — subroutine call, PC-relative |
| 14   | wfi      | Wait for interrupt — suspends execution until an interrupt fires |
| 15   | eai      | Enable interrupts |
| 16   | dai      | Disable interrupts |
| 17   | rti      | Return from interrupt — enable interrupts and jump to R13 |

Opcodes 18–31 are reserved for future use.

**jump** (`jmp`, `jpr`) transfers control without saving anything — a goto.
**branch** (`bra`, `bar`) saves the return address on the stack before jumping —
a subroutine call. The difference is in the opcode, not a mode bit.

### Assembler Macros

Conveniences that expand to real instructions. Not in hardware.

```
jmp    label          →  jmp.al  label
jpr    label          →  jpr.al  label
bra    label          →  bra.al  label
bar    label          →  bar.al  label
psh Rsrc              →  sub SP, #4 ; mov Rsrc, [SP]
pop Rdst              →  mov [SP], Rdst ; add SP, #4
cal label             →  bra label
ret                   →  rts
nop                   →  add R0, #0
clr Rdst              →  xor Rdst, Rdst
inc Rdst              →  add Rdst, #1
dec Rdst              →  sub Rdst, #1
mul Rsrc, Rdst        →  bra _mul
div Rsrc, Rdst        →  bra _div
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
Bit  26..24   mode      (3 bits)
Bit  23..20   Rsrc/Rdst (4 bits)   — source or address register
Bit  19..0    imm20    (20 bits)   — destination register and/or offset
```

### Mode 0 — Immediate
```
mov #imm20, Rdst
```
Load 20-bit immediate into Rdst, sign-extended to 32 bits. Range: -524288 to +524287.
```
opcode | mode=0 | Rdst | (imm20)
```

### Mode 1 — Move High Immediate
```
mov-h #imm20, Rdst
```
Load 20-bit immediate into the upper bits of Rdst (bits 31..12), zeroing the lower 12 bits.
Combined with `orr` mode 0, any 32-bit constant can be loaded in two instructions:
```asm
mov-h  #0x12345, R0    ; R0 = 0x12345000
orr    R0, #0x678      ; R0 = 0x12345678
```
```
opcode | mode=1 | Rdst | (imm20)
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
opcode | mode=5 | Rsrc | (Rdst[19:16], offset[15:0])
```

### Mode 6 — Indexed Write
```
mov Rsrc, [Rdst+off]
```
Write Rsrc to (Rdst + off).
```
opcode | mode=6 | Rsrc | (Rdst[19:16], offset[15:0])
```

Mode 7 is reserved for future use.

MoveB uses the same mode encoding as Move. Modes 3 and 5 read a byte
(zero-extended). Modes 4 and 6 write the low byte of the register.

---

## ALU Instructions

Add, Sub, And, Orr, Xor use the same `mode` field as Move to select the source
operand. The register field is always Rdst (the destination and left-hand operand).
Only modes 0, 1 and 2 are valid — the ALU never accesses memory directly.

| Mode | Source operand                   |
|------|----------------------------------|
| 0    | 20-bit immediate (sign-extended) |
| 1    | 20-bit high immediate            |
| 2    | register                         |

Result written back to Rdst.

```
add  Rdst, #imm20      →  Rdst = Rdst + sign_extend(imm20)
add  Rdst, Rsrc        →  Rdst = Rdst + Rsrc
```

(sub, and, orr, xor follow the same pattern.)

Multiply and divide are ROM subroutines, not hardware opcodes. The assembler
macros `mul` and `div` expand to `bra _mul` and `bra _div`.

---

## Unary and Shift Instructions

### not
```
not Rsrc    →  Rsrc = ~Rsrc
```
In-place bitwise NOT. No second operand.
```
opcode | 000 | Rsrc | 0...0
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
Shifts Rsrc right by |count| bits, replicating sign bit (bit 31). Result written back to Rsrc.
```
opcode | mode | Rsrc | (#count or Rcounter)
```

---

## Jump and Branch

Four opcodes for control flow transfer:

| Opcode | Mnemonic | Addressing | Return address |
|--------|----------|------------|----------------|
| 10 | `jmp` | absolute (imm20) | not saved — goto |
| 11 | `jpr` | relative (PC + imm20) | not saved — goto |
| 12 | `bra` | absolute (imm20) | pushed on stack — call |
| 13 | `bar` | relative (PC + imm20) | pushed on stack — call |

Encoding: `opcode(5) | cond(3) | Rcmp(4) | address/offset(20)`

The 3-bit mode field carries the condition code:

### Condition Codes

| mode[2:0] | Suffix | Condition |
|-----------|--------|-----------|
| 0         | .al    | Always (unconditional) |
| 1         | .z     | Rcmp equals zero |
| 2         | .nz    | Rcmp not equal to zero |
| 3         | .n     | Rcmp bit 31 set (negative) |
| 4         | .nn    | Rcmp bit 31 clear (non-negative) |
| 5–7       | —      | Reserved |

Rcmp is a register operand. When condition is `.al`, Rcmp is unused; the assembler writes zeros.

```asm
jmp      label           ; absolute goto, unconditional
jmp.z    Rcmp, label     ; absolute goto if Rcmp == 0
jmp.nz   Rcmp, label     ; absolute goto if Rcmp != 0
jmp.n    Rcmp, label     ; absolute goto if Rcmp < 0
jmp.nn   Rcmp, label     ; absolute goto if Rcmp >= 0

jpr      label           ; relative goto, unconditional
jpr.z    Rcmp, label     ; relative goto if Rcmp == 0

bra      label           ; absolute call, unconditional
bra.nz   Rcmp, label     ; absolute call if Rcmp != 0

bar      label           ; relative call, unconditional
bar.z    Rcmp, label     ; relative call if Rcmp == 0
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
1. The current instruction is abandoned (not executed)
2. PC (the return address) is pushed onto the stack
3. R13 is written with the interrupt status word (one bit per source)
4. Interrupts are disabled automatically
5. PC jumps to the interrupt vector at `0x000010`

`rti` must be a single hardware instruction. If it were two instructions
(`eai` then `mov R13, R15`), a new interrupt arriving between them would
overwrite R13 before the jump happened — the return address would be lost.
As a single instruction, `rti` sets `interrupts_enabled` and `PC` in the
same clock cycle.

```asm
; handler exit sequence
pop  R13        ; R13 = return address (was pushed by CPU on entry)
rti             ; enable interrupts and jump to R13
```

`rts` (return from subroutine) is encoded as `rti` with mode=1. It pops the
return address from the stack into R15 without touching the interrupt enable flag.
The `ret` macro expands to `rts`.

---

## Memory-Mapped Peripherals

Peripherals sit above the imm20 range (above `0x0FFFFF`) and always require
two instructions to reach:

```asm
mov-h  #0x400, R1     ; R1 = 0x400000 (UART)
mov    [R1], R0       ; read UART status
```

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
- R15 (PC) = 0x000000
- R14 (SP) = 0x0BFFFC  (top of SRAM — stack grows downward into SRAM)
- Interrupts disabled
- All other registers = 0
