# M56 CPU

The M56 is a 32-bit RISC CPU. Instructions are 32 bits wide. All registers are
32-bit. The physica address space covers 1 MB (imm20 range), mapped as follows:

---

## Registers

16 general-purpose registers, all 32-bit. Two have a fixed role by hardware; the rest are convention:

| Name   | Alias | Notes |
|--------|-------|-------|
| R0–R2  |       | Scratch registers                                |
| R3     |       | Leaf return address (by convention)              |
| R4–R12 |       | General purpose                                  |
| R13    |       | Written with irq_status word by hardware on interrupt entry; read by `rti` as return address after handler restores it from the stack |
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

### Byte access

| Region      | Word read (`mov`) | Word write (`mov`) | Byte read (`mvb`) | Byte write (`mvb`) |
|-------------|:-----------------:|:------------------:|:-----------------:|:------------------:|
| BRAM        | ✓                 | ✓                  | ✗ (hardware bug)  | ✗ (hardware bug)   |
| SRAM        | ✓                 | ✓                  | ✓                 | ✓                  |
| Peripherals | ✓                 | ✓                  | —                 | ✓                  |

`mvb` byte reads from BRAM are broken in synthesized hardware — the BRAM returns
a full word and the byte lane extraction does not work correctly after place and
route. Workaround: use word reads and mask with `and R, #0xFF`.

Byte reads and writes to SRAM work correctly. The SRAM controller performs a
single-byte transfer when `cpu_is_byte` is set, and the CPU extracts the result
from bits 7:0 of the read data. Packed byte strings therefore belong in SRAM,
not BRAM.

### Kernel Call Table

The BRAM exposes a stable jump table at a known address. Programs call these
fixed addresses — the implementation behind them may change, but the addresses
never move.

```
0x001000   mul       bra  mul_impl    ; software multiply
0x001004   div       bra  div_impl    ; software divide
0x001008   mod       bra  mod_impl    ; software modulo
0x00100C   _print    bra  print_impl  ; print null-terminated string — Rsrc = pointer
0x001010   _printnum bra  printnum_impl ; print integer to UART — Rsrc = value
...
```

---

## Instruction Format

Every instruction is exactly **32 bits**, 4-byte aligned in memory.

```
Bit  31..27   opcode    (5 bits)   — 32 possible opcodes, 20 defined
Bit  26..24   mode      (3 bits)   — addressing mode (modes 0–6 used; 7 reserved)
Bit  23..20   register  (4 bits)   — one explicit register
Bit  19..0    imm20    (20 bits)   — immediate, offset, or second register
```

The `mode` field means the same thing across all instructions that take a source
operand: Move, MoveB, ALU, and shift instructions share modes 0–6. The 20-bit
field carries exactly what each mode needs. It is never split arbitrarily.

---

## Opcodes

20 hardware opcodes. Above them: T-code pseudo-opcodes (portable across all Titania targets) and M56-only assembler macros.

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
| 8    | shf      | Logica shift — signed count, positive=left, negative=right |
| 9    | sar      | Arithmetic shift right — sign bit replicated |
| 10   | bra      | Conditional absolute branch — goto, no return address saved |
| 11   | bar      | Conditional relative branch — goto, PC-relative offset |
| 12   | cal      | Conditional absolute call — subroutine call, saves return address |
| 13   | car      | Conditional relative call — subroutine call, PC-relative |
| 14   | wfi      | Wait for interrupt — suspends execution until an interrupt fires |
| 15   | eai      | Enable interrupts |
| 16   | dai      | Disable interrupts |
| 17   | rti      | Return from interrupt — enable interrupts and jump to R13 |
| 18   | iba     | Conditional indirect goto — jump to address in register |
| 19   | ica     | Conditional indirect call — push return address, jump to register |

Opcodes 20–31 are reserved for future use.

**branch** (`bra`, `bar`) transfers control without saving anything — a goto.
**call** (`cal`, `car`) saves the return address on the stack before jumping —
a subroutine call. The difference is in the opcode, not a mode bit.
**indirect** (`iba`, `ica`) — same semantics as bra/cal but the target address comes from a register rather than an immediate. Used for function pointers and virtual dispatch.

### T-code Pseudo-Opcodes

T-code is Titania's portable instruction set. M56 machine code forms its base;
the pseudo-opcodes below extend it with operations that exist on every target
but have different low-level realisations. On M56 the assembler expands them
to the appropriate sequence; a RISC-V or ARM backend emits native equivalents.

