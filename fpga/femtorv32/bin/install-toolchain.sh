#!/usr/bin/env bash
# Prepares the openxc7 toolchain and enters the nix dev shell.
#
# Usage: ./bin/openxc7-toolchain.sh
#
# On first run:
#   - installs system packages (RISC-V toolchain, python3)
#   - copies nix-provided binaries into tools/bin/
# Subsequent runs skip steps that are already done.

set -e

# --- system packages --------------------------------------------------------

pkgs=()
command -v riscv64-unknown-elf-as &>/dev/null || pkgs+=(gcc-riscv64-unknown-elf)
command -v python3                &>/dev/null || pkgs+=(python3)

if [ ${#pkgs[@]} -gt 0 ]; then
    echo "Installing (apt): ${pkgs[*]}"
    sudo apt install -y "${pkgs[@]}"
fi

# --- nix check --------------------------------------------------------------

if ! command -v nix &>/dev/null; then
    echo "nix is not installed. Install it from https://nixos.org/download and re-run." >&2
    exit 1
fi

# --- nix dev shell + binary copy --------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BIN_DIR="${SCRIPT_DIR}/tools/bin"

exec nix develop github:openxc7/toolchain-nix \
    --extra-experimental-features 'nix-command flakes' \
    --command bash -c "
        for pair in nextpnr-xilinx:nextpnr-xilinx-bin bbasm:bbasm xc7frames2bit:xc7frames2bit python3.8:python3.8; do
            src=\${pair%%:*}; dst=\${pair##*:}
            dest=\"${BIN_DIR}/\${dst}\"
            if [ ! -f \"\$dest\" ]; then
                echo \"Copying \$src -> tools/bin/\$dst\"
                cp \"\$(which \"\$src\")\" \"\$dest\" && chmod +x \"\$dest\"
            fi
        done
        exec bash
    "
