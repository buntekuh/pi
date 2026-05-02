# Development Environment

## Host Machine

- **OS:** Debian GNU/Linux 13 (trixie), x86_64
- **Reproducible environment:** see `flake.nix` in the learn-fpga repo root

## FPGA Board

**Digilent Cmod A7-35T** — XC7A35T-1CPG236C, 48-pin DIP form factor.
Connected via Micro-USB (powers the board, JTAG programming, and UART bridge
all on the same cable).

## Tools

| Tool | Purpose |
|---|---|
| yosys | Verilog synthesis |
| openfpgaloader | Flash bitstream to FPGA over USB/JTAG |
| iverilog | Verilog simulation |
| ghdl | VHDL simulation and synthesis frontend for yosys |
| gtkwave | Waveform viewer (works with iverilog and GHDL output) |
| nextpnr-xilinx | Place & route for Xilinx Artix-7 (custom install, see below) |

The first five are managed by Nix. nextpnr-xilinx is not yet in nixpkgs and
must be installed manually.

## Custom toolchain (nextpnr-xilinx / prjxray)

Installed at `/home/buntekuh/pi/fpga/femtorv32/tools/`. Provides:
- `nextpnr-xilinx` — place & route for Xilinx Artix-7
- `fasm2frames` — convert FASM to frame data
- `xc7frames2bit` — convert frames to bitstream

Required environment variables (add to `~/.bashrc`, or set via Nix shellHook):

```bash
export PRJXRAY_DB_DIR=<tools>/prjxray-extract/opt/nextpnr-xilinx/external/prjxray-db
export NEXTPNR_CHIPDB_DIR=<tools>/resources
export PATH="<tools>/bin:$PATH"
export LD_LIBRARY_PATH="<tools>/lib:$LD_LIBRARY_PATH"
```

Chipdb file: `$NEXTPNR_CHIPDB_DIR/xc7a35tcpg236-1.bin`

## Breadboard wiring

8 red LEDs via 1kΩ resistors to GND (DIP pin 25):

| Signal | DIP pin | FPGA package pin |
|---|---|---|
| LEDS[0] | onboard LD1 | A17 |
| LEDS[1] | onboard LD2 | C16 |
| LEDS[2] | 26 | R3 |
| LEDS[3] | 27 | T3 |
| LEDS[4] | 28 | R2 |
| LEDS[5] | 29 | T1 |
| LEDS[6] | 30 | T2 |
| LEDS[7] | 31 | U1 |
| GND | 25 | — |

## udev rules (non-NixOS only)

On NixOS, add `hardware.openFPGALoader.enable = true;` to your configuration.
On Debian/Ubuntu:

```bash
sudo tee /etc/udev/rules.d/99-digilent.rules <<'EOF'
ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6010", MODE="0666", GROUP="plugdev"
ATTRS{idVendor}=="1443", MODE="0666", GROUP="plugdev"
EOF
sudo udevadm control --reload-rules && sudo udevadm trigger
sudo usermod -aG plugdev $USER
```
