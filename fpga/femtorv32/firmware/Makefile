# Makefile — build RISC-V firmware for Titania / FemtoRV32
#
# Requires a RISC-V toolchain targeting rv32i.
# macOS:  brew tap riscv-software-src/riscv && brew install riscv-tools
# Ubuntu: sudo apt install gcc-riscv64-unknown-elf
#         (use riscv64-unknown-elf- prefix, -march=rv32i forces 32-bit)

PREFIX  = riscv64-unknown-elf-
AS      = $(PREFIX)as
LD      = $(PREFIX)ld
OBJCOPY = $(PREFIX)objcopy

ARCH = rv32i
ABI  = ilp32

all: firmware.hex

echo.o: echo.s
	$(AS) -march=$(ARCH) -mabi=$(ABI) -o $@ $<

echo.elf: echo.o
	$(LD) -m elf32lriscv -Ttext=0x00000000 -o $@ $<

echo.bin: echo.elf
	$(OBJCOPY) -O binary $< $@

firmware.hex: echo.bin
	python3 bin2hex.py $< > $@
	@echo "firmware.hex ready ($(shell wc -l < firmware.hex) words)"

clean:
	rm -f echo.o echo.elf echo.bin firmware.hex
