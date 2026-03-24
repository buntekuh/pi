"""
Generates palette.html — a visual reference of every colour in the
current T46 palette with its index number.

Usage:
    python3 tools/palette_viewer.py
    open tools/palette.html
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from palette import PALETTE_DATA

palette = PALETTE_DATA

COLS = 16
CELL = 64   # px

rows = []
for row_start in range(0, len(palette), COLS):
    cells = []
    for i in range(row_start, min(row_start + COLS, len(palette))):
        r, g, b = palette[i]
        luma = 0.299 * r + 0.587 * g + 0.114 * b
        label_col = "#000" if luma > 128 else "#fff"
        cells.append(
            f'<td style="background:rgb({r},{g},{b});width:{CELL}px;'
            f'height:{CELL}px;text-align:center;vertical-align:middle;'
            f'font:11px monospace;color:{label_col};border:1px solid #222">'
            f'{i}<br><span style="font-size:9px">#{r:02X}{g:02X}{b:02X}</span></td>'
        )
    rows.append("<tr>" + "".join(cells) + "</tr>")

html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>T46 Palette</title>
<style>
  body {{ background:#111; padding:20px; }}
  h1   {{ color:#aaa; font-family:monospace; }}
  table {{ border-collapse:collapse; }}
</style>
</head>
<body>
<h1>T46 Palette &mdash; {len(palette)} entries</h1>
<table>{"".join(rows)}</table>
</body></html>
"""

out = os.path.join(os.path.dirname(__file__), 'palette.html')
with open(out, 'w') as f:
    f.write(html)

print(f"Written {len(palette)} colours to {out}")
