"""
T46 Terminal

A dumb graphical terminal. Renders display commands from the M56.
Captures keyboard input and pushes it to the M56's OS read handler.

Display: 256x192 pixels, 256-colour Doom palette (scaled 3x)
Text:    80x25 characters
"""

import threading
import pygame

# Standard Doom PLAYPAL (first palette, 256 RGB triples)
# fmt: off
DOOM_PALETTE = bytes([
  0,  0,  0,  31,  23,  11,  23,  15,   7,  75,  75,  75,
255,255,255, 27,  27,  27,  19,  19,  19,  11,  11,  11,
  7,   7,   7,  47,  55,  31,  35,  43,  15,  23,  31,   7,
 15,  23,   0,  79,  59,  43,  71,  51,  35,  63,  43,  27,
 55,  35,  19,  47,  27,  11,  43,  23,   7,  35,  19,   3,
 27,  15,   0,  23,  11,   0, 119, 127, 143, 111, 119, 135,
107, 111, 127,  99, 103, 119,  91,  99, 111,  87,  91, 103,
 79,  83,  95,  71,  75,  87,  67,  67,  79,  59,  63,  71,
 55,  55,  63,  47,  51,  55,  43,  43,  47,  35,  39,  43,
 31,  31,  35,  23,  27,  27,  19,  19,  23,  15,  15,  15,
111,  91,  83, 103,  83,  75,  95,  75,  67,  87,  67,  59,
 79,  59,  55,  71,  55,  47,  67,  47,  43,  59,  43,  35,
 55,  35,  31,  47,  31,  27,  43,  27,  23,  35,  23,  19,
 31,  19,  15,  27,  15,  11,  23,  11,   7,  19,   7,   3,
163,  59,  59, 151,  55,  55, 143,  47,  47, 131,  47,  47,
123,  39,  39, 111,  35,  35, 103,  31,  31,  95,  27,  27,
 83,  23,  23,  75,  19,  19,  67,  15,  15,  55,  11,  11,
 47,   7,   7,  39,   0,   0,  31,   0,   0,  23,   0,   0,
231, 167,  35, 215, 155,  31, 199, 143,  27, 183, 135,  23,
167, 123,  19, 151, 111,  15, 135, 103,  11, 119,  95,   7,
107,  83,   3,  91,  71,   0,  79,  63,   0,  67,  51,   0,
 55,  43,   0,  43,  35,   0,  35,  27,   0,  27,  19,   0,
195, 195, 195, 187, 187, 187, 179, 179, 179, 171, 171, 171,
163, 163, 163, 155, 155, 155, 147, 147, 147, 139, 139, 139,
131, 131, 131, 123, 123, 123, 119, 119, 119, 111, 111, 111,
103, 103, 103,  95,  95,  95,  87,  87,  87,  83,  83,  83,
 75,  75,  75,  67,  67,  67,  59,  59,  59,  55,  55,  55,
 47,  47,  47,  39,  39,  39,  35,  35,  35,  27,  27,  27,
163, 127, 103, 151, 115,  91, 143, 107,  83, 131,  99,  75,
123,  91,  67, 115,  83,  59, 107,  75,  55,  99,  67,  47,
 91,  59,  43,  79,  55,  39,  71,  47,  35,  63,  43,  27,
 55,  35,  23,  47,  31,  19,  39,  27,  15,  31,  19,  11,
111,  75,  43, 103,  71,  39,  95,  63,  35,  87,  59,  31,
 79,  51,  27,  71,  47,  23,  63,  43,  19,  55,  39,  15,
 47,  35,  11,  39,  27,   7,  31,  23,   3,  27,  19,   0,
 23,  15,   0,  19,  11,   0,  15,   7,   0,   0,   0,   0,
 99, 107,  47,  91,  99,  43,  83,  91,  43,  79,  83,  39,
 71,  75,  35,  63,  67,  31,  59,  63,  27,  55,  55,  23,
 47,  47,  19,  43,  43,  15,  35,  35,  11,  31,  31,   7,
 27,  23,   0,  23,  19,   0,  19,  15,   0,  15,  11,   0,
163, 167, 255, 143, 147, 255, 119, 123, 255,  99, 107, 255,
 79,  87, 255,  63,  71, 255,  43,  55, 255,  27,  43, 255,
  0,  27, 255,   0,  19, 215,   0,  15, 179,   0,   7, 143,
  0,   3, 111,   0,   0,  83,   0,   0,  55,   0,   0,  31,
 83,   0,  83,  71,   0,  71,  63,   0,  63,  51,   0,  51,
 43,   0,  43,  35,   0,  35,  27,   0,  27,  19,   0,  19,
255, 155,  99, 255, 135,  75, 255, 115,  55, 243,  99,  39,
219,  83,  27, 195,  67,  15, 171,  55,   7, 151,  43,   0,
131,  35,   0, 111,  27,   0,  95,  19,   0,  75,  15,   0,
 59,   7,   0,  43,   3,   0,  31,   0,   0,  15,   0,   0,
])
# fmt: on


