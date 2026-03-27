"""
Pi syntax highlighting for the T46 editor.

highlight_line(raw_text)  →  list of (start_col, length, rgb_tuple)

check_source(source)  →  str | None   (error message for LexError, else None)

Colour scheme (palette indices)
--------------------------------
  keywords  (if while end function …)   28  #4998A9  cool blue
  builtins  (dup + @ print …)           26  #6FAAA6  teal
  strings   ("…")                       15  #E29D58  amber
  numbers   (42  0xff)                  14  #D8BA7B  warm gold
  structure (-> : ; )                   25  #BAD0D1  light blue-green
  brackets  ({ } [ ])                   29  #96C3C9  lighter blue
  type-sig  (( ))                       30  #98A6A1  grey-blue
  comments  (// …  /* … */)             30  #98A6A1  grey-blue
  plain     (user words, names)         11  #E6E9E2  near-white
"""

from palette   import PALETTE_DATA as _PAL
from pi_lexer  import Lexer, LexError, TT
from pi_interp import _KEYWORDS, BUILTINS

# ---------------------------------------------------------------------------
# Palette colours
# ---------------------------------------------------------------------------

_C_KEYWORD  = _PAL[28]   # cool blue    — if while end function …
_C_BUILTIN  = _PAL[26]   # teal         — dup + @ print …
_C_STRING   = _PAL[15]   # amber        — "…"
_C_NUMBER   = _PAL[14]   # warm gold    — 42  0xff
_C_STRUCT   = _PAL[25]   # lt blue-grn  — -> : ;
_C_BRACKET  = _PAL[29]   # lighter blue — { } [ ]
_C_TYPESIG  = _PAL[30]   # grey-blue    — ( )
_C_COMMENT  = _PAL[30]   # grey-blue    — // /* */
_C_DEFAULT  = _PAL[11]   # near-white   — user-defined words
HL_DEFAULT  = _PAL[11]   # exported for editor.py

# Map TT → base colour (overridden for IDENT by keyword/builtin check)
_TT_COLOUR = {
    TT.INT:      _C_NUMBER,
    TT.STR:      _C_STRING,
    TT.COLON:    _C_STRUCT,
    TT.SEMI:     _C_STRUCT,
    TT.ARROW:    _C_STRUCT,
    TT.LBRACE:   _C_BRACKET,
    TT.RBRACE:   _C_BRACKET,
    TT.LBRACKET: _C_BRACKET,
    TT.RBRACKET: _C_BRACKET,
    TT.LPAREN:   _C_TYPESIG,
    TT.RPAREN:   _C_TYPESIG,
    TT.DOT:      _C_DEFAULT,
}

# Single-character source length for delimiter tokens
_TT_LEN = {
    TT.COLON:    1,
    TT.SEMI:     1,
    TT.LBRACE:   1,
    TT.RBRACE:   1,
    TT.LBRACKET: 1,
    TT.RBRACKET: 1,
    TT.LPAREN:   1,
    TT.RPAREN:   1,
    TT.DOT:      1,
    TT.ARROW:    2,
}

_BUILTIN_NAMES = frozenset(BUILTINS.keys())


def _colour_for(tok):
    if tok.type == TT.IDENT:
        v = tok.value
        if v in _KEYWORDS:
            return _C_KEYWORD
        if v in _BUILTIN_NAMES:
            return _C_BUILTIN
        return _C_DEFAULT
    return _TT_COLOUR.get(tok.type, _C_DEFAULT)


