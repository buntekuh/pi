---
name: Project Titania
description: A complete fantasy computer system designed to be understood by one person, built by one person, and taught to anyone.
type: project
---

## Mission

Most computers are too complex to understand completely. Titania is not.

Niklaus Wirth spent his career arguing that a system a person cannot fully
understand is a system that person cannot fully trust. Titania honours that
conviction. From the flip-flop to the scripting language, every part of the
system is designed to fit in one sitting — not because it is limited, but
because simplicity is a design goal, not an afterthought.

Titania is a complete computer: RISC-V CPU on real FPGA hardware, OS,
languages, and tools, built from first principles. Every layer is visible,
every decision is documented, and nothing is a black box. A student can start
at any layer and follow the thread in either direction — down to the silicon
or up to the adventure game running on top.

The system is also a book. Not a textbook that must be read in order, but a
map: each chapter explains one layer of Titania, stands alone, and points
outward to deeper resources for the curious. The chapters connect because the
system connects.

## The book

| Chapter | Layer |
|---------|-------|
| 1 | Introduction |
| 2 | VHDL on the FPGA |
| 3 | RISC-V (RV32I) |
| 4 | The memory map |
| 5 | Titania-0 |
| 6 | The OS |
| 7 | Titania-1 |
| 8 | Puck |
| 9 | Titania-2 |
| 10 | A Grue adventure on real hardware |

## Stack

| Layer | Description |
|-------|-------------|
| RISC-V (RV32I) | 32-bit RISC CPU. Implementation: FemtoRV32 (~400 lines Verilog, educational by design) on Digilent Cmod A7-35T (Artix-7 FPGA). RV32I is a published open standard — 47 instructions, uniform encoding, the same ISA the industry is converging on. |
| Titania OS | Message-passing, simple scheduler, single interrupt level |
| Filesystem | Cartridge-based (custom FAT, 512KB), visible/writable flags, no permissions |
| T46 | Terminal: 640×368, 256-colour palette |
| Titania-0 | BCPL-inspired, typeless, everything is a 32-bit word. Simple enough that its compiler fits in an evening. Bootstraps Titania-1. Compiles to RISC-V. |
| Titania-1 | Adds types (INTEGER, CHAR, BYTE, structs, pointers). C without the regret. Used to write the OS, Puck, and Titania-2. Compiles to RISC-V. |
| Puck | Interactive fiction engine. Extensible in Titania-1 against a stable API. Named for Titania's companion in A Midsummer Night's Dream. |
| Titania-2 (Imp) | Interpreted, embeddable scripting language derived from Lox. Follows Crafting Interpreters (Bob Nystrom) through Part II — Functions, then diverges: no classes, no objects, no garbage collector. Closures, a string library, and the Puck embedding API replace the object system. |
| Grue | The language Puck adventure authors write in. A thin layer on top of Titania-2 with domain syntax for rooms, items, and actions. Authors write real code — conditions, logic, variables — not pseudo-English. Grue is honest about being a programming language. Named after the creature from Zork. |

## Bootstrapping path

```
RISC-V assembly → Titania-0 compiler → Titania-1 compiler → OS, Puck, Titania-2
```

Each step is built using only the layer below it. A student can follow the
entire chain from VHDL flip-flops to a Grue adventure running on hardware,
with no magic transitions and no black boxes.

## CPU: RISC-V RV32I on FemtoRV32

The CPU chapter is not about a fantasy ISA — it is about RISC-V, the same
instruction set the industry is converging on. RV32I has 47 instructions with
a uniform 32-bit encoding. The base integer ISA fits on one page.

The implementation is FemtoRV32 by Bruno Levy: ~400 lines of documented
Verilog, designed explicitly for teaching processor design. It fits on the
Cmod A7-35T with thousands of LUTs to spare. A reader who finishes chapter 3
understands the same ISA that is in their phone, their router, and
increasingly their laptop.

The book pitch: *"From RISC-V flip-flops to a working adventure game —
every layer visible, nothing a black box."*

## Hardware

- Board: Digilent Cmod A7-35T (Artix-7 FPGA, 33K LUTs)
- Clock: 12 MHz onboard oscillator; PLL multiplies to 50–75 MHz for CPU core
- UART: buart (J1 CPU, BSD-2), translated to VHDL, 115200 bps via FT2232HQ USB chip
- SRAM: 512KB on-board cellular RAM (19-bit address, 8-bit data)
- Storage: SD card via SPI (one cartridge = one SD card, or .cart file in emulator)

## Design rules

- Every layer must be understandable in one sitting. If it takes two, the design is wrong.
- No security model. No users. No permissions. Simplicity over safety theatre.
- Filesystem visible/writable flags are a first-class game mechanic.
- When naming things, use the Titania mythology.
- Grue authors write real code. Do not hide programming behind pseudo-English grammar (cf. Inform 7). The goal is to get people programming, not to abstract programming away.

**How to apply:** When designing a layer, ask "can this be explained in one chapter?" When naming things, use Titania. When tempted to add complexity, ask what Wirth would cut. When designing Grue syntax, expose the code — don't hide it.
