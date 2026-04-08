"""
T46 colour palette — generated from tools/palette.aseprite.

Do not edit by hand.  Add or change colours in Aseprite, then run:
    python tools/aseprite2palette.py
"""

# fmt: off
_HEX = [
    "000000",  #   0
    "FFFFFF",  #   1
    "A9625B",  #   2
    "C24C3C",  #   3
    "D06F5A",  #   4
    "8C4434",  #   5
    "D5917E",  #   6
    "582C1E",  #   7
    "C2ABA3",  #   8
    "E6B49B",  #   9
    "7D6452",  #  10
    "A48F7E",  #  11
    "E29D58",  #  12
    "E8D3B8",  #  13
    "5B4F3F",  #  14
    "D8BE91",  #  15
    "D8BA7B",  #  16
    "B7A063",  #  17
    "8F8C55",  #  18
    "E6E9E2",  #  19
    "638056",  #  20
    "7D997E",  #  21
    "313E34",  #  22
    "436657",  #  23
    "98A6A1",  #  24
    "28564B",  #  25
    "6FAAA6",  #  26
    "528683",  #  27
    "BAD0D1",  #  28
    "37777D",  #  29
    "96C3C9",  #  30
    "4998A9",  #  31
    "45AC49",  #  32
    "37617D",  #  33
    "E27D58",  #  34
]
# fmt: on


def _parse(h):
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


_defined   = [_parse(h) for h in _HEX]
_padding   = [(0, 0, 0)] * (256 - len(_defined))

# PALETTE_DATA: list of 256 (R, G, B) tuples — the single source of truth
PALETTE_DATA = _defined + _padding

# Raw bytes for pygame set_palette()
PALETTE_BYTES = bytes(b for rgb in PALETTE_DATA for b in rgb)
