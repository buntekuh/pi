"""
img2spans.py — convert a pixel-art image to a layered horizontal-span file
for the T46 display.

Usage:
    python tools/img2spans.py info/evening2.png info/evening2.spans

Output format
-------------
One section per palette colour, in back-to-front order.
Each section:

    <palette_index>
    x,y,d;x,y;x,y,d;...   ← full perimeter spans, sorted by (y, x)
    fill:x,y               ← flood-fill seed (kept for later use)

Special header lines:
    size:w,h               ← image dimensions

Perimeter pixels are all pixels of this colour that are adjacent to a pixel
of a different colour (or the image edge).  Encoding is row-major horizontal
runs — the same x,y,d format as before, but covering the full outline rather
than just the topmost boundary.
"""

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from palette import PALETTE_DATA


# ---------------------------------------------------------------------------
# Palette quantisation
# ---------------------------------------------------------------------------

def nearest_palette_index(r, g, b):
    best_i, best_d = 0, float('inf')
    for i, (pr, pg, pb) in enumerate(PALETTE_DATA):
        if i >= 32:          # skip padding blacks
            break
        d = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
        if d < best_d:
            best_d, best_i = d, i
    return best_i


# ---------------------------------------------------------------------------
# Run-length encoding
# ---------------------------------------------------------------------------

def encode_runs(points):
    """Encode a list of (x, y) sorted by (y, x) as 'x,y,d;x,y;...' spans."""
    if not points:
        return ""
    runs = []
    sx, sy = points[0]
    d = 1
    for x, y in points[1:]:
        if y == sy and x == sx + d:
            d += 1
        else:
            runs.append(f"{sx},{sy},{d}" if d > 1 else f"{sx},{sy}")
            sx, sy, d = x, y, 1
    runs.append(f"{sx},{sy},{d}" if d > 1 else f"{sx},{sy}")
    return ";".join(runs)


def perimeter_pixels(quant, w, h, ci):
    """
    Return sorted list of (x, y) for every pixel of colour ci that touches
    a differently-coloured pixel or the image edge.  Sorted row-major (y, x).
    """
    result = []
    for y in range(h):
        for x in range(w):
            if quant[x][y] != ci:
                continue
            on_edge = (x == 0 or x == w - 1 or y == 0 or y == h - 1)
            has_different_neighbour = any(
                quant[nx][ny] != ci
                for nx, ny in ((x-1, y), (x+1, y), (x, y-1), (x, y+1))
                if 0 <= nx < w and 0 <= ny < h
            )
            if on_edge or has_different_neighbour:
                result.append((x, y))
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    try:
        from PIL import Image
    except ImportError:
        sys.exit("Pillow not installed — pip install pillow")

    if len(sys.argv) < 3:
        sys.exit("usage: img2spans.py <input.png> <output.spans>")

    img = Image.open(sys.argv[1]).convert("RGB")
    w, h = img.size
    px = img.load()

    # Quantise
    quant = [[0] * h for _ in range(w)]
    for y in range(h):
        for x in range(w):
            quant[x][y] = nearest_palette_index(*px[x, y])

    # Collect all y positions per colour
    color_ys = defaultdict(list)
    for x in range(w):
        for y in range(h):
            color_ys[quant[x][y]].append(y)

    # Sort colours back-to-front by average Y (low avg Y = sky, high = foreground)
    layer_order = sorted(color_ys, key=lambda c: sum(color_ys[c]) / len(color_ys[c]))

    out = []
    out.append(f"size:{w},{h}")

    for ci in layer_order:
        perim = perimeter_pixels(quant, w, h, ci)
        perim_set = set(perim)

        # Find one seed per connected interior region (BFS over interior pixels)
        interior = {(x, y)
                    for x in range(w) for y in range(h)
                    if quant[x][y] == ci and (x, y) not in perim_set}
        seeds = []
        visited = set()
        for start in interior:
            if start in visited:
                continue
            stack = [start]
            while stack:
                p = stack.pop()
                if p in visited or p not in interior:
                    continue
                visited.add(p)
                px, py = p
                for nb in ((px+1,py),(px-1,py),(px,py+1),(px,py-1)):
                    if nb not in visited and nb in interior:
                        stack.append(nb)
            seeds.append(start)
        # Fallback: perimeter pixel when region is hairline thin
        if not seeds and perim:
            seeds = [perim[0]]

        out.append(str(ci))
        out.append(encode_runs(perim))
        if seeds:
            out.append("fill:" + ";".join(f"{x},{y}" for x, y in seeds))
        out.append("")

    Path(sys.argv[2]).write_text("\n".join(out))
    print(f"wrote {sys.argv[2]}  ({len(layer_order)} layers)")


if __name__ == "__main__":
    main()
