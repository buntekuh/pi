#!/usr/bin/env bash
# build.sh — assemble firmware, synthesise M56, flash to Cmod A7-35T
#
# Prerequisites (nix shell from project root):
#   nix develop github:openxc7/toolchain-nix --extra-experimental-features 'nix-command flakes'
#
# Usage:
#   ./build.sh          — build + load to SRAM (lost on power cycle)
#   ./build.sh flash    — build + write to flash (survives power cycle)

PROJECT=titania
PART=xc7a35tcpg236-1
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TOOLS_DIR="${SCRIPT_DIR}/../femtorv32/tools"
DB_DIR="${TOOLS_DIR}/prjxray-extract/opt/nextpnr-xilinx/external/prjxray-db"
CHIPDB_DIR="${SCRIPT_DIR}/../femtorv32/resources"

export PATH="${TOOLS_DIR}/bin:${PATH}"
export LD_LIBRARY_PATH="${TOOLS_DIR}/lib:${LD_LIBRARY_PATH}"

set -ex

# Step 1: assemble firmware → hex + VHDL init package
python3 tools/asm.py firmware/echo.s firmware/firmware.hex

# Step 2: GHDL synthesises VHDL → Verilog
ghdl synth --std=08 --out=verilog \
    firmware/firmware_pkg.vhd \
    decoder.vhd \
    buart.vhd \
    cpu.vhd \
    top.vhd \
    -e SOC > ${PROJECT}_ghdl.v

# Step 3: yosys synthesises to Xilinx netlist
yosys -p "synth_xilinx -nowidelut -flatten -abc9 -arch xc7 -top SOC; \
          delete t:\$scopeinfo; write_json ${PROJECT}.json" \
      ${PROJECT}_ghdl.v

# Step 4: place & route
nextpnr-xilinx \
    --chipdb ${CHIPDB_DIR}/xc7a35tcpg236-1.bin \
    --xdc cmod_a7.xdc \
    --json ${PROJECT}.json \
    --write ${PROJECT}_routed.json \
    --fasm ${PROJECT}.fasm

# Step 5: bitstream
fasm2frames --part ${PART} --db-root "${DB_DIR}/artix7" ${PROJECT}.fasm > ${PROJECT}.frames
xc7frames2bit \
    --part_file "${DB_DIR}/artix7/${PART}/part.yaml" \
    --part_name ${PART} \
    --frm_file ${PROJECT}.frames \
    --output_file ${PROJECT}.bit

# Step 6: flash
if [ "${1}" = "flash" ]; then
    openFPGALoader --freq 30e6 -c digilent --fpga-part xc7a35tcpg236 -f ${PROJECT}.bit
else
    openFPGALoader --freq 30e6 -c digilent --fpga-part xc7a35 ${PROJECT}.bit
fi
