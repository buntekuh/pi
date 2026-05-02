{
  description = "Titania FPGA development environment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
      in {
        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            # Verilog simulation
            iverilog

            # VHDL simulation + synthesis frontend for yosys
            ghdl

            # Waveform viewer (works with both iverilog and GHDL output)
            gtkwave

            # Synthesis
            yosys

            # FPGA programming over USB/JTAG
            openFPGALoader
          ];

          # nextpnr-xilinx is not yet in nixpkgs — it must be installed
          # separately and its location passed via FPGA_TOOLS_DIR.
          shellHook = ''
            if [ -n "$FPGA_TOOLS_DIR" ]; then
              export PATH="$FPGA_TOOLS_DIR/bin:$PATH"
              export LD_LIBRARY_PATH="$FPGA_TOOLS_DIR/lib:$LD_LIBRARY_PATH"
              echo "nextpnr-xilinx toolchain loaded from $FPGA_TOOLS_DIR"
            else
              echo "Warning: FPGA_TOOLS_DIR not set — nextpnr-xilinx unavailable."
              echo "  Set it to the directory containing the custom toolchain."
            fi
            echo "Titania FPGA environment ready."
          '';
        };
      }
    );
}
