# M56 CPU

The M56 is a 32-bit RISC CPU. Instructions are 32 bits wide. All registers are
32-bit. The physical address space is 512 KB of SRAM — the full 32-bit address
range is wired to that, with addresses above 0x0007FFFF unmapped.

---

## Registers

16 general-purpose registers, all 32-bit. Two have a fixed role by convention:

| Name   | Alias | Notes |
|--------|-------|-------|
| R0     |       | Conventional zero / scratch |
| R1–R13 |       | General purpose |
| R14    | SP    | Stack pointer. Stack grows downward. |
| R15    | PC    | Program counter. Advances by 4 after each fetch. |

Writing to R15 redirects execution immediately. Reading R15 returns the address
of the instruction after the one currently executing (PC has already advanced).
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
0x00001000–0x0001FFFF   ROM — OS, assembler, Pi interpreter
0x00020000–0x0007FFFF   RAM — heap and stack (stack grows down from 0x0007FFFC)
```

---

## Instruction Format

Every instruction is exactly **32 bits**, 4-byte aligned in memory.

```
Bit  31..27   opcode  (5 bits)   — 32 possible opcodes, 20 defined
Bit  26..23   src     (4 bits)   — source register, mode selector, or condition code
Bit  22..19   dest    (4 bits)   — destination register
Bit  18..0    imm19   (19 bits)  — immediate, offset, or packed register reference
```

19-bit signed immediate covers ±256 KB — enough to reach any address in the
512 KB physical space from any other in a single relative jump.

The `src` field is not always a register number. For Load it encodes the
addressing mode. For Jump, Call, and Ret it encodes the condition code.

---

## Opcodes

| Code | Mnemonic | Description |
|------|----------|-------------|
| 0    | Load     | 32-bit word read or write, multiple addressing modes |
| 1    | LoadB    | Byte read — load one byte into register (zero-extended) |
| 2    | StoreB   | Byte write — store low byte of register to memory |
| 3    | Add      | Add |
| 4    | Sub      | Subtract |
| 5    | And      | Bitwise AND |
| 6    | Or       | Bitwise OR |
| 7    | Xor      | Bitwise XOR |
| 8    | Not      | Bitwise NOT (unary) |
| 9    | Shift    | Logical shift left or right |
| 10   | ShiftA   | Arithmetic shift right (sign-preserving) |
| 11   | Swap     | Swap high and low 16-bit halves of register |
| 12   | Mul      | Multiply (lower 32 bits of result) |
| 13   | Jump     | Conditional jump |
| 14   | Call     | Conditional call — pushes return address, jumps |
| 15   | Ret      | Conditional return — pops return address |
| 16   | Rti      | Return from interrupt — pops PC and FLAGS |
| 17   | Halt     | Halt CPU |
| 18   | Out      | Write register to I/O port |
| 19   | In       | Read I/O port into register (blocking) |

Opcodes 20–31 are reserved for future use.

### Assembler Macros

The following are assembler conveniences, not real opcodes:

```
Push dest     →  Sub R14, #4 ; Load dest, [R14]
Pop  dest     →  Load [R14], dest ; Add R14, #4
Nop         →  Add R0, #0
Mov dest, src  →  Load src, dest
Clr dest      →  Xor dest, dest
Inc dest      →  Add dest, #1
Dec dest      →  Sub dest, #1
EI          →  Or FLAGS, #0x10
DI          →  And FLAGS, #~0x10
```

---

## Load — Addressing Modes

The `src` field selects the mode. `dest` is the destination for reads, or the
value register for writes. Source registers are packed into the low bits of
`imm19`.

### Mode 0 — Immediate
```
Load #imm19, dest
```
Load 19-bit unsigned immediate into dest, zero-extended to 32 bits.

### Mode 1 — Register to Register
```
Load src, dest
```
Copy src into dest.
```
imm19[3:0] = src number
```

### Mode 2 — Indirect Read
```
Load [src], dest
```
Read 32-bit word at address in src into dest.
```
imm19[3:0] = src number
```

### Mode 3 — Indirect Write
```
Load dest, [src]
```
Write dest to address in src.
```
imm19[3:0] = src number
```

### Mode 4 — Indexed Read
```
Load [src+off], dest
```
Read 32-bit word at (src + off) into dest.
```
imm19[18:15] = src number
imm19[14:0]  = unsigned offset (0–32,767)
```

### Mode 5 — Indexed Write
```
Load dest, [src+off]
```
Write dest to (src + off).
```
imm19[18:15] = src number
imm19[14:0]  = unsigned offset (0–32,767)
```

### Mode 6 — PC-Relative Read
```
Load [PC+off], dest
```
Read 32-bit word at (current PC + imm19). PC has already advanced past the
instruction, so offset 0 reads the word immediately following.
```
imm19 = unsigned byte offset
```

---

## ALU Instructions

Add, Sub, And, Or, Xor, Mul share the same encoding. Bit 18 of `imm19`
selects register or immediate mode.

```
imm19 bit 18 = 0 → source is register src (src field)
imm19 bit 18 = 1 → source is imm19[17:0] (18-bit unsigned immediate)
```

Result written to dest. FLAGS updated after every ALU operation.

```
Add  dest, src      →  dest = dest + src
Add  dest, #imm18  →  dest = dest + imm18
Sub  dest, src      →  dest = dest - src
And  dest, src      →  dest = dest & src
Or   dest, src      →  dest = dest | src
Xor  dest, src      →  dest = dest ^ src
Mul  dest, src      →  dest = (dest * src)[31:0]   (C set if result exceeds 32 bits)
```

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
`imm19[4:0]` is a 5-bit signed shift count.
- Positive → shift left
- Negative (bit 4 set) → logical shift right

### ShiftA — Arithmetic Shift Right
```
ShiftA dest, #n
```
Right shift by `imm19[4:0]` bits, sign bit (bit 31) replicated.

### Swap
```
Swap dest    →  dest = ((dest & 0xFFFF) << 16) | (dest >> 16)
```
Swaps high and low 16-bit halves.

---

## Control Flow

Jump, Call, and Ret use `src` as a condition code. They execute only when the
condition is true.

### Condition Codes

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

### Jump
```
Jump.cond offset    ; PC += signed imm19 (in bytes)
Jump.cond dest        ; PC = dest  (dest field non-zero selects register)
```

### Call
```
Call.cond offset    ; Push PC, then PC += signed imm19
Call.cond dest        ; Push PC, then PC = dest
```
Pushes the return address (next instruction) before jumping.

### Ret
```
Ret.cond            ; PC = Pop()
```

---

## Interrupts

The M56 has a single interrupt line and single priority level.

When an interrupt fires and IE (FLAGS bit 4) is set:
1. The current instruction completes
2. FLAGS is pushed onto the stack
3. PC is pushed onto the stack
4. IE is cleared (interrupts disabled for the duration of the handler)
5. PC jumps to the interrupt vector at `0x00000010`

### Rti — Return from Interrupt
```
Rti    ; PC = Pop() ; FLAGS = Pop()
```
Restores both PC and FLAGS, re-enabling interrupts if IE was set before.

---

## Byte Access

### LoadB
```
LoadB [src], dest     ; dest = zero-extended byte at address src
LoadB [src+off], dest ; dest = zero-extended byte at (src + off)
```
Uses the same mode encoding as Load modes 2 and 4.

### StoreB
```
StoreB dest, [src]     ; mem[src] = dest[7:0]
StoreB dest, [src+off] ; mem[src+off] = dest[7:0]
```
Uses the same mode encoding as Load modes 3 and 5.

---

## I/O

Ports are 8-bit numbers. The I/O bus connects the CPU to the terminal and
storage. All I/O is synchronous; In blocks until data is available.

### Out
```
Out #port, src    ; write src to port
```

### In
```
In dest, #port     ; read port into dest (blocking)
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
