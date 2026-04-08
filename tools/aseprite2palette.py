"""
aseprite2palette.py — regenerate palette.py from tools/palette.aseprite.

Usage:
    python tools/aseprite2palette.py

Reads the palette chunk from the .aseprite file and writes palette.py.
Supports both the new (0x2019) and old (0x0004) palette chunk formats.
Color names defined in Aseprite appear as inline comments.
Run this whenever colours are added or changed in Aseprite.
"""

import struct
import sys
from pathlib import Path

ROOT       = Path(__file__).parent.parent
ASE_PATH   = Path(__file__).parent / "palette.aseprite"
PAL_PATH   = ROOT / "palette.py"


def read_palette(path):
    """
    Parse an .aseprite file and return a list of (index, r, g, b, name_or_None).
    """
    data = path.read_bytes()

    magic = struct.unpack_from('<H', data, 4)[0]
    if magic != 0xA5E0:
        sys.exit(f"not a valid .aseprite file (magic {magic:#06x})")

    colours = {}   # index → (r, g, b, name)

    # Walk chunks in frame 1 (starts at byte 128)
    off = 128
    frame_bytes = struct.unpack_from('<I', data, off)[0]
    n_chunks    = struct.unpack_from('<H', data, off + 8)[0]
    # newer format stores chunk count in a DWORD at offset 12
    n_chunks_ex = struct.unpack_from('<I', data, off + 12)[0]
    if n_chunks_ex:
        n_chunks = n_chunks_ex
    off += 16

    for _ in range(n_chunks):
        chunk_size, chunk_type = struct.unpack_from('<IH', data, off)

        if chunk_type == 0x2019:            # new palette chunk
            pal_size, first, last = struct.unpack_from('<III', data, off + 6)
            p = off + 6 + 4 + 4 + 4 + 8   # skip size, first, last, 8 reserved
            for idx in range(first, last + 1):
                flags, r, g, b, a = struct.unpack_from('<HBBBB', data, p)
                p += 6
                name = None
                if flags & 1:
                    slen = struct.unpack_from('<H', data, p)[0]; p += 2
                    name = data[p:p + slen].decode('utf-8', errors='replace'); p += slen
                colours[idx] = (r, g, b, name)

        elif chunk_type == 0x0004:          # old palette chunk
            p = off + 6
            n_packets = struct.unpack_from('<H', data, p)[0]; p += 2
            idx = 0
            for _ in range(n_packets):
                skip  = struct.unpack_from('<B', data, p)[0]; p += 1
                count = struct.unpack_from('<B', data, p)[0]; p += 1
                if count == 0:
                    count = 256
                idx += skip
                for _ in range(count):
                    r, g, b = struct.unpack_from('<BBB', data, p); p += 3
                    colours[idx] = (r, g, b, None)
                    idx += 1

        off += chunk_size

    if not colours:
        sys.exit("no palette chunk found in .aseprite file")

    max_idx = max(colours)
    return [(colours.get(i, (0, 0, 0, None))) for i in range(max_idx + 1)]


def write_palette(colours, path):
    lines = [
        '"""',
        'T46 colour palette — generated from tools/palette.aseprite.',
        '',
        'Do not edit by hand.  Add or change colours in Aseprite, then run:',
        '    python tools/aseprite2palette.py',
        '"""',
        '',
        '# fmt: off',
        '_HEX = [',
    ]

    for i, (r, g, b, name) in enumerate(colours):
        hex_val = f'"{r:02X}{g:02X}{b:02X}"'
        comment = f'  # {i:3d}  {name}' if name else f'  # {i:3d}'
        lines.append(f'    {hex_val},{comment}')

    lines += [
        ']',
        '# fmt: on',
        '',
        '',
        'def _parse(h):',
        '    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))',
        '',
        '',
        '_defined   = [_parse(h) for h in _HEX]',
        '_padding   = [(0, 0, 0)] * (256 - len(_defined))',
        '',
        '# PALETTE_DATA: list of 256 (R, G, B) tuples — the single source of truth',
        'PALETTE_DATA = _defined + _padding',
        '',
        '# Raw bytes for pygame set_palette()',
        'PALETTE_BYTES = bytes(b for rgb in PALETTE_DATA for b in rgb)',
        '',
    ]

    path.write_text('\n'.join(lines))
    print(f"wrote {path}  ({len(colours)} colours)")


if __name__ == '__main__':
    colours = read_palette(ASE_PATH)
    write_palette(colours, PAL_PATH)