| Mnemonic | Encoding                          | Description |
|----------|-----------------------------------|-------------|
| `mul`    | mul \| mode \| Rdst \| imm20      | Multiply |
| `div`    | div \| mode \| Rdst \| imm20      | Divide |
| `mod`    | mod \| mode \| Rdst \| imm20      | Modulo |
| `shf`    | shf \| mode \| Rdst \| imm20      | Shift (mode 0: logica, mode 1: arithmetic right) |
| `stk`    | stk \| mode \| Rreg \| 0          | Stack (mode 0: push, mode 1: pop) |
| `ret`    | ret \| mode \| 0 \| 0             | Return (mode 0: from subroutine, mode 1: from interrupt) |
| `hal`    | hal \| mode \| Rdst \| id(6)+imm(12) | Hardware abstraction call |

**mul/div/mod mode field** — bit 1: operand type (0=immediate, 1=register); bit 0: signedness (0=signed, 1=unsigned).

**shf** subsumes `sar` and the `shl`/`shr` macros. On M56: mode 0 → `shf`, mode 1 → `sar`.

**hal** — top 6 bits of imm20 are the hardware function ID (0–63); low 12 bits are an inline immediate. Arguments pass in R0–R2 per the calling convention.

**On M56**: mul/div/mod → `cal` to ROM subroutine; stk → push/pop sequence; ret mode 0 → `rts`, ret mode 1 → `rti`.

### M56 Assembler Macros

Expand to real M56 instructions. No T-code presence.

```
bra    label          →  bra.al  label
bar    label          →  bar.al  label
cal    label          →  cal.al  label
car    label          →  car.al  label
nop                   →  add R0, #0
clr Rdst              →  xor Rdst, Rdst
inc Rdst              →  add Rdst, #1
dec Rdst              →  sub Rdst, #1
shl Rsrc, #n          →  shf Rsrc, #n
shr Rsrc, #n          →  shf Rsrc, #-n
```

### ROM Subroutines

Called by the M56 T-code backend for pseudo-opcodes that have no single hardware instruction:

```
mul       software multiply    — shift-and-add
div       software divide      — shift-and-subtract
mod       software modulo
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

Multiply, divide, and modulo are T-code pseudo-opcodes. On M56 they expand to
`cal` to a ROM subroutine.

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

### shf — Logica Shift
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

Six opcodes for control flow transfer:

| Opcode | Mnemonic | Addressing | Return address |
|--------|----------|------------|----------------|
| 10 | `bra` | absolute (imm20) | not saved — goto |
| 11 | `bar` | relative (PC + imm20) | not saved — goto |
| 12 | `cal` | absolute (imm20) | pushed on stack — call |
| 13 | `car` | relative (PC + imm20) | pushed on stack — call |
| 18 | `iba` | register (Rtarget) | not saved — indirect goto |
| 19 | `ica` | register (Rtarget) | pushed on stack — indirect call |

Direct encoding: `opcode(5) | cond(3) | Rcmp(4) | address/offset(20)`

Indirect encoding: `opcode(5) | cond(3) | Rcmp(4) | Rtarget(4) | 0(16)`

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
bra      label           ; absolute goto, unconditional
bra.z    Rcmp, label     ; absolute goto if Rcmp == 0
bra.nz   Rcmp, label     ; absolute goto if Rcmp != 0
bra.n    Rcmp, label     ; absolute goto if Rcmp < 0
bra.nn   Rcmp, label     ; absolute goto if Rcmp >= 0

bar      label           ; relative goto, unconditional
bar.z    Rcmp, label     ; relative goto if Rcmp == 0

cal      label           ; absolute call, unconditional
cal.nz   Rcmp, label     ; absolute call if Rcmp != 0

car      label           ; relative call, unconditional
car.z    Rcmp, label     ; relative call if Rcmp == 0
```

```asm
iba      Rtarget         ; indirect goto, unconditional
iba.z    Rcmp, Rtarget   ; indirect goto if Rcmp == 0

ica      Rtarget         ; indirect call, unconditional
ica.nz   Rcmp, Rtarget   ; indirect call if Rcmp != 0
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
4. Interrupts are disabled automaticaly
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
The T-code `ret` pseudo-opcode (mode 0) expands to `rts` on M56; `ret` mode 1
(return from interrupt) expands to `rti`.

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
