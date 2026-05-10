# femtorv32 — Toolchain only

This directory contains the open-source Xilinx FPGA toolchain binaries
used to build the M56 / Titania design. It is not part of the M56 design
itself.

## Contents

- `bin/`   — installer scripts to fetch the toolchain on a new machine
- `tools/` — pre-built tool binaries (nextpnr-xilinx, fasm2frames, etc.)

## Acknowledgements

Many thanks to Bruno Levy, whose learn-fpga project and patient
documentation made it possible to get an open-source Xilinx toolchain
running at all. The path from VHDL to a working bitstream on an Artix-7
is not obvious, and his work has been of significant help.

And of course for the detailed tutorial on how to make a cpu come alive.

## Licence

The toolchain was obtained via the FemtoRV32 project by Bruno Levy:
  https://github.com/BrunaLevy/learn-fpga

Licensed under the BSD 3-Clause licence.

The underlying tools (nextpnr-xilinx, yosys, GHDL, prjxray) are each
individually open source. See their respective repositories for details.

## TODO

The following files are leftovers from an earlier FemtoRV32 experiment
and should be removed once confirmed no longer needed:

  buart.v
  build.sh
  cmod_a7.xdc
  femtorv32_quark.v
  firmware/
  titania.json
  top.v
