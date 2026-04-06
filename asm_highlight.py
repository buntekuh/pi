"""
M56 assembly syntax highlighting and error checking for the T46 editor.

highlight_line(raw_text)  →  list of (start_col, length, rgb_tuple)
check_source(source)      →  list of "line N: …" strings  ([] = clean)

Colour scheme (palette indices)
--------------------------------
  mnemonics   (LOAD ADD JMP …)        26  #6FAAA6  teal
  directives  (.DB .ORG .EQU …)       28  #4998A9  cool blue
  labels def  (LOOP:)                 15  #E29D58  amber
  registers   (R0-R7)                 29  #96C3C9  lighter blue
  conditions  (Z NZ C NC …)           25  #BAD0D1  light blue-green
  immediates  (#42 #0xFF)             14  #D8BA7B  warm gold
  strings     ("hello")               15  #E29D58  amber
  comments    (; …)                   30  #98A6A1  grey-blue
  brackets    ([ ])                   30  #98A6A1  grey-blue
  plain       (label refs, numbers)   11  #E6E9E2  near-white
"""

from palette import PALETTE_DATA as _PAL

# ---------------------------------------------------------------------------
# Palette colours
# ---------------------------------------------------------------------------

_C_MNEMONIC  = _PAL[26]   # teal
_C_DIRECTIVE = _PAL[28]   # cool blue
_C_LABEL_DEF = _PAL[15]   # amber
_C_REGISTER  = _PAL[29]   # lighter blue
_C_CONDITION = _PAL[25]   # light blue-green
_C_IMMEDIATE = _PAL[14]   # warm gold
_C_STRING    = _PAL[15]   # amber
_C_COMMENT   = _PAL[30]   # grey-blue
_C_BRACKET   = _PAL[30]   # grey-blue
_C_DEFAULT   = _PAL[11]   # near-white

HL_DEFAULT   = _PAL[11]   # exported for editor.py

# ---------------------------------------------------------------------------
# Known token sets
# ---------------------------------------------------------------------------

_MNEMONICS = frozenset({
    'LOAD', 'ADD',  'SUB',  'AND',  'OR',   'XOR',  'NOT',
    'SFT',  'SAR',  'MUL',  'DIV',  'SWP',  'JMP',  'CAL',
    'RET',  'PUSH', 'POP',  'NOP',  'HALT', 'OUT',  'IN',
    'LA',   # pseudo-instruction
})

_DIRECTIVES = frozenset({'.DB', '.DW', '.DS', '.ORG', '.EQU'})

_REGISTERS  = frozenset({f'R{i}' for i in range(8)})

_CONDITIONS = frozenset({'Z', 'NZ', 'C', 'NC', 'N', 'NN', 'V', 'AL'})


# ---------------------------------------------------------------------------
# Per-line highlighter
# ---------------------------------------------------------------------------

def highlight_line(raw_text):
    """Return syntax-highlight spans for one raw line of M56 assembly."""
    stripped = raw_text.strip()
    if not stripped:
        return []

    spans = []
    pos   = 0
    n     = len(raw_text)

    # Helper: skip leading whitespace
    def skip_ws():
        nonlocal pos
        while pos < n and raw_text[pos] in ' \t':
            pos += 1

    # Helper: read a token (non-whitespace, non-comma run)
    def read_token():
        nonlocal pos
        start = pos
        while pos < n and raw_text[pos] not in ' \t,;':
            pos += 1
        return start, raw_text[start:pos]

    skip_ws()
    if pos >= n:
        return []

    # Full-line comment
    if raw_text[pos] == ';':
        spans.append((pos, n - pos, _C_COMMENT))
        return spans

    # Check for label definition — a word immediately followed by ':'
    # It can appear alone (LOOP:) or before a mnemonic (LOOP: LOAD …)
    mark = pos
    start, tok = read_token()
    if tok.endswith(':'):
        # label definition (may include the colon)
        spans.append((start, len(tok), _C_LABEL_DEF))
        skip_ws()
        if pos >= n or raw_text[pos] == ';':
            if pos < n:
                spans.append((pos, n - pos, _C_COMMENT))
            return spans
        # fall through to parse the mnemonic on the same line
    else:
        # Not a label — rewind
        pos = mark

    # Mnemonic / directive
    skip_ws()
    start, tok = read_token()
    upper = tok.upper()

    if upper in _MNEMONICS:
        spans.append((start, len(tok), _C_MNEMONIC))
    elif upper in _DIRECTIVES:
        spans.append((start, len(tok), _C_DIRECTIVE))
    else:
        spans.append((start, len(tok), _C_DEFAULT))

    # Operands
    while pos < n:
        skip_ws()
        if pos >= n:
            break

        # Inline comment
        if raw_text[pos] == ';':
            spans.append((pos, n - pos, _C_COMMENT))
            break

        # Skip comma
        if raw_text[pos] == ',':
            pos += 1
            continue

        # String literal (used in .DB)
        if raw_text[pos] == '"':
            start = pos
            pos += 1
            while pos < n:
                if raw_text[pos] == '\\':
                    pos += 2
                    continue
                if raw_text[pos] == '"':
                    pos += 1
                    break
                pos += 1
            spans.append((start, pos - start, _C_STRING))
            continue

        # Opening bracket [Rs+off] or [Rs]
        if raw_text[pos] == '[':
            start = pos
            while pos < n and raw_text[pos] != ']':
                pos += 1
            if pos < n:
                pos += 1   # consume ']'
            bracket_text = raw_text[start:pos]
            # Colour the brackets grey, the register inside lighter blue
            spans.append((start, 1, _C_BRACKET))              # '['
            inner_start = start + 1
            inner       = bracket_text[1:-1]                   # Rs+off or Rs
            # Find register token inside
            reg_end = 0
            while reg_end < len(inner) and inner[reg_end] not in '+]':
                reg_end += 1
            reg_tok = inner[:reg_end].strip().upper()
            if reg_tok in _REGISTERS or reg_tok == 'PC':
                spans.append((inner_start, reg_end, _C_REGISTER))
                if reg_end < len(inner):   # +offset part
                    spans.append((inner_start + reg_end,
                                  len(inner) - reg_end, _C_IMMEDIATE))
            else:
                spans.append((inner_start, len(inner), _C_DEFAULT))
            spans.append((start + len(bracket_text) - 1, 1, _C_BRACKET))  # ']'
            continue

        # Regular token
        start, tok = read_token()
        if not tok:
            break
        upper = tok.upper()
        tok_no_hash = tok.lstrip('#')

        if upper in _REGISTERS:
            spans.append((start, len(tok), _C_REGISTER))
        elif upper in _CONDITIONS:
            spans.append((start, len(tok), _C_CONDITION))
        elif tok.startswith('#'):
            spans.append((start, len(tok), _C_IMMEDIATE))
        elif _is_number(tok_no_hash):
            spans.append((start, len(tok), _C_IMMEDIATE))
        else:
            spans.append((start, len(tok), _C_DEFAULT))   # label ref

    return spans


def _is_number(s):
    """Return True if s looks like a decimal or hex integer."""
    try:
        int(s, 0)
        return True
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Error checker
# ---------------------------------------------------------------------------

def check_source(source):
    """
    Assemble the full source and return a list of error strings.

    Uses AssemblerError which already formats as 'line N: message'.
    Returns [] if the source assembles cleanly.
    """
    from assembler import assemble, AssemblerError
    try:
        assemble(source)
        return []
    except AssemblerError as e:
        return [str(e)]
