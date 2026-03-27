"""
Pi source-level debugger.
=========================

Runs a .pi program token by token inside the T46 window, showing the
source, stack, and last program output on every step.

Layout (25 rows × 80 cols)
---------------------------
  rows  0-15   source view  — 16 lines, auto-scrolls to keep current line
  row  16      separator
  rows 17-21   stack view   — top 5 values (top of stack in amber)
  row  22      output log   — last line the program printed
  row  23      separator
  row  24      status bar   — mode, location, token, key hints

Keys
----
  s / Space / Enter   step one token
  r                   run to end (no more pausing)
  q                   quit immediately
"""

from palette import PALETTE_DATA as _PAL
from pi_interp import Interpreter, InterpError
from pi_lexer  import LexError

# ---------------------------------------------------------------------------
# Palette choices
# ---------------------------------------------------------------------------

_BG          = (0, 0, 0)
_FG_DEFAULT  = _PAL[11]   # #E6E9E2  near-white  — normal source text
_FG_LINENO   = _PAL[30]   # #98A6A1  grey-blue   — line numbers
_FG_SEP      = _PAL[26]   # #6FAAA6  teal        — separator lines
_BG_CURLINE  = _PAL[22]   # #28564B  dark teal   — current-line highlight
_FG_STACK0   = _PAL[15]   # #E29D58  amber       — top-of-stack value
_FG_STACK    = _PAL[11]   # #E6E9E2  near-white  — other stack values
_FG_STKLABEL = _PAL[30]   # #98A6A1  grey-blue   — "stack (n):" label
_FG_OUTPUT   = _PAL[14]   # #D8BA7B  warm gold   — program output line
_FG_STATUS   = _PAL[28]   # #4998A9  cool blue   — status bar
_FG_ERROR    = _PAL[3]    # #C24C3C  red         — error message

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------

_COLS       = 80
_SRC_TOP    = 0
_SRC_ROWS   = 16   # rows 0-15
_SEP1       = 16   # row 16
_STK_TOP    = 17   # rows 17-21
_STK_ROWS   = 5
_OUT_ROW    = 22   # row 22 — last output line
_SEP2       = 23   # row 23
_STATUS_ROW = 24   # row 24


# ---------------------------------------------------------------------------
# Internal sentinel
# ---------------------------------------------------------------------------

class _Quit(Exception):
    pass


# ---------------------------------------------------------------------------
# Debugger
# ---------------------------------------------------------------------------

class PiDebugger:

    def __init__(self, os_):
        self._os   = os_
        self._term = os_.terminal

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self, source, filename='<pi>'):
        self._source_lines = source.splitlines()
        self._filename     = filename
        self._stepping     = True    # False → run without pausing
        self._cur_tok      = None
        self._last_output  = ''      # last text the program printed

        def capture_output(text):
            # Accumulate output; keep only the last non-empty line for display.
            self._last_output = (self._last_output + text)
            # Trim to last line so the output row stays clean.
            lines = self._last_output.splitlines()
            if lines:
                self._last_output = lines[-1]

        interp = Interpreter(
            output    = capture_output,
            input_fn  = lambda: self._os.read_line(),
            term_fn   = self._term.receive,
            step_hook = self._hook,
        )

        self._term.set_raw(True)
        self._term.receive({'type': 'cls'})
        self._draw_separators()

        try:
            interp.run(source)
            # Program finished normally — show completion message.
            self._status_msg('Program finished.  q to close.')
            self._drain_quit()
        except _Quit:
            pass
        except (LexError, InterpError) as e:
            self._status_msg(f'ERROR: {e}', error=True)
            self._drain_quit()
        finally:
            self._term.set_raw(False)
            self._term.receive({'type': 'cls'})

    # ------------------------------------------------------------------
    # Step hook — called by the interpreter before every token
    # ------------------------------------------------------------------

    def _hook(self, tok, stack):
        self._cur_tok = tok
        self._draw_source(tok)
        self._draw_stack(stack)
        self._draw_output()
        self._draw_status(tok)
        if self._stepping:
            self._wait_key()

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------

    def _wait_key(self):
        while True:
            key = self._term.read_key()
            if key in ('s', '\n', ' ', ''):
                return
            if key == 'r':
                self._stepping = False
                return
            if key == 'q':
                raise _Quit()

    def _drain_quit(self):
        """Wait for 'q' after the program ends or errors."""
        while True:
            key = self._term.read_key()
            if key == 'q':
                return

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _text(self, x, y, text, colour, bg=None):
        self._term.receive({
            'type':   'text',
            'x':      x,
            'y':      y,
            'text':   text,
            'colour': colour,
            'bg':     bg or _BG,
        })

    def _draw_separators(self):
        sep = '-' * (_COLS - 1)
        self._text(0, _SEP1, sep, _FG_SEP)
        self._text(0, _SEP2, sep, _FG_SEP)

    def _draw_source(self, tok):
        cur  = tok.line - 1           # 0-based index into source lines
        half = _SRC_ROWS // 2
        top  = max(0, cur - half)
        top  = min(top, max(0, len(self._source_lines) - _SRC_ROWS))

        for row in range(_SRC_ROWS):
            buf = top + row
            y   = _SRC_TOP + row
            is_cur = (buf == cur)
            bg     = _BG_CURLINE if is_cur else _BG

            if buf < len(self._source_lines):
                ln   = f'{buf + 1:4d} | '
                body = self._source_lines[buf]
            else:
                ln   = '     | '
                body = '~'

            # Pad the full row to clear any previous content.
            full = (ln + body)[:_COLS]
            full = full.ljust(_COLS)

            ln_end = len(ln)
            self._text(0,      y, full[:ln_end],       _FG_LINENO,  bg)
            self._text(ln_end, y, full[ln_end:_COLS],  _FG_DEFAULT, bg)

    def _draw_stack(self, stack):
        depth = len(stack)
        label = f' stack ({depth})'.ljust(_COLS)
        self._text(0, _STK_TOP, label, _FG_STKLABEL)

        for i in range(1, _STK_ROWS):   # rows 18-21 — entries
            y   = _STK_TOP + i
            idx = i - 1                 # 0 = top of stack
            if idx < depth:
                val  = stack[-(idx + 1)]
                line = f'  {idx}: {val!r}'[:_COLS].ljust(_COLS)
                fg   = _FG_STACK0 if idx == 0 else _FG_STACK
            else:
                line = ' ' * _COLS
                fg   = _FG_STACK
            self._text(0, y, line, fg)

    def _draw_output(self):
        line = f' out: {self._last_output}'[:_COLS].ljust(_COLS)
        self._text(0, _OUT_ROW, line, _FG_OUTPUT)

    def _draw_status(self, tok):
        mode = 'STEP' if self._stepping else 'RUN '
        info = f' [{mode}]  ln {tok.line:<4} col {tok.col:<3}  tok: {str(tok.value):<14}'
        keys = '  s step  r run  q quit'
        line = (info + keys)[:_COLS - 1].ljust(_COLS - 1)
        self._text(0, _STATUS_ROW, line, _FG_STATUS)

    def _status_msg(self, msg, error=False):
        fg   = _FG_ERROR if error else _FG_OUTPUT
        line = f' {msg}  (q to close)'[:_COLS - 1].ljust(_COLS - 1)
        self._text(0, _STATUS_ROW, line, fg)