CHAR_W = 8    # font cell width
CHAR_H = 8    # font cell height
COLS   = 80
ROWS   = 25

# We render text at native resolution 640x200, graphics at 256x192.
# For simplicity, one surface: 640x480 scaled. But the spec says 256x192.
# We'll use 256x192 native and fit an 8x8 font inside that (32x24 chars).
# Actually spec says 80x25 text mode — that needs 640x200 at 8x8.
# Resolution: use 640x400 surface (text=640x200 top, graphics=256x192 scaled).
# Simpler: single 256x192 framebuffer, tiny 3x4 font for text. Too small.
# Decision: framebuffer = 320x200 @ 2x scale = 640x400. Text fits 40x25 at 8x8.
# Per spec 80x25 needs a wider surface. We'll do 640x200 native for text,
# 256x192 for graphics, switch modes. Scale text surface to fit window.
#
# For now: 640x200 text surface (80x25 @ 8x8), scaled 2x = 640x400 window.
# Graphics mode: 256x192 scaled to fit same window.

SCALE     = 3
GFX_W     = 256
GFX_H     = 192
TXT_W     = COLS * CHAR_W   # 640
TXT_H     = ROWS * CHAR_H   # 200
WIN_W     = GFX_W * SCALE   # 768
WIN_H     = GFX_H * SCALE   # 576


