"""
Markdown syntax highlighting for the T46 editor.

highlight_line(raw_text)  →  list of (start_col, length, rgb_tuple)

Colour scheme (palette indices)
--------------------------------
  headers   (# ## ###)    28  #4998A9  cool blue
  bold      (**...**)     15  #E29D58  orange/amber
  italic    (*...*)       10  #7D997E  muted green
  plain                   11  #E6E9E2  near-white
"""

from palette import PALETTE_DATA as _PAL

_C_HEADER  = _PAL[28]   # cool blue
_C_BOLD    = _PAL[15]   # orange/amber
_C_ITALIC  = _PAL[10]   # muted green
_C_DEFAULT = _PAL[11]   # near-white

HL_DEFAULT = _PAL[11]   # exported for editor.py


def highlight_line(raw_text):
    """Return syntax-highlight spans for one raw line of Markdown."""
    stripped = raw_text.strip()
    if not stripped:
        return []

    n = len(raw_text)

    # Header: line whose first non-space content begins with '#'
    if stripped[0] == '#':
        lead = n - len(raw_text.lstrip())
        return [(lead, n - lead, _C_HEADER)]

    spans = []
    pos   = 0

    while pos < n:
        # Bold: **...** (check before single *)
        if raw_text[pos:pos + 2] == '**':
            close = raw_text.find('**', pos + 2)
            if close != -1:
                spans.append((pos, close + 2 - pos, _C_BOLD))
                pos = close + 2
                continue

        # Bold: __...__  (check before single _)
        if raw_text[pos:pos + 2] == '__':
            close = raw_text.find('__', pos + 2)
            if close != -1:
                spans.append((pos, close + 2 - pos, _C_BOLD))
                pos = close + 2
                continue

        # Italic: *...*
        if raw_text[pos] == '*':
            close = raw_text.find('*', pos + 1)
            if close != -1:
                spans.append((pos, close + 1 - pos, _C_ITALIC))
                pos = close + 1
                continue

        # Italic: _..._
        if raw_text[pos] == '_':
            close = raw_text.find('_', pos + 1)
            if close != -1:
                spans.append((pos, close + 1 - pos, _C_ITALIC))
                pos = close + 1
                continue

        pos += 1

    return spans
