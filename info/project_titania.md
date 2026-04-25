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


Titania is a complete fantasy computer: CPU, OS, languages, and tools, built
from first principles on real FPGA hardware. Every layer is visible, every
decision is documented, and nothing is a black box. A student can start at any
layer and follow the thread in either direction — down to the silicon or up to
the adventure game running on top.

The system is also a book. Not a textbook that must be read in order, but a
map: each chapter explains one layer of Titania, stands alone, and points
outward to deeper resources for the curious. The chapters connect because the
system connects.

## The book

Titania is also a book. Not a textbook that must be read in order, but a map:
each chapter explains one layer, stands alone, and points outward to deeper
resources for the curious. Each language chapter exists because the previous
layer had a pain point it could not solve.

| Chapter | Layer |
|---------|-------|
| 1 | Introduction |
| 2 | VHDL on the FPGA |
| 3 | The M56 CPU |
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
| M56 | 32-bit RISC CPU on Digilent Cmod A7-35T (Artix-7 FPGA) |
| Titania OS | Message-passing, simple scheduler, single interrupt level |
| Filesystem | Tree of nodes, visible/writable flags, no permissions |
| T46 | Terminal: 640×368, 256-colour palette |
| Titania-0 | BCPL-inspired, typeless, everything is a 32-bit word. Simple enough that its compiler fits in an evening. Bootstraps Titania-1. |
| Titania-1 | Adds types (INTEGER, CHAR, BYTE, structs, pointers). C without the regret. Used to write the OS, Puck, and Titania-2. |
| Puck | Interactive fiction engine. Extensible in Titania-1 against a stable API. Named for Titania's companion in A Midsummer Night's Dream. |
| Titania-2 (Imp) | Interpreted, embeddable scripting language derived from Lox. Follows Crafting Interpreters (Bob Nystrom) through Part II — Functions, then diverges: no classes, no objects, no garbage collector. Closures, a string library, and the Puck embedding API replace the object system. Lives inside Puck as the event handler and extension layer. |
| Grue | The language Puck adventure authors write in. Readable by non-programmers. Powered by Titania-2 underneath. |

## Bootstrapping path

```
M56 assembly → Titania-0 compiler → Titania-1 compiler → OS, Puck, Titania-2
```

Each step is built using only the layer below it. A student can follow the
entire chain from VHDL flip-flops to a Grue adventure running on hardware,
with no magic transitions and no black boxes.

## Design rules

- Every layer must be understandable in one sitting. If it takes two, the design is wrong.
- No security model. No users. No permissions. Simplicity over safety theatre.
- Filesystem visible/writable flags are a first-class game mechanic.
- When naming things, use the Titania mythology.

**How to apply:** When designing a layer, ask "can this be explained in one chapter?" When naming things, use Titania. When tempted to add complexity, ask what Wirth would cut.
