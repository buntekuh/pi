# board/cmod_a7.sh — Build system constants for the Digilent Cmod A7-35T
#
# Sourced by build.sh. To port to a new board, create a matching
# board/<name>.sh with these variables set appropriately.

# Full Xilinx part number — used by fasm2frames and xc7frames2bit
PART=xc7a35tcpg236-1

# Chip database for nextpnr-xilinx place & route
CHIPDB=xc7a35tcpg236-1.bin

# Part name passed to openFPGALoader when writing to flash
LOADER_PART_FLASH=xc7a35tcpg236

# Part name passed to openFPGALoader when loading to SRAM
LOADER_PART_SRAM=xc7a35
