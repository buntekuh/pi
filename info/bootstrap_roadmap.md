# Titania Bootstrap Roadmap

The path from working M56 hardware to a self-hosted Titania-0 system.

## Phase 1 — Hardware complete

Memory map (finalised):
- `0x000000–0x03FFFF` BRAM 225 KB (bit 18=0) — system: kernel, runtime, filesystem
- `0x040000–0x0BFFFF` SRAM 512 KB (bit 18=1) — user: heap, stack
- `0x400000` UART (bit 22=1, above imm20 range, needs two instructions)

ISA (finalised):
- 32-bit instructions: `opcode(5) | mode(3) | register(4) | imm20(20)`
- 18 opcodes: mov mvb add sub and orr xor not shf sar bra bar cal car wfi eai dai rti
- jmp/jpr = goto (no return); bra/bar = subroutine call (pushes return address)
- Full 737 KB (BRAM + SRAM) directly addressable with imm20

Remaining steps:
1. ~~SRAM controller (VHDL)~~ — done
2. **Interrupt dispatch table in `io.s`** — writeable table of handler addresses
   at a known BRAM location; default entries point to a no-op.
   *Note: consider moving dispatch into hardware (interrupt controller in VHDL
   that fetches the handler address and jumps directly, bypassing the software
   table). Decision deferred until SD card IRQ pattern is known.*
3. **Software multiply and divide (`_mul`, `_div`)** in assembly — these are the
   M56 backend's implementation of the T-code `MUL` and `DIV` opcodes. The M56
   runtime library is linked into every M56 binary automatically; the T-code
   emitter never needs to know they are subroutines rather than single
   instructions.
4. **SD card SPI driver (VHDL + assembly shim)** — raw sector reads via PMOD

## Phase 1.5 — Refactor (after test suite)

- **`cpu.vhd` refactor** — split into `cpu/` subfolder with VHDL procedure
  packages (`types`, `mov`, `logic`, `arith`, `shift`, `branch`, `interrupt`);
  refactor only after the test suite exists so correctness can be verified.

## Phase 2 — Test suite

- **Instruction test suite** — assembly program that exercises every opcode
  variant, addressing mode, edge case, and hardware path (BRAM, SRAM, UART,
  interrupt, stack) with known inputs; reports pass/fail over UART.
  Hardware must be fully wired before this is written so nothing is left untested.

## Phase 2.5 — Clock speed characterisation

The Artix-7 35T contains an MMCM (Mixed-Mode Clock Manager) that can multiply
the 12 MHz on-board crystal in integer steps: 24, 36, 48, 60, 72 MHz and so on.
`CLOCK_FREQUENCY` in `board/cmod_a7.vhd` is the single point of truth; the UART
baud divider derives from it automatically.

Steps:
1. **Add MMCM to `system.vhd`** — instantiate the Artix-7 MMCM primitive, feed
   it the 12 MHz crystal, output a configurable multiple. Lock signal feeds a
   reset hold so the CPU stays in reset until the clock is stable.
2. **Expose a `CLOCK_MULT` constant** in `board/cmod_a7.vhd` — change one line
   to move between speed grades.
3. **Run the instruction test suite** (Phase 2) at each step — 24, 36, 48 MHz …
   until the suite reports failures or timing analysis fails in nextpnr.
4. **Record the maximum stable frequency** and lock `CLOCK_MULT` to the last
   passing value. Update `CLOCK_FREQUENCY` accordingly.

The ceiling is most likely the SRAM controller: the IS61WV5128BLL has a ~10 ns
access time, giving a theoretical 100 MHz cap. Real margin (setup, hold, routing)
puts the practical limit somewhere between 50 and 80 MHz.

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
