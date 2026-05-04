# M56 CPU

> **Open questions — resolve before implementation:**
> 1. **Instruction encoding** — bit field layout is not fully specified for all instruction classes. `mov`/ALU, `jmp`/`cal`/`ret`, unary (`not`, `shl`, `shr`, `sar`), and no-operand instructions (`eai`, `dai`, `hlt`, `rti`) each need a complete and consistent encoding table.
> 2. **`jmp` offset field** — currently shown as 19 bits but the condition (3 bits) + register (4 bits) fields leave 20 bits, not 19. Needs resolving.
> 3. **`mov-h` bit placement** — exactly which bits of `dest` does the 19-bit immediate map to? Needs a precise definition.
> 4. **Memory map** — ROM size unknown; peripheral I/O region address is provisional (marked in the peripherals section).
> 5. **Calling convention** — register usage for arguments and return values not yet defined.

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
0x0000100C   _print    jmp  print_impl  ; print string to UART — R1 = pointer to null-terminated string
0x00001010   _printnum jmp  printnum_impl ; print integer to UART — R1 = value
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
operand: Move, MoveB, and all ALU instructions share modes 0–2. The 19-bit field
carries exactly what each mode needs. It is never split arbitrarily.

---

## Opcodes

15 real opcodes. Everything else is an assembler macro or a ROM subroutine.

All mnemonics are exactly three lowercase letters.

| Code | Mnemonic | Description |
|------|----------|-------------|
| 0    | mov      | 32-bit word load, store, and register-to-register |
| 1    | mvb      | Byte load or store |
| 2    | add      | Add |
| 3    | sub      | Subtract |
| 4    | and      | Bitwise AND |
| 5    | orr      | Bitwise OR |
| 6    | xor      | Bitwise XOR |
| 7    | not      | Bitwise NOT (unary) |
| 8    | shl      | Logical shift left |
| 9    | shr      | Logical shift right |
| 10   | sar      | Arithmetic shift right (sign-preserving) |
| 11   | jmp      | Conditional jump — compare register against zero, branch to PC+offset |
| 12   | hlt      | Halt CPU |
| 13   | eai      | Enable interrupts |
| 14   | dai      | Disable interrupts |

Opcodes 15–31 are reserved for future use.

### Assembler Macros

Conveniences that expand to real instructions. Not in hardware.

```
psh src          →  sub SP, #4 ; mov src, [SP]
pop dest         →  mov [SP], dest ; add SP, #4
cal label        →  psh R15 ; jmp label
ret              →  pop R15
rti              →  pop R15 ; eai
nop              →  add R0, #0
clr dest         →  xor dest, dest
inc dest         →  add dest, #1
dec dest         →  sub dest, #1
mul dest, src    →  psh R15 ; jmp _mul
div dest, src    →  psh R15 ; jmp _div
```

### ROM Subroutines

Complex operations implemented once in ROM, called by convention:

```
_mul      software multiply    — shift-and-add
_div      software divide      — shift-and-subtract
_mod      software modulo
_print    print null-terminated string to UART — R1 = string pointer
_printnum print integer as decimal to UART    — R1 = value
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
mov #imm19, dest
```
Load 19-bit immediate into dest, sign-extended to 32 bits. Range: -262144 to +262143.
```
opcode | mode=0 | dest | (imm19)
```

### Mode 1 — Move High Immediate
```
mov-h #imm19, dest
```
Load 19-bit immediate into the upper bits of dest (bits 31..13), zeroing the lower 13 bits.
Combined with mode 0, any 32-bit constant can be loaded in two instructions:
```asm
mov-h  #0x7FFFF, R0    ; R0 = 0xFFFFE000
mov    #0x1FFF,  R0    ; R0 = 0xFFFFFFFF
```
```
opcode | mode=1 | dest | (imm19)
```

### Mode 2 — Register to Register
```
mov src, dest
```
Copy src into dest.
```
opcode | mode=2 | src | (dest)
```

### Mode 3 — Indirect Read
```
mov [src], dest
```
Read 32-bit word at address in src into dest.
```
opcode | mode=3 | src | (dest)
```

### Mode 4 — Indirect Write
```
mov src, [dest]
```
Write src to address held in dest.
```
opcode | mode=4 | src | (dest)
```

### Mode 5 — Indexed Read
```
mov [src+off], dest
```
Read 32-bit word at (src + off) into dest.
```
opcode | mode=5 | src | (dest[18:15], offset[14:0])
```

### Mode 6 — Indexed Write
```
mov src, [dest+off]
```
Write src to (dest + off).
```
opcode | mode=6 | src | (dest[18..15], offset[14..0])
```

Modes 7–15 are reserved for future use.

MoveB uses the same mode encoding as Move. Modes 3 and 5 read a byte
(zero-extended). Modes 4 and 6 write the low byte of the register.

---

## ALU Instructions

Add, Sub, And, Orr, Xor use the same `mode` field as Move to select the source
operand. The `register` field is always the destination (and left-hand operand).
Only modes 0, 1 and 2 are valid — the ALU never accesses memory directly.

| Mode | Source operand                   |
|------|----------------------------------|
| 0    | 19-bit immediate (sign-extended) |
| 1    | 19-bit high immediate            |
| 2    | register                         |

Result written to the register field.

```
add  dest, #imm19      →  dest = dest + sign_extend(imm19)
add  dest, src         →  dest = dest + src
```

(sub, and, orr, xor follow the same pattern.)

Multiply and divide are ROM subroutines, not hardware opcodes. The assembler
macros `mul` and `div` expand to `cal _mul` and `cal _div`.

---

## Unary Instructions

### not
```
not dest    →  dest = ~dest
```

### shl — Logical Shift Left
```
shl dest, #n
```
Shift dest left by n bits. Bits [4:0] of the 19-bit field hold the shift count.

### shr — Logical Shift Right
```
shr dest, #n
```
Shift dest right by n bits, zero-filling from the left.

### sar — Arithmetic Shift Right
```
sar dest, #n
```
Shift dest right by n bits, sign bit (bit 31) replicated.

---

## Jump

`jmp` is the only branch opcode. Plain `jmp` is unconditional; with a suffix it tests a register against zero. The offset is signed and PC-relative — the assembler calculates it from the label.

### Condition Codes

| Code | Suffix | Condition |
|------|--------|-----------|
| 0    | .z     | Register equals zero |
| 1    | .nz    | Register not equal to zero |
| 2    | .n     | Register bit 31 set (negative) |
| 3    | .nn    | Register bit 31 clear (non-negative) |

```asm
jmp    label        ; unconditional
jmp.z  R1, label    ; jump if R1 == 0
jmp.nz R1, label    ; jump if R1 != 0
jmp.n  R1, label    ; jump if R1 < 0  (signed)
jmp.nn R1, label    ; jump if R1 >= 0 (signed)
```

For computed jumps (function pointers, dispatch tables), write directly to R15:
```asm
mov  R1, R15        ; jump to address in R1
```

---

## Interrupts

The M56 has a single interrupt line and single priority level.

Interrupts are enabled and disabled with dedicated opcodes:
```
eai    ; enable interrupts
dai    ; disable interrupts
```

When an interrupt fires and interrupts are enabled:
1. The current instruction completes
2. PC is pushed onto the stack
3. Interrupts are disabled automatically
4. PC jumps to the interrupt vector at `0x00000010`

Return from interrupt is via the `rti` opcode: pops PC and re-enables interrupts.

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