def _token_source_len(tok, raw, content_end):
    """Best-effort source length for a token starting at tok.col-1."""
    start = tok.col - 1
    tt    = tok.type

    if tt in _TT_LEN:
        return _TT_LEN[tt]

    if tt == TT.IDENT:
        return len(tok.value)

    if tt == TT.INT:
        # Could be decimal (possibly negative) or hex 0x…
        pos = start
        if pos < len(raw) and raw[pos] == '-':
            pos += 1
        if raw[pos:pos+2].lower() == '0x':
            pos += 2
            while pos < len(raw) and raw[pos] in '0123456789abcdefABCDEF':
                pos += 1
        else:
            while pos < len(raw) and raw[pos].isdigit():
                pos += 1
        return max(1, pos - start)

    if tt == TT.STR:
        # Walk the raw source to find the closing unescaped quote.
        pos = start
        if pos < len(raw) and raw[pos] == '"':
            pos += 1
            while pos < len(raw):
                if raw[pos] == '\\':
                    pos += 2
                    continue
                if raw[pos] == '"':
                    pos += 1
                    break
                pos += 1
        return max(1, pos - start)

    return 1


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def highlight_line(raw_text):
    """
    Return syntax-highlight spans for one raw line of Pi source.

    Returns list of (start_col, length, rgb_tuple).  start_col is 0-based.
    Only non-default coloured spans are returned; gaps use HL_DEFAULT.
    """
    # Fast path: blank line
    stripped = raw_text.strip()
    if not stripped:
        return []

    # Detect line comment before lexing (avoids LexError on bare //)
    comm = _find_line_comment(raw_text)
    if comm == 0:
        return [(0, len(raw_text), _C_COMMENT)]

    content_end = len(raw_text.rstrip())

    try:
        tokens = Lexer(raw_text + '\n').tokenize()
    except LexError:
        return []

    spans = []
    for tok in tokens:
        if tok.type == TT.EOF:
            break
        start = tok.col - 1       # 0-based
        if start >= content_end:
            break

        colour = _colour_for(tok)
        length = min(_token_source_len(tok, raw_text, content_end),
                     content_end - start)
        if length <= 0:
            continue

        spans.append((start, length, colour))

        # Colour the inline comment that follows the last real token
        if comm is not None and start + length >= comm:
            break

    if comm is not None:
        spans.append((comm, content_end - comm, _C_COMMENT))

    return spans


def _find_line_comment(raw):
    """Return 0-based index of '//' not inside a string, or None."""
    in_str = False
    i = 0
    while i < len(raw):
        ch = raw[i]
        if in_str:
            if ch == '\\':
                i += 2
                continue
            if ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif raw[i:i+2] == '//':
                return i
        i += 1
    return None


# Type-annotation words used in function signatures ( Int Str -> ).
# These are not builtins or keywords but are always valid.
_TYPE_WORDS = frozenset({'Int', 'Str', 'Bool', 'List', 'Any'})


def check_source(source):
    """
    Check Pi source and return a list of issue strings, or [].

    Two passes:
      1. Lex — catches bad characters, unclosed strings, etc.
      2. Semantic — flags identifiers that are not keywords, builtins,
         type-annotation words, or names defined in this file.

    Issue format: 'line N:col M: message'  (matches editor _check_line).
    """
    # Pass 1 — lex
    try:
        tokens = Lexer(source).tokenize()
    except LexError as e:
        return [str(e)]

    # Pass 2a — collect all names defined in this file
    defined = set()
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.type == TT.EOF:
            break
        if tok.type == TT.COLON:
            # : NAME … ; — macro definition
            if i + 1 < len(tokens) and tokens[i + 1].type == TT.IDENT:
                defined.add(tokens[i + 1].value)
        elif tok.type == TT.IDENT and tok.value in ('function', 'variable',
                                                     'constant', 'namespace'):
            if i + 1 < len(tokens) and tokens[i + 1].type == TT.IDENT:
                defined.add(tokens[i + 1].value)
        elif tok.type == TT.ARROW:
            # -> name [name …] : — collect local names
            j = i + 1
            while j < len(tokens) and tokens[j].type != TT.COLON:
                if tokens[j].type == TT.IDENT:
                    defined.add(tokens[j].value)
                j += 1
        i += 1

    # Pass 2b — check every IDENT reference
    known    = _KEYWORDS | _BUILTIN_NAMES | _TYPE_WORDS | defined
    issues   = []
    in_sig   = False   # inside ( … ) type signature — skip type words
    in_arrow = False   # inside -> … : binding — names are being defined

    for i, tok in enumerate(tokens):
        if tok.type == TT.EOF:
            break
        if tok.type == TT.LPAREN:
            in_sig = True
            continue
        if tok.type == TT.RPAREN:
            in_sig = False
            continue
        if tok.type == TT.ARROW:
            in_arrow = True
            continue
        if in_arrow and tok.type == TT.COLON:
            in_arrow = False
            continue
        if tok.type != TT.IDENT or in_sig or in_arrow:
            continue

        v = tok.value
        if v in known:
            continue
        # RHS of a qualified namespace access (stats.sum — 'sum' after DOT)
        if i > 0 and tokens[i - 1].type == TT.DOT:
            continue
        # LHS of a qualified access (stats.sum — 'stats' before DOT)
        if i + 1 < len(tokens) and tokens[i + 1].type == TT.DOT:
            continue

        issues.append(f"line {tok.line}:{tok.col}: unknown word '{v}'")

    return issues
