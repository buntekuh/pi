#!/usr/bin/env bash
# build.sh — synthesise Titania/FemtoRV32 and flash to Cmod A7-35T
#
# Prerequisites (in a nix shell):
#   nix develop github:openxc7/toolchain-nix --extra-experimental-features 'nix-command flakes'
#
# Usage:
#   ./build.sh          — build + flash to SRAM (lost on power cycle)
#   ./build.sh flash    — build + flash to FLASH (survives power cycle)

PROJECT=titania
PART=xc7a35tcpg236-1
DB_DIR=/usr/share/nextpnr/prjxray-db
CHIPDB_DIR=/usr/share/nextpnr/xilinx-chipdb
VERILOGS="femtorv32_quark.v buart.v top.v"

set -ex

# Step 1: firmware
make -C firmware

# Step 2: synthesise
yosys -p "synth_xilinx -nowidelut -flatten -abc9 -arch xc7 -top top; write_json ${PROJECT}.json" ${VERILOGS}

# Step 3: place & route
nextpnr-xilinx \
    --chipdb ${CHIPDB_DIR}/xc7a35tcpg236-1.bin \
    --xdc cmod_a7.xdc \
    --json ${PROJECT}.json \
    --write ${PROJECT}_routed.json \
    --fasm ${PROJECT}.fasm

# Step 4: bitstream
fasm2frames --part ${PART} --db-root ${DB_DIR}/artix7 ${PROJECT}.fasm > ${PROJECT}.frames
xc7frames2bit \
    --part_file ${DB_DIR}/artix7/${PART}/part.yaml \
    --part_name ${PART} \
    --frm_file ${PROJECT}.frames \
    --output_file ${PROJECT}.bit

# Step 5: flash
if [ "${1}" = "flash" ]; then
    openFPGALoader --freq 30e6 -c digilent --fpga-part xc7a35tcpg236 -f ${PROJECT}.bit
else
    openFPGALoader --freq 30e6 -c digilent --fpga-part xc7a35 ${PROJECT}.bit
fi
