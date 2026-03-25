"""
T46 Terminal

A dumb graphical terminal. Renders display commands from the M56.
Captures keyboard input and pushes it to the M56's OS read handler.

Display: 256x192 pixels, 256-colour Doom palette (scaled 3x)
Text:    80x25 characters
"""

import queue
import threading
import pygame

from palette import PALETTE_DATA, PALETTE_BYTES


CHAR_W = 9     # font cell width  — 1 px wider than the nominal 8 to give glyphs breathing room
CHAR_H = 16    # font cell height — 8x16 looks like a real terminal
COLS   = 80
ROWS   = 25

GFX_W  = 256
GFX_H  = 192
GFX_SCALE = 3

TXT_W  = COLS * CHAR_W   # 640
TXT_H  = ROWS * CHAR_H   # 400

# macOS rounds window corners (~8 px radius).  A small bottom margin keeps
# the last text row clear of the curve.
_BOTTOM_PAD = 8

# Window: text mode drives the size; graphics mode scales up to fit.
WIN_W  = TXT_W                  # 640
WIN_H  = TXT_H + _BOTTOM_PAD   # 408


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

        # Text framebuffer: 32-bit so font surfaces blit cleanly
        self.txt_fb = pygame.Surface((TXT_W, TXT_H))

        # Prefer Menlo/Monaco (macOS native coding fonts) at size 13 — they
        # give M=(8,16), leaving a spare pixel inside the 9-wide cell and
        # rendering wide glyphs (m, w) cleanly.  Fall back to Courier New /
        # Courier at size 14 on other platforms.
        for name, size in (("Menlo",       CHAR_H - 3),
                           ("Monaco",      CHAR_H - 3),
                           ("Courier New", CHAR_H - 2),
                           ("Courier",     CHAR_H - 2),
                           ("monospace",   CHAR_H - 2)):
            self.font = pygame.font.SysFont(name, size, bold=False)
            fw, fh = self.font.size("M")
            if fw <= CHAR_W and fh <= CHAR_H:
                break
        self._font_surf_cache = {}

        self.mode    = self.MODE_TEXT
        self.running = True

        # Text state (owned by main thread)
        self._cur_row = 0
        self._cur_col = 0
        self._fg      = PALETTE_DATA[26]  # #6FAAA6 — teal
        self._bg      = (0,  0,  0)     # black

        self._m56     = None
        self._scroll_bottom = ROWS - 1   # bottom row of the scroll region (inclusive)

        # Render command queue: M56 thread enqueues, main thread executes
        self._cmd_queue = queue.Queue()

        # I/O bus interface (CPU IN/OUT instructions)
        self._io_args     = [0, 0, 0, 0]
        self._char_queue  = queue.Queue()   # individual chars for CPU IN
        self._line_buffer = []

        # Shell line input: poll() pushes completed lines here.
        # read_line() blocks until one is available.
        self._line_queue  = queue.Queue()

        # Raw key input: used by the editor (set_raw=True bypasses line buffer)
        self._key_queue  = queue.Queue()
        self._raw_mode   = False

        self._clear_text()

    def connect(self, m56):
        self._m56 = m56

    def register_on_bus(self, io_bus):
        """Register all T46 ports on the I/O bus."""
        from m56 import (PORT_T46_CMD, PORT_T46_ARG0, PORT_T46_ARG1,
                         PORT_T46_ARG2, PORT_T46_ARG3, PORT_T46_KEY)
        for port in (PORT_T46_CMD, PORT_T46_ARG0, PORT_T46_ARG1,
                     PORT_T46_ARG2, PORT_T46_ARG3, PORT_T46_KEY):
            io_bus.register(port, self)

    # ------------------------------------------------------------------
    # I/O bus device interface
    # ------------------------------------------------------------------

    def io_write(self, port, value):
        from m56 import (PORT_T46_CMD,  PORT_T46_ARG0, PORT_T46_ARG1,
                         PORT_T46_ARG2, PORT_T46_ARG3,
                         T46_CMD_CLS, T46_CMD_PRINT, T46_CMD_PEN,
                         T46_CMD_PLOT, T46_CMD_LINE,  T46_CMD_FILL,
                         T46_CMD_RECT, T46_CMD_MODE)
        if port == PORT_T46_ARG0:
            self._io_args[0] = value
        elif port == PORT_T46_ARG1:
            self._io_args[1] = value
        elif port == PORT_T46_ARG2:
            self._io_args[2] = value
        elif port == PORT_T46_ARG3:
            self._io_args[3] = value
        elif port == PORT_T46_CMD:
            a = self._io_args
            if value == T46_CMD_CLS:
                self.receive({"type": "cls"})
            elif value == T46_CMD_PRINT:
                self.receive({"type": "print", "text": chr(a[0] & 0xFF)})
            elif value == T46_CMD_PEN:
                self.receive({"type": "pen", "colour": a[0]})
            elif value == T46_CMD_PLOT:
                self.receive({"type": "plot", "x": a[0], "y": a[1], "colour": self._fg})
            elif value == T46_CMD_LINE:
                self.receive({"type": "line", "x1": a[0], "y1": a[1],
                              "x2": a[2], "y2": a[3], "colour": self._fg})
            elif value == T46_CMD_FILL:
                self.receive({"type": "fill", "x": a[0], "y": a[1], "colour": self._fg})
            elif value == T46_CMD_RECT:
                self.receive({"type": "rect", "x": a[0], "y": a[1],
                              "w": a[2], "h": a[3], "colour": self._fg})
            elif value == T46_CMD_MODE:
                mode = self.MODE_TEXT if a[0] == 0 else self.MODE_GRAPHICS
                self.receive({"type": "mode", "mode": mode})

    def io_read(self, port):
        """
        Called by CPU IN instruction (from the M56 thread).
        PORT_T46_KEY: returns one character code. Blocks if queue is empty.
        The CPU reads in a loop until it receives ord('\\n').
        """
        from m56 import PORT_T46_KEY
        if port == PORT_T46_KEY:
            ch = self._char_queue.get()    # blocks here until poll() pushes a char
            return ord(ch)
        return 0

    def read_line(self):
        """Block until the user presses Enter. Returns the line without newline."""
        return self._line_queue.get()

    def set_raw(self, raw):
        """Switch between line-buffered (shell) and raw (editor) input modes."""
        self._raw_mode = raw
        if raw:
            self._line_buffer.clear()

    def read_key(self):
        """Block until one raw keypress is available. Used by the editor."""
        return self._key_queue.get()

    # ------------------------------------------------------------------
    # Commands from M56  (called from M56 thread — enqueue only)
    # ------------------------------------------------------------------

    def receive(self, command):
        """Enqueue a display command. Safe to call from any thread."""
        self._cmd_queue.put(command)

    # ------------------------------------------------------------------
    # Input / event loop  (main thread only)
    # ------------------------------------------------------------------

    def poll(self):
        """Process Pygame events and drain the render queue. Main thread only."""
        dirty = False

        # Keyboard events
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                if self._raw_mode:
                    key = self._event_to_key(event)
                    if key is not None:
                        self._key_queue.put(key)
                else:
                    ch = self._key_to_char(event)
                    if ch is None:
                        continue
                    if ch == "\b":
                        if self._line_buffer:
                            self._line_buffer.pop()
                            self._print("\b \b")
                            dirty = True
                    elif ch == "\n":
                        self._print("\n")
                        line = "".join(self._line_buffer)
                        self._line_buffer.clear()
                        # Shell input (Python OS layer)
                        self._line_queue.put(line)
                        # CPU input (IN instruction)
                        for c in line:
                            self._char_queue.put(c)
                        self._char_queue.put("\n")
                        dirty = True
                    else:
                        self._line_buffer.append(ch)
                        self._print(ch)
                        dirty = True

        # Drain render commands from M56 thread
        while not self._cmd_queue.empty():
            try:
                self._exec_cmd(self._cmd_queue.get_nowait())
                dirty = True
            except queue.Empty:
                break

        if dirty:
            self._blit()
        pygame.display.flip()

    def _exec_cmd(self, cmd):
        """Execute one display command. Main thread only."""
        t = cmd.get("type")
        if t == "goto":
            self._cur_row = max(0, min(cmd["row"], ROWS - 1))
            self._cur_col = max(0, min(cmd["col"], COLS - 1))
            return
        if t == "scroll_region":
            # Set the bottom of the scroll region (0-based row index).
            # Rows above this value scroll normally; rows at or below are
            # protected and will not move when the screen scrolls.
            self._scroll_bottom = max(0, min(cmd["bottom"], ROWS - 1))
            return
        if t == "mode":
            self.mode = cmd["mode"]
        elif t == "cls":
            if self.mode == self.MODE_TEXT:
                self._clear_text()
            else:
                self.gfx_fb.fill(cmd.get("colour", 0))
        elif t == "print":
            self._print(cmd["text"])
        elif t == "pen":
            # colour can be an RGB tuple or a Doom palette index
            c = cmd["colour"]
            self._fg = _build_palette()[c] if isinstance(c, int) else c
        elif t == "text":
            self._draw_text(cmd)
        elif t == "line":
            pal = _build_palette()
            pygame.draw.line(self.gfx_fb, pal[cmd["colour"]],
                             (cmd["x1"], cmd["y1"]), (cmd["x2"], cmd["y2"]))
        elif t == "fill":
            _flood_fill(self.gfx_fb, cmd["x"], cmd["y"], cmd["colour"])
        elif t == "rect":
            pal = _build_palette()
            pygame.draw.rect(self.gfx_fb, pal[cmd["colour"]],
                             (cmd["x"], cmd["y"], cmd["w"], cmd["h"]))
        elif t == "plot":
            pal = _build_palette()
            self.gfx_fb.set_at((cmd["x"], cmd["y"]), pal[cmd["colour"]])

    # ------------------------------------------------------------------
    # Internal rendering helpers  (main thread only)
    # ------------------------------------------------------------------

    def _clear_text(self):
        self._cur_row = 0
        self._cur_col = 0
        self.txt_fb.fill(self._bg)

    def _print(self, text):
        for ch in text:
            if ch == "\n":
                self._cur_col = 0
                self._cur_row += 1
                if self._cur_row > self._scroll_bottom:
                    self._scroll()
            elif ch == "\r":
                self._cur_col = 0
            elif ch == "\b":
                if self._cur_col > 0:
                    self._cur_col -= 1
                    self._put_char(self._cur_row, self._cur_col, " ", self._fg, self._bg)
            else:
                self._put_char(self._cur_row, self._cur_col, ch, self._fg, self._bg)
                self._cur_col += 1
                if self._cur_col >= COLS:
                    self._cur_col = 0
                    self._cur_row += 1
                    if self._cur_row > self._scroll_bottom:
                        self._scroll()

    def _put_char(self, row, col, ch, fg, bg):
        x, y = col * CHAR_W, row * CHAR_H
        pygame.draw.rect(self.txt_fb, bg, (x, y, CHAR_W, CHAR_H))
        surf = self._render_char(ch, fg, bg)
        # Clip to the cell so wide glyphs (m, w, …) don't bleed into the
        # next column and get erased when that column's background is drawn.
        self.txt_fb.blit(surf, (x, y), (0, 0, CHAR_W, CHAR_H))

    def _render_char(self, ch, rgb_fg, rgb_bg):
        key = (ch, rgb_fg, rgb_bg)
        if key not in self._font_surf_cache:
            # Render at natural font size — no squeezing
            s = self.font.render(ch, False, rgb_fg, rgb_bg)
            self._font_surf_cache[key] = s
        return self._font_surf_cache[key]

    def _draw_text(self, cmd):
        col, row = cmd["x"], cmd["y"]
        fg  = cmd.get("colour", self._fg)
        bg  = cmd.get("bg", self._bg)
        for ch in cmd["text"]:
            if col < COLS:
                self._put_char(row, col, ch, fg, bg)
                col += 1

    def _scroll(self):
        bottom = self._scroll_bottom
        self._cur_row = bottom
        if bottom == ROWS - 1:
            # Full-screen scroll — use the fast built-in path.
            self.txt_fb.scroll(0, -CHAR_H)
            pygame.draw.rect(self.txt_fb, self._bg,
                             (0, (ROWS - 1) * CHAR_H, TXT_W, CHAR_H))
        else:
            # Partial scroll: rows 0..bottom only.  pygame's scroll() cannot
            # be used on a subsurface, so copy the region via blit + temp.
            # Copy rows 1..bottom (shifted up) into a temp surface, then
            # blit it back to rows 0..bottom-1, and clear row bottom.
            h = bottom * CHAR_H   # height of rows 1..bottom
            temp = self.txt_fb.subsurface(
                pygame.Rect(0, CHAR_H, TXT_W, h)).copy()
            self.txt_fb.blit(temp, (0, 0))
            pygame.draw.rect(self.txt_fb, self._bg,
                             (0, bottom * CHAR_H, TXT_W, CHAR_H))

    def _blit(self):
        if self.mode == self.MODE_TEXT:
            # txt_fb is already WIN_W x WIN_H — blit directly, no scaling
            self.screen.blit(self.txt_fb, (0, 0))
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

    @staticmethod
    def _event_to_key(event):
        """Translate a pygame KEYDOWN event to a raw key string for the editor."""
        k = event.key
        if k == pygame.K_UP:        return "UP"
        if k == pygame.K_DOWN:      return "DOWN"
        if k == pygame.K_LEFT:      return "LEFT"
        if k == pygame.K_RIGHT:     return "RIGHT"
        if k == pygame.K_HOME:      return "HOME"
        if k == pygame.K_END:       return "END"
        if k == pygame.K_PAGEUP:    return "PGUP"
        if k == pygame.K_PAGEDOWN:  return "PGDN"
        if k == pygame.K_RETURN:    return "\n"
        if k == pygame.K_BACKSPACE: return "\b"
        if k == pygame.K_TAB:       return "\t"
        if event.unicode:           return event.unicode
        return None


# ------------------------------------------------------------------
# Palette + flood fill
# ------------------------------------------------------------------

def _build_palette():
    return list(PALETTE_DATA)


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
