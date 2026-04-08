# The M56 FPGA Computer

## Manifesto

The M56 is a learning device. The idea of the M56 is to have a computer that is so simple, that every single aspect can easily be understood. At the same time it evades the stumbling blocks and pitfalls of early computers that had to work around limited resources.

The M56 opts to be limited in scope. It is not a high power workhorse. In essence it is a toy of a computer. The limitation exists in order to simplify the machine.

The M56 is a computer simple enough that every layer can be held in your head
at once From the logic gates in the FPGA fabric to the CPU instruction
set. From the ultra simple operating system to the type-safe Forth based programming language Pi the OS and all the tools are implemented in. From an interactive fiction
interpreter, all the way up to the text adventure worlds a user creates and
plays.

No layer is a mystery. No component requires a specialist to
comprehend. A curious person with time can trace a
command typed at a terminal to the electrons that execute it and back again.

The computer system uses a mainframe <-> terminal set up. The terminal, called T46 edits text and displays graphics. The terminal is implemented in Python. The graphics system, the display, the keyboard all these are not part of the M56 computer. They are excluded and are not what is being taught. What remains is a computer with an ultra simple 16 bit Risc processor, a very simple filesystem, single priority interrupts, extremely basic i/o and limited RAM. It can connect to the T46 terminal, a sd card reader and network with other M56 computers.

This simplicity is not a limitation. It is the point.

## Inspirations

### The PDP-8

A machine so constrained it seems almost a joke by modern
standards, yet beloved for generations because its constraints made it
completely knowable. You could understand a PDP-8. Both C and Unix were invented on a PDP.

### Andrew Tanenbaum

Who built MINIX not to be the fastest or the most capable Unix, but to be the one you could learn from and teach whole generations of students.
Tanenbaum was criticised for choosing clarity over performance. He was right to make
that choice as a teacher, and the M56 makes the same choices.

### Crown Jewels

#### The Grue text adventuring system

The Grue text adventuring system is a very simple but extensible text adventure runtime. It invites the user to play and tinker, make worlds come alive with a few simple words and extend the existing system with extensions written in Pi.

#### Pi
The pi dialect of Forth was developed to make it easier to be used by modern developers.

While it is an interpreted language it is extremely near to how computers operate. This makes it an ideal language to run an OS on, in a language that is easily understood by those who are willing to think the way a machine does.

#### The Risc CPU

The Risc CPU is implemented with a tiny set of opcodes that make it Turing complete, yet extremely easy to understand. Mission critical parts of the OS like the Forth interpreter are implemented in assembly.

## The Stack

From bottom to top, each layer open source and comprehensible on its own terms:

1. **FPGA fabric** — SPI master, UART, and the CPU core in VHDL
2. **M56 CPU** — 16-bit, 21 opcodes, fixed 24-bit instructions, port-based I/O
3. **Pi** — a type-safe implementation of Forth, used to implement the OS and
   tools
4. **Operating system** — a Forth-based kernel, small enough to read in an
   afternoon
5. **IF interpreter** — the Grue engine, a language for building interactive
   worlds
6. **The worlds** — text adventures written in Grue by anyone who has climbed
   the layers below


## Hardware Philosophy

The M56 is a mainframe, not a microcontroller. It does not need to interface
with the Arduino ecosystem or run real-time control loops. It needs three
things:

- A terminal to talk to a human
- Mass storage to hold programs and worlds
- A way to connect to other M56 machines

All three are satisfied with nothing more exotic than UART and SPI in the FPGA
fabric. No USB host stack. No complex bridge chips. No proprietary protocols.


## Hardware Specification

### HDL Language: VHDL

The M56 hardware will be written in VHDL rather than Verilog. VHDL is more
verbose but explicit and unambiguous — every signal, type, and transition is
declared clearly. Verilog's terseness, inherited from C, introduces implicit
behaviours that can hide bugs and reduce readability.

This is consistent with the project's philosophy: a curious person should be
able to read the CPU source and understand what it does. VHDL's structure
supports that goal. Vivado supports VHDL fully under the free WebPACK licence.

VHDL was modelled on Ada, itself designed for correctness and clarity above all
else. Good company.

### FPGA Board: Digilent Cmod A7-35T

