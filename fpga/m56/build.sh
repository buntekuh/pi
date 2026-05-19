#!/usr/bin/env bash
# build.sh — assemble firmware, synthesise M56, load to target board
#
# Prerequisites (nix shell from project root):
#   nix develop github:openxc7/toolchain-nix --extra-experimental-features 'nix-command flakes'
#
# Usage:
#   ./build.sh                    — build and run, cmod_a7, load to SRAM
#   ./build.sh -b                 — build only
#   ./build.sh -r                 — run only (load existing bitstream)
#   ./build.sh -br                — build and run (default)
#   ./build.sh -br cmod_a7        — build and run for a specific board
#   ./build.sh -br cmod_a7 flash  — build and write to flash (survives power cycle)
#   ./build.sh -p                 — patch only: asm → patch_fasm → bitstream (~5 s)
#   ./build.sh -pr                — patch and load to SRAM
#   ./build.sh -pr flash          — patch and write to flash

# Parse arguments — order does not matter
MODE="br"
BOARD="cmod_a7"
FLASH=""

for arg in "$@"; do
    case "$arg" in
        -b|-r|-br|-p|-pr) MODE="${arg#-}" ;;
        flash)     FLASH="flash" ;;
        *)         BOARD="$arg" ;;
    esac
done

PROJECT=titania
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TOOLS_DIR="${SCRIPT_DIR}/../toolchain"
DB_DIR="${TOOLS_DIR}/prjxray-db"
CHIPDB_DIR="${TOOLS_DIR}/resources"

# Load board-specific constants (PART, CHIPDB, LOADER_PART_FLASH, LOADER_PART_SRAM)
source board/${BOARD}.sh

# Read BLOCK_RAM_WORDS from the board VHDL package so firmware_pkg.vhd matches exactly
MEM_WORDS=$(grep -oP 'BLOCK_RAM_WORDS\s*:\s*integer\s*:=\s*\K[0-9]+' board/${BOARD}.vhd)

export PATH="${TOOLS_DIR}/bin:${PATH}"
export LD_LIBRARY_PATH="${TOOLS_DIR}/lib:${LD_LIBRARY_PATH}"

# --- SELinux ----------------------------------------------------------------
if command -v getenforce &>/dev/null && [ "$(getenforce)" = "Enforcing" ]; then
    echo "SELinux is enforcing — setting to permissive for Nix compatibility..."
    sudo setenforce 0
fi

# --- preflight checks -------------------------------------------------------
required=(python3)
case "${MODE}" in
    b|br)   required+=(ghdl yosys nextpnr-xilinx fasm2frames xc7frames2bit) ;;
    p|pr)   required+=(fasm2frames xc7frames2bit) ;;
esac
[[ "${MODE}" == *r* ]] && required+=(openFPGALoader)

missing=()
for cmd in "${required[@]}"; do
    command -v "$cmd" &>/dev/null || missing+=("$cmd")
done
if [ ${#missing[@]} -gt 0 ]; then
    echo "ERROR: missing required tools: ${missing[*]}" >&2
    echo "Run ../bin/install-toolchain.sh to set up the toolchain." >&2
    exit 1
fi

set -ex

# ── Fast patch mode ──────────────────────────────────────────────────────────
# Reassemble firmware and patch the existing titania.fasm in-place,
# then regenerate frames + bitstream.  Skips synthesis and place-and-route.
# Requires a titania.fasm from a prior full build.
if [ "${MODE}" = "p" ] || [ "${MODE}" = "pr" ]; then
    python3 tools/asm.py --mem-words ${MEM_WORDS} firmware/io.s firmware/firmware.hex
    python3 tools/patch_fasm.py ${PROJECT}.fasm firmware/firmware.hex
    fasm2frames --part ${PART} --db-root "${DB_DIR}/artix7" ${PROJECT}.fasm > ${PROJECT}.frames
    xc7frames2bit \
        --part_file "${DB_DIR}/artix7/${PART}/part.yaml" \
        --part_name ${PART} \
        --frm_file ${PROJECT}.frames \
        --output_file ${PROJECT}.bit
fi

if [ "${MODE}" = "pr" ]; then
    if [ "${FLASH}" = "flash" ]; then
        openFPGALoader --freq 30e6 -c digilent --fpga-part ${LOADER_PART_FLASH} -f ${PROJECT}.bit
    else
        openFPGALoader --freq 30e6 -c digilent --fpga-part ${LOADER_PART_SRAM} ${PROJECT}.bit
    fi
fi

# ── Full build ────────────────────────────────────────────────────────────────
if [ "${MODE}" = "b" ] || [ "${MODE}" = "br" ]; then

    # Step 1: assemble firmware → hex + VHDL init package
    python3 tools/asm.py --mem-words ${MEM_WORDS} firmware/io.s firmware/firmware.hex

    # Step 2: GHDL synthesises VHDL → Verilog
    ghdl synth --std=08 --out=verilog \
        board/${BOARD}.vhd \
        firmware/firmware_pkg.vhd \
        decoder.vhd \
        uart.vhd \
        interrupt.vhd \
        sram.vhd \
        spi.vhd \
        cpu.vhd \
        system.vhd \
        -e SOC > ${PROJECT}_ghdl.v

    # Step 3: yosys synthesises to Xilinx netlist
    yosys -p "read_verilog -sv ${PROJECT}_ghdl.v; \
              synth_xilinx -nowidelut -flatten -abc9 -arch xc7 -top SOC; \
              delete t:\$scopeinfo; write_json ${PROJECT}.json"

    # Step 4: place & route
    nextpnr-xilinx \
        --chipdb ${CHIPDB_DIR}/${CHIPDB} \
        --xdc board/${BOARD}.xdc \
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

fi

if [ "${MODE}" = "r" ] || [ "${MODE}" = "br" ]; then

    # Step 6: load to board
    if [ "${FLASH}" = "flash" ]; then
        # Write to flash — bitstream survives power cycle
        openFPGALoader --freq 30e6 -c digilent --fpga-part ${LOADER_PART_FLASH} -f ${PROJECT}.bit
    else
        # Load to SRAM — fast, but lost on power cycle
        openFPGALoader --freq 30e6 -c digilent --fpga-part ${LOADER_PART_SRAM} ${PROJECT}.bit
    fi

fi
