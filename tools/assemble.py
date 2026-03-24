"""
M56 Assembler — CLI wrapper.

Usage:
    python3 tools/assemble.py input.asm              # hex dump to stdout
    python3 tools/assemble.py input.asm output.bin   # write binary
    python3 tools/assemble.py input.asm --load-addr 0x4000
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from assembler import assemble, AssemblerError
from m56 import USERRAM_START

import argparse

parser = argparse.ArgumentParser(description='M56 Assembler')
parser.add_argument('input',               help='assembly source file (.asm)')
parser.add_argument('output', nargs='?',   help='output binary (optional)')
parser.add_argument('--load-addr', default=hex(USERRAM_START),
                    help=f'load address (default: {hex(USERRAM_START)})')
args = parser.parse_args()

load_addr = int(args.load_addr, 0)

with open(args.input) as f:
    source = f.read()

try:
    code, labels, listing = assemble(source, load_addr)
except AssemblerError as e:
    print(f'error: {e}', file=sys.stderr)
    sys.exit(1)

print(f'{len(code)} bytes at {hex(load_addr)}')

if labels:
    for name, addr in sorted(labels.items(), key=lambda x: x[1]):
        print(f'  {name} = {hex(addr)}')

print()
for addr, data, line in listing:
    print(f'  {addr:05X}  {data.hex(" "):10}  {line}')

if args.output:
    with open(args.output, 'wb') as f:
        f.write(code)
    print(f'\nwritten to {args.output}')
