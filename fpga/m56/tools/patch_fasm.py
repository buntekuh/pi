#!/usr/bin/env python3
"""
patch_fasm.py — patch BRAM INIT lines in a Titania .fasm file with new firmware.

Replaces the RAMB18 INIT data for the program memory block without
re-running synthesis, place-and-route, or bitstream assembly from scratch.
Only fasm2frames + xc7frames2bit need to re-run (~5 s instead of ~10 min).

Usage:
    python3 tools/patch_fasm.py titania.fasm firmware/firmware.hex
        — patch titania.fasm in-place

    python3 tools/patch_fasm.py --verify titania.fasm firmware/firmware.hex
        — verify that the FASM already matches the hex (run after a full build
          to confirm the tile ordering assumption is correct)

Artix-7 RAMB36 INIT mapping (one RAMB36 = two RAMB18 halves Y0 and Y1):
    RAMB18_Y0  holds bits [15: 0] of each 32-bit word
    RAMB18_Y1  holds bits [31:16] of each 32-bit word
    Each INIT register is 256 bits = 16 words × 16 bits per half
    64 INIT registers (INIT_00..INIT_3F) × 16 words = 1024 words per RAMB36

Multiple RAMB36 tiles are sorted by Y coordinate (ascending), so the tile with
the lowest Y holds firmware words 0..1023, the next tile 1024..2047, and so on.
Run --verify after a full build to confirm this ordering for your placement.
"""

import re
import sys

# Matches both hex (256'h + 64 hex chars) and binary (256'b + 256 bits) INIT lines.
INIT_RE = re.compile(
    r'^(\S+)\.(RAMB18_Y\d)\.INIT_([0-9A-Fa-f]{2})\[255:0\]\s*=\s*256\'([bh])([0-9A-Fa-f]{64}|[01]{256})$',
    re.MULTILINE
)

WORDS_PER_TILE = 1024  # each RAMB36 holds 1024 32-bit words


def tile_sort_key(name):
    """Extract (Y, X) from a tile name like 'BRAM_L_X6Y40' for sort ordering."""
    m = re.search(r'X(\d+)Y(\d+)', name)
    return (int(m.group(2)), int(m.group(1))) if m else (0, 0)


def parse_fasm_inits(fasm_text):
    """
    Scan the FASM and collect all RAMB18 INIT lines.

    Returns a list of (tile_name, y0_inits, y1_inits) sorted by tile Y coordinate
    (ascending), where y0/y1_inits are dicts { init_idx(int): hex_string_64_chars }.
    """
    tiles = {}
    for line in fasm_text.splitlines():
        m = INIT_RE.match(line.strip())
        if not m:
            continue
        tile, half, idx_hex, fmt, data = m.groups()
        if fmt == 'b':
            data = f'{int(data, 2):064X}'
        idx = int(idx_hex, 16)
        if tile not in tiles:
            tiles[tile] = {'y0': {}, 'y1': {}}
        if half == 'RAMB18_Y0':
            tiles[tile]['y0'][idx] = data
        else:
            tiles[tile]['y1'][idx] = data
    if not tiles:
        raise ValueError("No RAMB18 INIT lines found in FASM — is this the right file?")
    return [
        (name, d['y0'], d['y1'])
        for name, d in sorted(tiles.items(), key=lambda x: tile_sort_key(x[0]), reverse=True)
    ]


def words_to_inits(words, tile_names):
    """
    Distribute firmware words across tiles (WORDS_PER_TILE words each).

    Returns dict { (tile_name, half, init_idx): hex_string_64_chars }.
    Y0 holds bits[15:0], Y1 holds bits[31:16] of each word.
    Words are packed LSB-first within each 256-bit INIT register.
    """
    result = {}
    for tile_idx, tile_name in enumerate(tile_names):
        base = tile_idx * WORDS_PER_TILE
        tile_words = list(words[base : base + WORDS_PER_TILE])
        tile_words += [0] * (WORDS_PER_TILE - len(tile_words))
        for init_idx in range(64):
            for half, shift in (('RAMB18_Y0', 0), ('RAMB18_Y1', 16)):
                val = 0
                for word_in_block in range(15, -1, -1):
                    bits = (tile_words[init_idx * 16 + word_in_block] >> shift) & 0xFFFF
                    val = (val << 16) | bits
                result[(tile_name, half, init_idx)] = f'{val:064X}'
    return result


def inits_to_words(tiles):
    """
    Reconstruct 32-bit words from a parsed tile list.

    tiles: list of (tile_name, y0_dict, y1_dict) in address order.
    """
    words = []
    for _, y0, y1 in tiles:
        for init_idx in range(64):
            h0 = int(y0.get(init_idx, '0' * 64), 16)
            h1 = int(y1.get(init_idx, '0' * 64), 16)
            for word_in_block in range(16):
                shift = word_in_block * 16
                lo = (h0 >> shift) & 0xFFFF
                hi = (h1 >> shift) & 0xFFFF
                words.append((hi << 16) | lo)
    return words


def patch(fasm_text, new_words):
    """Replace all BRAM INIT lines in fasm_text with data from new_words."""
    tiles = parse_fasm_inits(fasm_text)
    tile_names = [name for name, _, _ in tiles]
    new_inits = words_to_inits(new_words, tile_names)

    def replace_line(m):
        tile, half, idx_hex, _fmt, _ = m.groups()
        idx = int(idx_hex, 16)
        new_data = new_inits.get((tile, half, idx), '0' * 64)
        bin_str = f'{int(new_data, 16):0256b}'
        return f"{tile}.{half}.INIT_{idx_hex.upper()}[255:0] = 256'b{bin_str}"

    return INIT_RE.sub(replace_line, fasm_text)


def verify(fasm_text, expected_words):
    """
    Check that the FASM INIT data matches expected_words.
    Prints a summary and returns True if they match, False otherwise.
    """
    tiles = parse_fasm_inits(fasm_text)
    tile_names = [name for name, _, _ in tiles]
    print(f"tiles (address order): {tile_names}")
    actual = inits_to_words(tiles)
    mismatches = []
    for i, (a, e) in enumerate(zip(actual, expected_words)):
        if a != e:
            mismatches.append((i, a, e))
    if not mismatches:
        print(f"verify OK — {len(expected_words)} words match")
        return True
    print(f"verify FAIL — {len(mismatches)} mismatches:")
    for i, a, e in mismatches[:20]:
        print(f"  word {i:4d} (0x{i*4:04X})  fasm=0x{a:08X}  expected=0x{e:08X}")
    if len(mismatches) > 20:
        print(f"  ... and {len(mismatches) - 20} more")
    return False


def load_hex(path):
    with open(path) as f:
        return [int(line.strip(), 16) for line in f if line.strip()]


if __name__ == '__main__':
    args = sys.argv[1:]
    do_verify = False
    if args and args[0] == '--verify':
        do_verify = True
        args = args[1:]

    if len(args) != 2:
        sys.exit(f'usage: {sys.argv[0]} [--verify] titania.fasm firmware.hex')

    fasm_path, hex_path = args
    words = load_hex(hex_path)

    with open(fasm_path) as f:
        fasm_text = f.read()

    if do_verify:
        ok = verify(fasm_text, words)
        sys.exit(0 if ok else 1)
    else:
        patched = patch(fasm_text, words)
        with open(fasm_path, 'w') as f:
            f.write(patched)
        print(f"patched {fasm_path} ({len(words)} words across {len(parse_fasm_inits(patched))} tile(s))")
