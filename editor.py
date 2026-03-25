"""
T46 in-window text editor.

Runs inside the T46 pygame window. The OS creates an Editor, calls
run(content), and gets back the edited content (or None if discarded).

Keys:
    Arrow keys / Home / End / PgUp / PgDn   navigate
    Ctrl+S                                  save and close
    Ctrl+Q                                  discard and close
"""

_ROWS = 23   # content rows  (T46 = 25 rows; bottom 2 are separator + status)
_COLS = 80


class Editor:

    def __init__(self, os_, path):
        self.os       = os_
        self.path     = path
        self.lines    = [""]
        self.row      = 0     # cursor row  in buffer
        self.col      = 0     # cursor col  in buffer
        self.top      = 0     # viewport top  (first visible buffer row)
        self.left     = 0     # viewport left (first visible buffer col)
        self.modified = False
        self._saved   = False  # becomes True once Ctrl+S is pressed
        self._prev    = None   # previously displayed screen lines

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self, content=""):
        """Open the editor with content. Returns edited text or None (discard)."""
        self.lines = content.split("\n")
        if self.lines and self.lines[-1] == "":
            self.lines.pop()
        if not self.lines:
            self.lines = [""]

        term = self.os.terminal
        term.set_raw(True)
        term.receive({"type": "cls"})
        self._prev = None
        self._draw(full=True)

        try:
            while True:
                key  = term.read_key()
                done = self._handle(key)
                self._draw()
                if done:
                    break
        finally:
            term.set_raw(False)
            term.receive({"type": "cls"})

        return ("\n".join(self.lines) + "\n") if self._saved else None

    # ------------------------------------------------------------------
    # Key handling
    # ------------------------------------------------------------------

    def _save(self):
        self._saved   = True
        self.modified = False
        self.os.fs.write_file(self.path, "\n".join(self.lines) + "\n")

    def _handle(self, key):
        """Process one keypress. Returns done."""
        if key == "\x13":                    # Ctrl+S — save in place
            self._save()
            return False
        if key == "\x11":        return True  # Ctrl+Q — quit

        if   key == "UP":        self._move_up()
        elif key == "DOWN":      self._move_down()
        elif key == "LEFT":      self._move_left()
        elif key == "RIGHT":     self._move_right()
        elif key == "HOME":      self.col = 0
        elif key == "END":       self.col = len(self.lines[self.row])
        elif key == "PGUP":
            self.row = max(0, self.row - _ROWS)
            self.col = min(self.col, len(self.lines[self.row]))
        elif key == "PGDN":
            self.row = min(len(self.lines) - 1, self.row + _ROWS)
            self.col = min(self.col, len(self.lines[self.row]))
        elif key == "\n":        self._insert_newline()
        elif key == "\b":        self._backspace()
        elif key == "\t":        self._insert("    ")
        elif len(key) == 1 and key.isprintable():
            self._insert(key)

        self._clamp_viewport()
        return False

    def _move_up(self):
        if self.row > 0:
            self.row -= 1
            self.col = min(self.col, len(self.lines[self.row]))

    def _move_down(self):
        if self.row < len(self.lines) - 1:
            self.row += 1
            self.col = min(self.col, len(self.lines[self.row]))

    def _move_left(self):
        if self.col > 0:
            self.col -= 1
        elif self.row > 0:
            self.row -= 1
            self.col = len(self.lines[self.row])

    def _move_right(self):
        if self.col < len(self.lines[self.row]):
            self.col += 1
        elif self.row < len(self.lines) - 1:
            self.row += 1
            self.col  = 0

    def _insert(self, text):
        line = self.lines[self.row]
        self.lines[self.row] = line[:self.col] + text + line[self.col:]
        self.col += len(text)
        self.modified = True

    def _insert_newline(self):
        line = self.lines[self.row]
        self.lines[self.row] = line[:self.col]
        self.lines.insert(self.row + 1, line[self.col:])
        self.row += 1
        self.col  = 0
        self.modified = True
        self._prev = None  # line count changed — full redraw

    def _backspace(self):
        if self.col > 0:
            line = self.lines[self.row]
            self.lines[self.row] = line[:self.col - 1] + line[self.col:]
            self.col -= 1
            self.modified = True
        elif self.row > 0:
            prev_len = len(self.lines[self.row - 1])
            self.lines[self.row - 1] += self.lines[self.row]
            self.lines.pop(self.row)
            self.row -= 1
            self.col  = prev_len
            self.modified = True
            self._prev = None

    def _clamp_viewport(self):
        if self.row < self.top:
            self.top = self.row
        elif self.row >= self.top + _ROWS:
            self.top = self.row - _ROWS + 1
        if self.col < self.left:
            self.left = self.col
        elif self.col >= self.left + _COLS:
            self.left = self.col - _COLS + 1

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _draw(self, full=False):
        term    = self.os.terminal
        scr_row = self.row - self.top
        scr_col = self.col - self.left

        # Build raw screen lines (no cursor)
        raw = []
        for i in range(_ROWS):
            buf_row = self.top + i
            if buf_row < len(self.lines):
                line    = self.lines[buf_row]
                visible = line[self.left: self.left + _COLS]
                raw.append(visible.ljust(_COLS))
            else:
                raw.append("~" + " " * (_COLS - 1))

        # Apply block cursor
        screen = list(raw)
        if 0 <= scr_row < _ROWS and 0 <= scr_col < _COLS:
            line = list(screen[scr_row])
            line[scr_col] = "\u2588"   # █
            screen[scr_row] = "".join(line)

        # Separator (row 23) and status bar (row 24 — max 79 chars, no wrap)
        mod    = "*" if self.modified else " "
        status = (f" {mod} {self.path}   "
                  f"ln {self.row + 1}/{len(self.lines)}  "
                  f"col {self.col + 1}"
                  f"    ^S save  ^Q quit (close)")[: _COLS - 1]

        if full or self._prev is None:
            for i, line in enumerate(screen):
                term.receive({"type": "goto", "row": i, "col": 0})
                term.receive({"type": "print", "text": line})
            term.receive({"type": "goto", "row": _ROWS, "col": 0})
            term.receive({"type": "print", "text": "-" * (_COLS - 1)})
        else:
            for i, (new, old) in enumerate(zip(screen, self._prev)):
                if new != old:
                    term.receive({"type": "goto", "row": i, "col": 0})
                    term.receive({"type": "print", "text": new})

        term.receive({"type": "goto", "row": _ROWS + 1, "col": 0})
        term.receive({"type": "print", "text": status})

        self._prev = screen