class T46:
    """
    Pygame terminal window.

    Modes:
        'text'     — 80x25 character display
        'graphics' — 256x192 pixel display

    The M56 sends commands via receive(). Keyboard events are pushed
    to m56.input() on each poll() call.
    """

    MODE_TEXT     = "text"
    MODE_GRAPHICS = "graphics"

    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((WIN_W, WIN_H))
        pygame.display.set_caption("T46")

        # Graphics framebuffer: 8-bit indexed, Doom palette
        self.gfx_fb = pygame.Surface((GFX_W, GFX_H), depth=8)
        self.gfx_fb.set_palette(_build_palette())

        # Text framebuffer: 8-bit indexed, same palette
        self.txt_fb = pygame.Surface((TXT_W, TXT_H), depth=8)
        self.txt_fb.set_palette(_build_palette())

        self.font  = pygame.font.SysFont("monospace", CHAR_H * SCALE // 2 + 1)
        self._font_surf_cache = {}

        self.mode    = self.MODE_TEXT
        self.running = True

        # Text state
        self._lines   = [""] * ROWS
        self._cur_row = 0
        self._cur_col = 0
        self._fg      = 7    # light grey
        self._bg      = 0    # black

        self._m56 = None
        self._lock = threading.Lock()

        self._clear_text()
        self._blit()

    def connect(self, m56):
        self._m56 = m56

    # ------------------------------------------------------------------
    # Commands from M56
    # ------------------------------------------------------------------

    def receive(self, command):
        with self._lock:
            t = command.get("type")
            if t == "mode":
                self.mode = command["mode"]
            elif t == "cls":
                if self.mode == self.MODE_TEXT:
                    self._clear_text()
                else:
                    self.gfx_fb.fill(command.get("colour", 0))
            elif t == "text":
                self._draw_text(command)
            elif t == "print":
                self._print(command["text"])
            elif t == "pen":
                self._fg = command["colour"]
            elif t == "line":
                pygame.draw.line(
                    self.gfx_fb,
                    command["colour"],
                    (command["x1"], command["y1"]),
                    (command["x2"], command["y2"]),
                )
            elif t == "fill":
                _flood_fill(self.gfx_fb, command["x"], command["y"], command["colour"])
            elif t == "rect":
                pygame.draw.rect(
                    self.gfx_fb,
                    command["colour"],
                    (command["x"], command["y"], command["w"], command["h"]),
                )
            elif t == "plot":
                self.gfx_fb.set_at((command["x"], command["y"]), command["colour"])
        self._blit()

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------

    def poll(self):
        """Process Pygame events. Call this from the main thread repeatedly."""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                ch = self._key_to_char(event)
                if ch is not None and self._m56:
                    self._m56.input(ch)
        pygame.display.flip()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _clear_text(self):
        self._lines   = [""] * ROWS
        self._cur_row = 0
        self._cur_col = 0
        self.txt_fb.fill(self._bg)

    def _print(self, text):
        """Stream text with newline handling, scrolling."""
        for ch in text:
            if ch == "\n":
                self._cur_col = 0
                self._cur_row += 1
                if self._cur_row >= ROWS:
                    self._scroll()
            elif ch == "\r":
                self._cur_col = 0
            else:
                self._put_char(self._cur_row, self._cur_col, ch, self._fg, self._bg)
                self._cur_col += 1
                if self._cur_col >= COLS:
                    self._cur_col = 0
                    self._cur_row += 1
                    if self._cur_row >= ROWS:
                        self._scroll()

    def _put_char(self, row, col, ch, fg, bg):
        x = col * CHAR_W
        y = row * CHAR_H
        pygame.draw.rect(self.txt_fb, bg, (x, y, CHAR_W, CHAR_H))
        surf = self._render_char(ch, fg, bg)
        self.txt_fb.blit(surf, (x, y))

    def _render_char(self, ch, fg, bg):
        key = (ch, fg, bg)
        if key not in self._font_surf_cache:
            pal = _build_palette()
            rgb_fg = pal[fg]
            rgb_bg = pal[bg]
            s = self.font.render(ch, False, rgb_fg, rgb_bg)
            s = pygame.transform.scale(s, (CHAR_W, CHAR_H))
            self._font_surf_cache[key] = s
        return self._font_surf_cache[key]

    def _draw_text(self, cmd):
        """Place text at explicit (col, row) position."""
        col, row = cmd["x"], cmd["y"]
        fg  = cmd.get("colour", self._fg)
        bg  = cmd.get("bg", self._bg)
        for ch in cmd["text"]:
            if col < COLS:
                self._put_char(row, col, ch, fg, bg)
                col += 1

    def _scroll(self):
        self._cur_row = ROWS - 1
        self.txt_fb.scroll(0, -CHAR_H)
        pygame.draw.rect(
            self.txt_fb, self._bg,
            (0, (ROWS - 1) * CHAR_H, TXT_W, CHAR_H)
        )

    def _blit(self):
        if self.mode == self.MODE_TEXT:
            scaled = pygame.transform.scale(self.txt_fb, (WIN_W, WIN_H))
        else:
            scaled = pygame.transform.scale(self.gfx_fb, (WIN_W, WIN_H))
        self.screen.blit(scaled, (0, 0))

    @staticmethod
    def _key_to_char(event):
        if event.key == pygame.K_RETURN:
            return "\n"
        if event.key == pygame.K_BACKSPACE:
            return "\b"
        if event.unicode:
            return event.unicode
        return None


# ------------------------------------------------------------------
# Palette + flood fill
# ------------------------------------------------------------------

def _build_palette():
    pal = []
    for i in range(0, len(DOOM_PALETTE), 3):
        pal.append((DOOM_PALETTE[i], DOOM_PALETTE[i+1], DOOM_PALETTE[i+2]))
    # pad to 256 if our constant is short
    while len(pal) < 256:
        pal.append((0, 0, 0))
    return pal


def _flood_fill(surface, x, y, colour):
    target = surface.get_at((x, y))[0]  # indexed surface returns index
    if target == colour:
        return
    stack = [(x, y)]
    w, h = surface.get_size()
    while stack:
        cx, cy = stack.pop()
        if cx < 0 or cy < 0 or cx >= w or cy >= h:
            continue
        if surface.get_at((cx, cy))[0] != target:
            continue
        surface.set_at((cx, cy), colour)
        stack.extend([(cx+1, cy), (cx-1, cy), (cx, cy+1), (cx, cy-1)])
