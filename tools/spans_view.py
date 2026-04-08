"""
spans_view.py — render a .spans file in a pygame window.

Usage:
    python tools/spans_view.py info/evening2.spans
    python tools/spans_view.py info/evening2.spans --scale 2
    python tools/spans_view.py info/evening2.spans --scale 2 --delay 100

Options:
    --scale N     integer display scale factor (default 1)
    --delay MS    pause MS milliseconds between layer draws (default 0)

Rendering strategy (back-to-front):
  1. First layer (sky): fill the whole canvas.
  2. Each subsequent layer:
       a. Draw the top-boundary spans as horizontal 1px lines.
       b. Stitch vertical segments wherever the boundary y jumps between
          adjacent columns — this closes the outline so the flood fill
          cannot leak through the gaps.
       c. Flood fill from the seed point.

Press any key or close the window to quit.
"""

import sys
import time
import argparse
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))
from palette import PALETTE_DATA


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse_spans(path_or_bytes):
    if isinstance(path_or_bytes, (bytes, bytearray)):
        lines = path_or_bytes.decode(errors='replace').splitlines()
    else:
        lines = Path(path_or_bytes).read_text().splitlines()
    w = h = 0
    layers = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if line.startswith("size:"):
            w, h = map(int, line[5:].split(","))
            i += 1
            continue
        if line.lstrip("-").isdigit():
            palette_idx = int(line)
            spans_str   = lines[i + 1].strip() if i + 1 < len(lines) else ""
            seed        = None
            if i + 2 < len(lines) and lines[i + 2].strip().startswith("fill:"):
                raw   = lines[i + 2].strip()[5:]
                seed  = [tuple(map(int, pt.split(","))) for pt in raw.split(";")]
                i += 3
            else:
                i += 2
            layers.append((palette_idx, spans_str, seed))
            continue
        i += 1
    return w, h, layers


def parse_boundary(spans_str):
    """Yield (x, y, length) for each run in 'x,y,d;x,y;...' string."""
    if not spans_str:
        return
    for token in spans_str.split(";"):
        parts = token.split(",")
        if len(parts) == 3:
            yield int(parts[0]), int(parts[1]), int(parts[2])
        elif len(parts) == 2:
            yield int(parts[0]), int(parts[1]), 1


# ---------------------------------------------------------------------------
# Pygame surface primitives (operate at native 1x; scale only at blit time)
# ---------------------------------------------------------------------------

def surf_rect(surf, colour, x, y, w, h):
    import pygame
    pygame.draw.rect(surf, colour, (x, y, w, h))


def surf_plot(surf, colour, x, y):
    surf.set_at((x, y), colour)


def surf_line(surf, colour, x1, y1, x2, y2):
    import pygame
    pygame.draw.line(surf, colour, (x1, y1), (x2, y2))


def surf_fill(surf, colour, x, y, on_update=None):
    """
    Scanline flood fill — fills horizontal runs with draw.rect (fast C path).
    Calls on_update() after each span so the fill can be seen spreading.
    """
    import pygame
    target = surf.get_at((x, y))[:3]
    if target == colour:
        return
    sw, sh = surf.get_size()
    stack = [(x, y)]
    while stack:
        cx, cy = stack.pop()
        if cy < 0 or cy >= sh:
            continue
        if surf.get_at((cx, cy))[:3] != target:
            continue
        # Extend left and right to find the full span
        xl = cx
        while xl > 0 and surf.get_at((xl - 1, cy))[:3] == target:
            xl -= 1
        xr = cx
        while xr < sw - 1 and surf.get_at((xr + 1, cy))[:3] == target:
            xr += 1
        # Fill the span in one rect call
        pygame.draw.rect(surf, colour, (xl, cy, xr - xl + 1, 1))
        if on_update:
            on_update()
        # Push one seed per contiguous target run in the rows above and below
        for ny in (cy - 1, cy + 1):
            if not (0 <= ny < sh):
                continue
            xi = xl
            while xi <= xr:
                if surf.get_at((xi, ny))[:3] == target:
                    stack.append((xi, ny))
                    while xi <= xr and surf.get_at((xi, ny))[:3] == target:
                        xi += 1
                else:
                    xi += 1


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

def render(surf, w, h, layers, delay=0, screen=None, scale=1):
    import pygame

    pause = delay / 1000.0

    def show():
        if screen and scale > 1:
            scaled = pygame.transform.scale(surf, (w * scale, h * scale))
            screen.blit(scaled, (0, 0))
        elif screen:
            screen.blit(surf, (0, 0))
        if screen:
            pygame.display.flip()

    def show_and_wait():
        show()
        if pause:
            time.sleep(pause)

    for layer_num, (pidx, spans_str, seed) in enumerate(layers):
        rgb = PALETTE_DATA[pidx]

        if layer_num == 0:
            surf_rect(surf, rgb, 0, 0, w, h)
            show_and_wait()
            continue

        # Draw perimeter row by row — group spans on the same y, show each row
        current_y = None
        for x, y, length in parse_boundary(spans_str):
            surf_rect(surf, rgb, x, y, length, 1)
            if y != current_y:
                current_y = y
                show_and_wait()

        # Flood fill from every interior seed, animating the spread
        if seed:
            for sx, sy in seed:
                surf_fill(surf, rgb, sx, sy, on_update=show)

    show()


# ---------------------------------------------------------------------------
# T46 terminal renderer  (no pygame surface — sends receive() commands)
# ---------------------------------------------------------------------------

def render_to_terminal(terminal, layers):
    """
    Render a parsed spans layer list directly to a T46 terminal via receive().
    Used by the Grue interpreter draw command — no local pygame surface needed.
    """
    for layer_num, (pidx, spans_str, seed) in enumerate(layers):
        terminal.receive({'type': 'pen', 'colour': pidx})
        if layer_num == 0:
            # Sky: full-screen rect using pen colour
            from t46 import GFX_W, GFX_H
            terminal.receive({'type': 'rect', 'x': 0, 'y': 0,
                              'w': GFX_W, 'h': GFX_H, 'colour': pidx})
            continue
        for x, y, length in parse_boundary(spans_str):
            terminal.receive({'type': 'rect', 'x': x, 'y': y,
                              'w': length, 'h': 1, 'colour': pidx})
        if seed:
            for sx, sy in seed:
                terminal.receive({'type': 'fill', 'x': sx, 'y': sy, 'colour': pidx})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Render a .spans file")
    parser.add_argument("spans",  help=".spans file")
    parser.add_argument("--scale", type=int, default=1, metavar="N",
                        help="display scale factor (default 1)")
    parser.add_argument("--delay", type=int, default=0, metavar="MS",
                        help="pause between layers in ms (default 0)")
    args = parser.parse_args()

    w, h, layers = parse_spans(args.spans)
    if not layers:
        sys.exit("no layers found")

    import pygame
    pygame.init()
    screen = pygame.display.set_mode((w * args.scale, h * args.scale))
    pygame.display.set_caption(Path(args.spans).name)

    # Draw into a native 1x surface, scale only for display
    surf = pygame.Surface((w, h))

    import threading
    def do_render():
        render(surf, w, h, layers, delay=args.delay,
               screen=screen, scale=args.scale)

    threading.Thread(target=do_render, daemon=True).start()

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                running = False
        pygame.time.wait(16)

    pygame.quit()


if __name__ == "__main__":
    main()
