"""
T46 colour palette.

Edit _HEX to change the colours. 256 entries max; anything unused is
padded with black. Index 0 is always black.
"""

# fmt: off
_HEX = [
    # 0 — black (added explicitly)
    "000000",
    # warm terracottas / earthy reds
    "D5917E", "D06F5A", "C24C3C", "A9625B", "8C4434", "582C1E",
    # olives / muted greens
    "B7A063", "8F8C55", "638056", "7D997E",
    # lights / neutrals
    "E6E9E2", "E8D3B8", "D8BE91", "D8BA7B", "E29D58", "E6B49B",
    "C2ABA3", "A48F7E", "7D6452", "5B4F3F",
    # dark greens
    "436657", "28564B", "313E34",
    # purple (note: source had 7-digit typo "528683" — using "522868")
    "528683",
    # cool blue-greens
    "BAD0D1", "6FAAA6", "37777D", "96C3C9", "4998A9", "98A6A1",
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
