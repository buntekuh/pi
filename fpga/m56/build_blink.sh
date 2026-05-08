#!/usr/bin/env bash
# build_blink.sh — synthesise blink.vhd (button→LED, UART loopback)
# No firmware, no CPU.  Use this to verify toolchain + board programming.

PROJECT=blink
PART=xc7a35tcpg236-1
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TOOLS_DIR="${SCRIPT_DIR}/../femtorv32/tools"
DB_DIR="${TOOLS_DIR}/prjxray-extract/opt/nextpnr-xilinx/external/prjxray-db"
CHIPDB_DIR="${SCRIPT_DIR}/../femtorv32/resources"

export PATH="${TOOLS_DIR}/bin:${PATH}"
export LD_LIBRARY_PATH="${TOOLS_DIR}/lib:${LD_LIBRARY_PATH}"

set -ex

ghdl synth --std=08 --out=verilog blink.vhd -e SOC > ${PROJECT}_ghdl.v

yosys -p "synth_xilinx -nowidelut -flatten -abc9 -arch xc7 -top SOC; \
          delete t:\$scopeinfo; write_json ${PROJECT}.json" \
      ${PROJECT}_ghdl.v

nextpnr-xilinx \
    --chipdb ${CHIPDB_DIR}/xc7a35tcpg236-1.bin \
    --xdc cmod_a7.xdc \
    --json ${PROJECT}.json \
    --write ${PROJECT}_routed.json \
    --fasm ${PROJECT}.fasm

fasm2frames --part ${PART} --db-root "${DB_DIR}/artix7" ${PROJECT}.fasm > ${PROJECT}.frames
xc7frames2bit \
    --part_file "${DB_DIR}/artix7/${PART}/part.yaml" \
    --part_name ${PART} \
    --frm_file ${PROJECT}.frames \
    --output_file ${PROJECT}.bit

openFPGALoader --freq 30e6 -c digilent --fpga-part xc7a35 ${PROJECT}.bit
