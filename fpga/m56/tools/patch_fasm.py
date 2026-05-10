#!/usr/bin/env python3
"""
patch_fasm.py — patch BRAM INIT lines in a Titania .fasm file with new firmware.

Replaces the RAMB36 INIT data for the program memory block without
re-running synthesis, place-and-route, or bitstream assembly from scratch.
Only fasm2frames + xc7frames2bit need to re-run (~5 s instead of ~10 min).

Usage:
    python3 tools/patch_fasm.py titania.fasm firmware/firmware.hex
        — patch titania.fasm in-place

    python3 tools/patch_fasm.py --verify titania.fasm firmware/firmware.hex
        — verify that the FASM already matches the hex (useful for checking
          the bit mapping is correct after a full build)

Artix-7 RAMB36 INIT mapping (one RAMB36 = two RAMB18 halves Y0 and Y1):
    RAMB18_Y0  holds bits [15: 0] of each 32-bit instruction word
    RAMB18_Y1  holds bits [31:16] of each 32-bit instruction word
    Each INIT register is 256 bits = 16 words × 16 bits per half
    64 INIT registers (INIT_00 .. INIT_3F) × 16 words = 1024 words total
"""

import re
import sys

# Matches: TILE_NAME.RAMB18_Yx.INIT_nn[255:0] = 256'hHHH...HHH
INIT_RE = re.compile(
    r'^(\S+)\.(RAMB18_Y\d)\.INIT_([0-9A-Fa-f]{2})\[255:0\]\s*=\s*256\'h([0-9A-Fa-f]{64})$'
)


def words_to_inits(words, mem_words=1024):
    """
    Convert a list of 32-bit instruction words to a dict of INIT hex strings.

    Returns { (ramb_half, init_idx): hex_string_64_chars }
    where ramb_half is 'RAMB18_Y0' or 'RAMB18_Y1'
    and   init_idx  is an integer 0..63.

    Y0 holds bits[15:0], Y1 holds bits[31:16].
    Within each 256-bit INIT register the words are packed LSB-first:
    word 0 occupies bits[15:0], word 1 bits[31:16], ..., word 15 bits[255:240].
    The 64-char hex string is big-endian (most-significant nibble first).
    """
    padded = list(words) + [0] * (mem_words - len(words))
    result = {}
    for init_idx in range(64):
        for half, shift, mask in (('RAMB18_Y0', 0, 0xFFFF), ('RAMB18_Y1', 16, 0xFFFF)):
            val = 0
            for word_in_block in range(15, -1, -1):
                global_word = init_idx * 16 + word_in_block
                bits = (padded[global_word] >> shift) & mask
                val = (val << 16) | bits
            result[(half, init_idx)] = f'{val:064X}'
    return result


def inits_to_words(inits_y0, inits_y1, mem_words=1024):
    """
    Reverse mapping: reconstruct 32-bit words from Y0/Y1 INIT hex strings.

    inits_y0 / inits_y1: dict { init_idx(int): hex_string_64_chars }
    """
    words = [0] * mem_words
    for init_idx in range(64):
        h0 = int(inits_y0.get(init_idx, '0' * 64), 16)
        h1 = int(inits_y1.get(init_idx, '0' * 64), 16)
        for word_in_block in range(16):
            global_word = init_idx * 16 + word_in_block
            if global_word >= mem_words:
                break
            # extract 16-bit slice for this word position
            shift = word_in_block * 16
            lo = (h0 >> shift) & 0xFFFF
            hi = (h1 >> shift) & 0xFFFF
            words[global_word] = (hi << 16) | lo
    return words


def parse_fasm_inits(fasm_text):
    """
    Scan the FASM text and collect all BRAM INIT lines.

    Returns:
        tile_name  — the unique tile name for the BRAM block
        y0_inits   — { init_idx(int): hex_string }
        y1_inits   — { init_idx(int): hex_string }
    """
    tile_name = None
    y0 = {}
    y1 = {}
    for line in fasm_text.splitlines():
        m = INIT_RE.match(line.strip())
        if not m:
            continue
        tile, half, idx_hex, data = m.groups()
        idx = int(idx_hex, 16)
        if tile_name is None:
            tile_name = tile
        elif tile_name != tile:
            # More than one BRAM tile — not currently handled
            raise ValueError(
                f"Multiple BRAM tiles found: {tile_name!r} and {tile!r}. "
                "Only single-BRAM designs are supported."
            )
        if half == 'RAMB18_Y0':
            y0[idx] = data
        else:
            y1[idx] = data
    if tile_name is None:
        raise ValueError("No RAMB18 INIT lines found in FASM — is this the right file?")
    return tile_name, y0, y1


def patch(fasm_text, new_words):
    """Replace all BRAM INIT lines in fasm_text with data from new_words."""
    tile_name, _, _ = parse_fasm_inits(fasm_text)
    new_inits = words_to_inits(new_words)

    def replace_line(m):
        tile, half, idx_hex, _ = m.groups()
        idx = int(idx_hex, 16)
        new_data = new_inits.get((half, idx), '0' * 64)
        return f"{tile}.{half}.INIT_{idx_hex.upper()}[255:0] = 256'h{new_data}"

    return INIT_RE.sub(replace_line, fasm_text)


def verify(fasm_text, expected_words):
    """
    Check that the FASM INIT data matches expected_words.
    Prints a summary and returns True if they match, False otherwise.
    """
    _, y0, y1 = parse_fasm_inits(fasm_text)
    actual = inits_to_words(y0, y1)
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
        print(f"patched {fasm_path} with {len(words)} words from {hex_path}")
