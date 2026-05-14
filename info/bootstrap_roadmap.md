# Titania Bootstrap Roadmap

The path from working M56 hardware to a self-hosted Titania-0 system.

## Phase 1 — Hardware complete

- SRAM controller (VHDL) — map the 512 KB on-board SRAM into the CPU address space
- Interrupt dispatch table in `io.s` — replace hardcoded handler with a
  writeable table of handler addresses (one per IRQ bit) at a known BRAM
  location; default entries point to a no-op; user programs install handlers
  by writing a function address into the appropriate slot; requires SRAM
  accessible so the table can live outside BRAM
- Quad-SPI Flash controller (VHDL) — read-only boot path; writable later for
  storing assembled programs
- SD card SPI driver (VHDL + assembly shim) — raw sector reads via PMOD
- Software multiply and divide (`_mul`, `_div`) in assembly
- Boot sequence in assembly — copy runtime image from Flash into SRAM, set up
  stack, jump to entry point

## Phase 2 — Test suite

- **Instruction test suite** — assembly program that exercises every opcode
  variant, addressing mode, edge case, and hardware path (BRAM, SRAM, UART,
  interrupt, stack) with known inputs; reports pass/fail over UART.
  Hardware must be fully wired before this is written so nothing is left untested.

## Phase 3 — Host tools

- **M56 emulator in Python** — must pass the instruction test suite exactly as
  hardware does; this is the development target so the board is not needed for
  every iteration
- **BCPL compiler in Python** — cross-compiles Titania-0 source to M56 object
  code; this is the bootstrap compiler that breaks the self-hosting chicken-and-egg

## Phase 4 — BCPL on M56

- **Runtime in BCPL** — stack frame layout, heap allocator over SRAM, I/O
  primitives wrapping the assembly shims
- **Assembler in BCPL** — two-pass assembler replacing `asm.py`; assembled and
  run on the emulator first, then on hardware
- **BCPL compiler in BCPL** — self-hosting Titania-0 compiler; Python bootstrap
  compiler can be retired once this passes its own test suite

## Phase 5 — Storage

- **Filesystem in BCPL** — simple FAT over SD card; one cartridge = one SD card
- Wire up the SD card reader end-to-end: VHDL SPI → assembly sector read →
  BCPL filesystem → Titania-0 file API

## Notes

- Steps 2 and 3 of phase 3 can be developed entirely on the emulator — no
  hardware flashing needed until phase 4.
- The Python BCPL compiler and Python assembler are bootstrap tools only; they
  are retired once BCPL is self-hosting.
- Assembly is reserved for: interrupt handlers, hardware initialisation, context
  switching, and any future performance-critical inner loops. Everything else
  lives in BCPL (Titania-0) or Titania-1.
- Once the BCPL compiler is self-hosting on M56, adding a RISC-V or ARM backend
  brings the entire software stack to that real hardware for free. RISC-V and ARM
  are hardware targets reached via compiler backends, not emulation.
