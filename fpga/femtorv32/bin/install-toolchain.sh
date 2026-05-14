#!/usr/bin/env bash
# Prepares the openxc7 toolchain and enters the nix dev shell.
#
# Usage: ./bin/install-toolchain.sh
#
# On first run:
#   - detects apt (Debian/Ubuntu) or dnf (Fedora/RHEL)
#   - installs system packages (RISC-V toolchain, python3)
#   - installs Nix if not present
#   - copies nix-provided binaries into tools/bin/
# Subsequent runs skip steps that are already done.

set -e

# --- SELinux ----------------------------------------------------------------
if command -v getenforce &>/dev/null && [ "$(getenforce)" = "Enforcing" ]; then
    echo "SELinux is enforcing — setting to permissive for Nix compatibility..."
    sudo setenforce 0
fi

# --- detect package manager -------------------------------------------------

if command -v apt &>/dev/null; then
    PKG_MANAGER="apt"
    RISCV_PKG="gcc-riscv64-unknown-elf"
    RISCV_CMD="riscv64-unknown-elf-as"
elif command -v dnf &>/dev/null; then
    PKG_MANAGER="dnf"
    # Fedora ships the Linux-target cross compiler; bare-metal (unknown-elf) is
    # not in the standard repos.  The binary is riscv64-linux-gnu-as.
    RISCV_PKG="gcc-riscv64-linux-gnu"
    RISCV_CMD="riscv64-linux-gnu-as"
else
    echo "Neither apt nor dnf found. Please install system packages manually." >&2
    exit 1
fi

# --- system packages --------------------------------------------------------

pkgs=()
command -v "$RISCV_CMD"  &>/dev/null || pkgs+=("$RISCV_PKG")
command -v python3        &>/dev/null || pkgs+=(python3)
command -v ghdl           &>/dev/null || pkgs+=(ghdl)
command -v yosys          &>/dev/null || pkgs+=(yosys)

if [ ${#pkgs[@]} -gt 0 ]; then
    echo "Installing ($PKG_MANAGER): ${pkgs[*]}"
    sudo "$PKG_MANAGER" install -y "${pkgs[@]}"
fi

# --- python packages --------------------------------------------------------
pip3 install --user --quiet \
    fasm \
    simplejson \
    intervaltree \
    numpy \
    progressbar2 \
    pyjson5 \
    pyyaml

# --- install nix if missing -------------------------------------------------

if ! command -v nix &>/dev/null; then
    echo "Nix not found — installing via the official multi-user installer..."
    curl -L https://nixos.org/nix/install | sh -s -- --daemon
    # Source nix into the current session so we can continue without a new shell
    if [ -f /etc/profile.d/nix.sh ]; then
        # shellcheck source=/dev/null
        . /etc/profile.d/nix.sh
    elif [ -f "$HOME/.nix-profile/etc/profile.d/nix.sh" ]; then
        # shellcheck source=/dev/null
        . "$HOME/.nix-profile/etc/profile.d/nix.sh"
    else
        echo "Nix installed but profile not found. Please open a new shell and re-run." >&2
        exit 1
    fi
fi

# --- nix dev shell + binary copy --------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BIN_DIR="${SCRIPT_DIR}/tools/bin"

mkdir -p "${BIN_DIR}"

exec nix develop github:openxc7/toolchain-nix \
    --extra-experimental-features 'nix-command flakes' \
    --command bash -c "
        for pair in nextpnr-xilinx:nextpnr-xilinx-bin bbasm:bbasm xc7frames2bit:xc7frames2bit python3.8:python3.8 openFPGALoader:openFPGALoader; do
            src=\${pair%%:*}; dst=\${pair##*:}
            dest=\"${BIN_DIR}/\${dst}\"
            if [ ! -f \"\$dest\" ]; then
                src_path=\"\$(which \"\$src\" 2>/dev/null || true)\"
                if [ -z \"\$src_path\" ]; then
                    echo \"WARNING: \$src not found in Nix shell, skipping\"
                    continue
                fi
                echo \"Copying \$src -> tools/bin/\$dst\"
                cp \"\$src_path\" \"\$dest\" && chmod +x \"\$dest\"
            fi
        done
        # --- prjxray Python package ---------------------------------------------
        PRJXRAY_DEST=\"${SCRIPT_DIR}/tools/prjxray-snap/opt/prjxray/prjxray\"
        if [ ! -d \"\$PRJXRAY_DEST\" ]; then
            PRJXRAY_SRC=\$(python3 -c \"import prjxray, os; print(os.path.dirname(prjxray.__file__))\" 2>/dev/null || true)
            if [ -n \"\$PRJXRAY_SRC\" ]; then
                echo \"Copying prjxray Python package -> tools/prjxray-snap/opt/prjxray/\"
                cp -r \"\$PRJXRAY_SRC\" \"\$PRJXRAY_DEST\"
            else
                echo \"WARNING: prjxray Python package not found in Nix shell\"
            fi
        fi
        # --- prjxray database ---------------------------------------------------
        # Copy the full Nix prjxray-db to a stable local path. The prjxray-extract
        # database is an older format incompatible with the prjxray Python package
        # from Nix; using the Nix db ensures the versions match.
        NIX_PRJXRAY_DB_ROOT=\$(find /nix/store -path \"*/share/nextpnr/external/prjxray-db\" -type d 2>/dev/null | head -1)
        LOCAL_PRJXRAY_DB=\"${SCRIPT_DIR}/tools/prjxray-db\"
        if [ -n \"\$NIX_PRJXRAY_DB_ROOT\" ] && [ ! -d \"\$LOCAL_PRJXRAY_DB\" ]; then
            echo \"Copying prjxray-db from Nix store...\"
            cp -r \"\$NIX_PRJXRAY_DB_ROOT\" \"\$LOCAL_PRJXRAY_DB\"
        fi
        # --- chipdb -------------------------------------------------------------
        RESOURCES_DIR=\"${SCRIPT_DIR}/resources\"
        mkdir -p \"\$RESOURCES_DIR\"
        BBAEXPORT=\$(find /nix/store -name \"bbaexport.py\" -path \"*/share/nextpnr/*\" 2>/dev/null | head -1)
        if [ -z \"\$BBAEXPORT\" ]; then
            echo \"WARNING: bbaexport.py not found in Nix store, skipping chipdb generation\"
        else
            NEXTPNR_DATA=\$(dirname \$(dirname \"\$BBAEXPORT\"))
            for part in xc7a35tcpg236-1 xc7a35tcsg324-1; do
                dest=\"\$RESOURCES_DIR/\${part}.bin\"
                if [ ! -f \"\$dest\" ]; then
                    echo \"Generating chipdb \${part}.bin ...\"
                    python3 \"\$BBAEXPORT\" \
                        --device \"\$part\" \
                        --xray \"\$NEXTPNR_DATA/external/prjxray-db/artix7\" \
                        --metadata \"\$NEXTPNR_DATA/external/nextpnr-xilinx-meta/artix7\" \
                        --bba /tmp/\${part}.bba &&
                    bbasm --le --files /tmp/\${part}.bba \"\$dest\" &&
                    rm /tmp/\${part}.bba
                fi
            done
        fi

        echo 'Install completed successfully. Please start a new session to ensure the toolchain is available.'
    "
