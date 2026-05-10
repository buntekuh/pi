# M56 FPGA Hardware Reference

## Hardware Philosophy

The M56 is a mainframe, not a microcontroller. It does not need to interface
with the Arduino ecosystem or run real-time control loops. It needs three
things:

- A terminal to talk to a human
- Mass storage to hold programs and worlds
- A way to connect to other M56 machines

All three are satisfied with nothing more exotic than UART and SPI in the FPGA
fabric. No USB host stack. No complex bridge chips. No proprietary protocols.


## HDL Language: VHDL

The M56 hardware is written in VHDL rather than Verilog. VHDL is more verbose
but explicit and unambiguous — every signal, type, and transition is declared
clearly. Verilog's terseness, inherited from C, introduces implicit behaviours
that can hide bugs and reduce readability.

This is consistent with the project's philosophy: a curious person should be
able to read the CPU source and understand what it does. VHDL's structure
supports that goal. Vivado supports VHDL fully under the free WebPACK licence.

VHDL was modelled on Ada, itself designed for correctness and clarity above all
else.


## FPGA Board: Digilent Cmod A7-35T

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

The M56 CPU core uses roughly 2,000–4,000 LUTs. Headroom is ample.

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


## Peripherals

| Function                         | Module                       | Interface | Approx. cost |
|----------------------------------|------------------------------|-----------|--------------|
| Terminal to PC                   | Onboard USB-UART (J17/J18)   | UART      | included     |
| Mass storage                     | PMOD SD card reader (6-pin)  | SPI       | ~€7.50       |
| Inter-machine / classic terminal | PMOD RS-232 (6-pin)          | UART      | ~€2.50       |

Only two hardware blocks are needed beyond the CPU core itself:

- **SPI master** — drives the SD card over the DIP-pin PMOD
- **UART** — one instance for USB-UART terminal, one for RS-232 networking


## Memory Map

The onboard SRAM (512 KB) provides more than enough space for the M56's
address space. The Quad-SPI Flash holds the bitstream and the OS/ROM image,
loaded automatically at power-on.

Current Block RAM allocation (in FPGA, before SRAM is wired up):

| Address bit 22 | Range                 | Device     |
|----------------|-----------------------|------------|
| 0              | 0x000000 – 0x3FFFFF   | Block RAM  |
| 1              | 0x400000              | UART       |


## Storage

SD card over SPI. The filesystem is a custom, simplified format optimised for
the M56 and its use cases. FAT compatibility with external machines is not a
goal; the M56 owns its storage and is the only system that needs to read it.


## Networking

RS-232 point-to-point between M56 machines, or to a classic terminal. Simple,
proven, and requires nothing in the FPGA fabric beyond the UART block already
present for the terminal connection.

### The Fantasy Network

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
