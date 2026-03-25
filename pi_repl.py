"""
Pi REPL

Interactive Pi interpreter with a T46-aware fixed status bar that shows
the current stack after every expression.

Layout (when running inside the T46):
  rows 0-22  — scrolling output (results, errors, printed values)
  row  23    — separator line
  row  24    — stack display  "stack: 42 -1 0x1A00 [ 3 items ]"

Same pattern as the debugger and editor.
"""

from pi_interp import Interpreter, InterpError

# ---------------------------------------------------------------------------
# T46 layout constants (must match t46.py)
# ---------------------------------------------------------------------------

_T46_ROWS    = 25
_T46_COLS    = 80
_SCROLL_BOTTOM = _T46_ROWS - 3      # rows 0-22 scroll; 23-24 are fixed

_SEP  = "-" * (_T46_COLS - 1)
_HINT = "  Pi REPL  |  q / quit  |  stack bottom → top"


# ---------------------------------------------------------------------------
# Value formatting
# ---------------------------------------------------------------------------

def _fmt(v) -> str:
    """Format a single stack value for display."""
    if isinstance(v, int):
        if -9999 <= v <= 9999:
            return str(v)
        return hex(v)
    if isinstance(v, str):
        return repr(v)
    if isinstance(v, list):
        return f"[list/{len(v)}]"
    if isinstance(v, tuple) and v and v[0] == 'quotation':
        return "[quot]"
    return repr(v)


def _stack_line(stack) -> str:
    """Build the one-line stack summary for the status bar."""
    n = len(stack)
    if n == 0:
        return "stack: (empty)".ljust(_T46_COLS - 1)
    # Show at most 6 values, bottom → top, truncated from the left if needed.
    shown = stack[-6:]
    parts = "  ".join(_fmt(v) for v in shown)
    prefix = "... " if n > 6 else ""
    count  = f"  [ {n} ]"
    line   = f"stack: {prefix}{parts}{count}"
    return line[:_T46_COLS - 1].ljust(_T46_COLS - 1)


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------

class PiRepl:
    """
    Interactive Pi REPL.

    When term is provided the same fixed-bar layout as the debugger is used:
    scroll region keeps rows 23-24 pinned while output scrolls above.
    println / read_line default to plain stdin/stdout for CLI use.
    """

    def __init__(self, println=None, read_line=None, term=None):
        self._w    = println   or print
        self._r    = read_line or input
        self._term = term
        self._interp = Interpreter(output=self._emit)

    def _emit(self, text):
        """Called by the Pi interpreter for 'print' output."""
        self._w(text)

    # ------------------------------------------------------------------
    # T46 status bar
    # ------------------------------------------------------------------

    def _draw_status(self):
        t = self._term
        t.receive({"type": "goto", "row": _T46_ROWS - 2, "col": 0})
        t.receive({"type": "print", "text": _SEP})
        t.receive({"type": "goto", "row": _T46_ROWS - 1, "col": 0})
        t.receive({"type": "print", "text": _HINT.ljust(_T46_COLS - 1)})

    def _draw_stack(self):
        if not self._term:
            return
        t = self._term
        t.receive({"type": "goto", "row": _T46_ROWS - 1, "col": 0})
        t.receive({"type": "print", "text": _stack_line(self._interp.stack)})

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def loop(self):
        if self._term:
            self._term.receive({"type": "cls"})
            self._term.receive({"type": "scroll_region", "bottom": _SCROLL_BOTTOM})
            self._draw_status()
            self._term.receive({"type": "goto", "row": 0, "col": 0})

        self._w("")
        self._w("Pi REPL  (type 'q' or 'quit' to exit)")
        self._w("")

        while True:
            # Redraw stack bar before each prompt so it always reflects the
            # current state even if the last command printed output.
            self._draw_stack()

            try:
                self._w("(pi) ")
                line = self._r().strip()
            except (EOFError, KeyboardInterrupt):
                self._w("")
                break

            if line in ("q", "quit", "exit"):
                break

            if not line:
                continue

            try:
                self._interp.run(line)
            except InterpError as e:
                self._w(f"  error: {e}")
            except Exception as e:
                self._w(f"  internal error: {e}")

            # Redraw stack immediately after execution so the result is
            # visible before the next prompt appears.
            self._draw_stack()

        if self._term:
            self._term.receive({"type": "scroll_region", "bottom": _T46_ROWS - 1})
            self._term.receive({"type": "cls"})