A tiny 48-pin DIP form factor board (0.7" × 2.75") built around a Xilinx
Artix-7 35T FPGA. Supported under the free Vivado WebPACK licence — no cost
beyond the board itself.

The similar Cmod S7 (Spartan-7) was considered and rejected: it lacks onboard
SRAM (requiring an external chip) and has only 32 DIP pins vs 44. At €10 less
it is not worth the trade-off.

**FPGA (XC7A35T-1CPG236C)**

| Resource         | Amount  |
|------------------|---------|
| LUTs             | 20,800  |
| Flip-Flops       | 41,600  |
| Block RAM        | 225 KB  |
| Clock tiles      | 5       |
| DSP slices       | 90      |

The M56 CPU core will use roughly 2,000–4,000 LUTs. Headroom is ample.

**Onboard peripherals**

| Resource             | Details                                               |
|----------------------|-------------------------------------------------------|
| SRAM                 | 512 KB, 8-bit bus, 8 ns access (IS61WV5128BLL)        |
| Quad-SPI Flash       | 4 MB — bitstream uses ~2 MB, leaving ~2 MB for ROM    |
| USB-UART bridge      | FTDI FT2232HQ on FPGA pins J17/J18, via Micro-USB     |
| USB-JTAG             | Same Micro-USB connector, independent of UART         |
| PMOD connector       | One standard 2×6, 8 digital I/O, 3.3 V, 200 Ω series |
| DIP connector        | 44 digital I/O + 2 analog inputs, 100-mil spacing     |
| LEDs                 | 2 user LEDs, 1 RGB LED                                |
| Buttons              | 2 push buttons                                        |

**Single PMOD, two modules**

The board has one PMOD connector (2×6, 12 pins). Digilent makes a 6-pin SD
card reader that uses only one row, leaving the other row free. The RS-232
PMOD is also 6-pin. Both modules plug into the same connector simultaneously —
one on each row — so no second PMOD adapter or hand-wiring is needed at all.

### Peripherals

| Function                         | Module                       | Interface | Approx. cost |
|----------------------------------|------------------------------|-----------|--------------|
| Terminal to PC                   | Onboard USB-UART (J17/J18)   | UART      | included     |
| Mass storage                     | PMOD SD card reader (6-pin)  | SPI       | ~€7.50       |
| Inter-machine / classic terminal | PMOD RS-232 (6-pin)          | UART      | ~€2.50       |

### FPGA Fabric Blocks

Only two hardware blocks are needed beyond the CPU core itself:

- **SPI master** — drives the SD card over the DIP-pin PMOD
- **UART** — one instance for USB-UART terminal, one for RS-232 networking

### Memory Map

The onboard SRAM (512 KB) provides more than enough space for the M56's 20-bit
address space. The Quad-SPI Flash holds the bitstream and the OS/ROM image,
loaded automatically at power-on.

### Storage

SD card over SPI. The filesystem is a custom, simplified format optimised for
the M56 and its use cases. FAT compatibility with external machines is not a
goal; the M56 owns its storage and is the only system that needs to read it.

### Networking

RS-232 point-to-point between M56 machines, or to a classic terminal. Simple,
proven, and requires nothing in the FPGA fabric beyond the UART block already
present for the terminal connection.

#### The Fantasy Network

The M56 simulates a network of machines using the filesystem. A fantasy network
address (e.g. `connect 345-t45`) maps to a directory on the SD card, making
that directory the accessible root for the session — its own home, its own
cartridges, its own history. `disconnect` returns to the local machine.

On real hardware, the same convention applies. The RS-232 port can also connect
to a genuinely remote M56 machine, using the same protocol. The user experience
is identical either way — the fantasy network and the real network are
indistinguishable.

The address naming convention is creative territory: it can encode geography,
era, faction, or anything the fiction demands. A Grue game can hand the player
off to another machine at its conclusion. Combined with the cartridge unlock
mechanic, completing a world on one machine can reveal addresses of others,
drawing the player deeper into the network.


## What This Is Not

- It is not a general-purpose computer trying to run Linux.
- It is not optimised for speed or throughput.
- It is not designed to interface with the modern PC ecosystem beyond a
  terminal window.
- It is not a microcontroller.

It is a teaching machine with a text adventure system as its crown jewel, open
to anyone who wants to look inside, and it is enough.
