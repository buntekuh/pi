# T-code

T-code is Titania's intermediate representation — the equivalent of Pascal's
P-code. Every compiler layer emits T-code; one backend per hardware target
reads the token stream and emits native machine code. Adding a target means
writing one backend. Every language in the stack is immediately portable.

```
Titania-0 source ──┐
Titania-1 source ──┼──► T-code token stream ──► M56 backend   ──► M56
Titania-2 source ──┘                        ├──► rv32i backend ──► rv32i
                                             └──► ARM backend   ──► ARM
```

---

## Design philosophy

T-code is M56 assembly with the minimum abstraction needed to target all three
platforms cleanly. The M56 is the simplest of the three targets; T-code starts
there and adds only what is necessary to keep the rv32i and ARM backends honest.

T-code is not a general-purpose IR designed for optimisation or to exhaust the
capabilities of any target processor. It covers exactly the operations a student
needs to understand computation. Simplicity is the specification.

---

## Targets

| Target | Hardware |
|--------|----------|
| M56 | Titania FPGA (Cmod A7) |
| M56 emu | Software M56 — no board needed |
| rv32i | RISC-V 32-bit integer hardware |
| ARM | Raspberry Pi and similar |

---

## Types

T-code has two types.

| Type | Width |
|------|-------|
| word | 32 bits |
| byte | 8 bits |

No floating point. The stack — kernel, filesystem, text adventure engine,
scripting — works entirely in integers and addresses. If fractional arithmetic
is ever needed, a fixed-point convention (e.g. Q16.16: top 16 bits integer,
bottom 16 bits fraction) costs nothing and requires no new T-code operations.

---

## Operations

### Registers

T-code uses virtual registers. The backend performs register allocation for the
target. The M56 has 16 general-purpose registers; rv32i has 32; ARM has 16.
Virtual registers remove this difference from the T-code layer entirely.

### Load and store

```
LOADIMM  reg, value        // load a constant into a register
LOADW    reg, [addr]       // load word from address
STOREW   [addr], reg       // store word to address
LOADB    reg, [addr]       // load byte from address
STOREB   [addr], reg       // store byte to address
```

`LOADIMM` is abstract — the backend emits however many instructions the target
needs to materialise a 32-bit constant (one instruction on M56 for values that
fit imm20; two instructions otherwise).

### Arithmetic and logic

```
ADD  dst, a, b
SUB  dst, a, b
AND  dst, a, b
ORR  dst, a, b
XOR  dst, a, b
NOT  dst, a
SHL  dst, a, count         // shift left
SHR  dst, a, count         // shift right logical
SAR  dst, a, count         // shift right arithmetic
MUL  dst, a, b
DIV  dst, a, b
```

`MUL` and `DIV` are T-code opcodes. On M56 the backend emits `cal _mul` /
`cal _div` and links the software routines automatically — the T-code emitter
never needs to know they are subroutines rather than single instructions. On
rv32i (M extension) and ARM the backend emits hardware multiply/divide.

### Branch and call

All branch and call opcodes take an optional condition suffix.

| Opcode | Meaning | Conditions |
|--------|---------|------------|
| `BRA` | branch absolute | none `.z .nz .n .nn` |
| `BAR` | branch relative | none `.z .nz .n .nn` |
| `CAL` | call absolute | none `.z .nz .n .nn` |
| `CAR` | call relative | none `.z .nz .n .nn` |
| `RET` | return | none `.z .nz .n .nn` |

`CAR` (relative call) makes libraries position-independent. `RET` is abstract;
backends emit the appropriate return sequence for the target. `RTI` (return from
interrupt) is a separate opcode with no conditions.

### Interrupt control

```
ENABLE_INTERRUPTS
DISABLE_INTERRUPTS
WAIT_INTERRUPT
RTI                        // return from interrupt handler
```

These map to target-specific instructions. No inline assembly is permitted in
T-code; these keywords are the only mechanism for interrupt control.

---

## What T-code does not have

- **Floating point** — no use case in the Titania stack
- **Unsigned comparison** — the four signed conditions cover what the stack needs
- **SIMD or vector operations** — not in the teaching scope
- **Memory model or ordering** — single-core only; no concurrency primitives
- **Type checking** — T-code carries type information (word/byte) for load/store
  width only; it does not enforce types across operations

---

## The abstraction layer over M56

The delta between M56 assembly and T-code is deliberately small:

| M56-specific | T-code abstraction |
|---|---|
| Physical registers R0–R15 | Virtual registers — backend allocates |
| `imm20` encoding | `LOADIMM` — backend emits 1 or 2 instructions |
| `mov-h` two-instruction constant load | Folded into `LOADIMM` |
| `eai dai wfi rti` | `ENABLE_INTERRUPTS DISABLE_INTERRUPTS WAIT_INTERRUPT RTI` |
| Hardware `mul`/`div` absent | `MUL`/`DIV` — M56 backend links `_mul`/`_div` |

The M56 backend is nearly a one-to-one transcription. The rv32i and ARM backends
translate a small, well-understood vocabulary rather than a rich abstract machine.

---

## Status

T-code is not yet fully specified. The opcode set above captures design
decisions made during the hardware phase. The complete specification —
including the binary token encoding, register conventions, and calling
convention — will be written once the M56 hardware phase is complete and the
full set of operations the machine needs to express is known.
