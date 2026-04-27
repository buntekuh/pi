#!/usr/bin/env python3
"""Convert a raw binary to the hex format Vivado's $readmemh expects.
One 32-bit little-endian word per line.
Usage: python3 bin2hex.py echo.bin > firmware.hex
"""
import sys

data = open(sys.argv[1], 'rb').read()
# Pad to 4-byte boundary
while len(data) % 4:
    data += b'\x00'

for i in range(0, len(data), 4):
    word = int.from_bytes(data[i:i+4], 'little')
    print(f'{word:08x}')
