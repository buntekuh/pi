"""
Pi language lexer.
==================

Turns Pi source text into a flat list of Token objects.

Design philosophy
-----------------
Pi is a Forth-dialect that looks like a programming language rather than
assembly.  Its grammar is intentionally simple — almost everything is either
a word (identifier), a literal (integer or string), or a structural
delimiter (:, ;, (, ), {, }, [, ]).

A hand-written recursive-descent lexer is about 200 lines and is trivial to
extend.  Parser generators would be overkill for a grammar this regular and
would hide the '-' disambiguation logic (see below) that is essential to the
language's readability.

Key responsibilities
--------------------
1. Strip whitespace and comments (// line comments, /* */ block comments).
2. Classify each chunk of non-whitespace into one of 14 token types.
3. Record the source location (line, column) of every token so that error
   messages can point at the right place.
4. Enforce machine-range limits on integer literals at lex time so the
   interpreter never sees an out-of-range value.

Disambiguation: the '-' character
----------------------------------
'-' appears in three distinct roles in Pi source:

    -42         negative decimal integer literal
    ->          the ARROW token used in local-variable binding (-> x:)
    - or -xyz   subtraction / operator identifier (e.g. in  : sub   - ;)

The rule is simple: look one character ahead.
    • next char is a digit  → start of a negative decimal literal
    • next char is '>'      → ARROW token (consume both characters)
    • anything else         → fall through to _read_sym / operator handling

Disambiguation: alpha identifiers with hyphens
-----------------------------------------------
Pi uses kebab-case for identifiers: 'count-if', 'go-north', 'int-to-str'.
A hyphen is allowed inside an alpha identifier unless the NEXT character is
'>' — that would be the start of '->'.  So 'count-if' is one token, but
'count-> x:' tokenises as IDENT('count') ARROW IDENT('x') COLON.

Hex literals vs signed decimals
---------------------------------
Decimal literals are stored as signed (-32768..32767) — Pi is a 16-bit
machine and negative literals are common.

Hex literals (0x...) are stored as unsigned (0..65535).  A programmer who
writes 0xffff almost certainly means the bit pattern, not -1.  The
interpreter wraps the value to signed when it pushes it onto the stack, so
0xffff and -1 compare equal at runtime — the distinction is purely in how
you spell it in source.

Run directly to tokenize a file and print the token stream:

    python3 pi_lexer.py examples/test.pi
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional


# ---------------------------------------------------------------------------
# Token types
# ---------------------------------------------------------------------------

class TT(Enum):
    """
    All token types recognised by the Pi lexer.

    There is a token type for each structural delimiter plus the three
    'value-carrying' types (INT, STR, IDENT).  Having an explicit ARROW token
    (instead of just IDENT('->')) allows the interpreter to handle the ->
    binding syntax without any string comparison.

    DOT is its own token type because it appears in two completely different
    roles:
        stats.sum   — namespace separator between two IDENT tokens
        .           — standalone Forth print-with-space word

    The interpreter distinguishes the two by looking at the surrounding
    tokens at parse time (3-token lookahead in _step).
    """
    INT      = auto()   # integer literal  — decimal (signed) or hex (unsigned)
    STR      = auto()   # string literal   — "hello\n"
    IDENT    = auto()   # identifier, keyword, or operator  (go-north, +, dup, if)
    COLON    = auto()   # :  — ends a definition header or condition expression
    SEMI     = auto()   # ;  — ends a : ... ; macro definition
    LPAREN   = auto()   # (  — opens a type signature  ( Int -> Str )
    RPAREN   = auto()   # )  — closes a type signature
    ARROW    = auto()   # -> — begins a local-variable binding  -> x y:
    LBRACE   = auto()   # {  — opens a quotation  { dup * }
    RBRACE   = auto()   # }  — closes a quotation
    LBRACKET = auto()   # [  — opens a list literal  [ 1 2 3 ]
    RBRACKET = auto()   # ]  — closes a list literal
    DOT      = auto()   # .  — namespace separator or standalone print word
    EOF      = auto()   # sentinel; always the last token in the stream


@dataclass
class Token:
    """
    A single lexical unit.

    'value' carries the payload for value tokens:
        INT   → Python int   (decimal: signed; hex: unsigned)
        STR   → Python str   (escape sequences already resolved)
        IDENT → Python str   (the identifier text, e.g. 'count-if')
        all others → None    (the token type is its own information)

    'line' and 'col' are 1-based source coordinates used for error messages.
    They record where the token *starts* in the source text.
    """
    type:  TT
    value: object    # int | str | None
    line:  int
    col:   int

    def __repr__(self) -> str:
        """Pretty representation for CLI debugging output."""
        loc = f"{self.line}:{self.col}"
        if self.value is not None:
            return f"{self.type.name:<10} {self.value!r:<20} @ {loc}"
        return f"{self.type.name:<10} {'':20} @ {loc}"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class LexError(Exception):
    """
    Raised when the lexer encounters input it cannot tokenize.

    Always includes the source location so the user can find the offending
    character.  The interpreter catches LexError and re-raises or prints it
    at the top level.
    """
    def __init__(self, msg: str, line: int, col: int):
        super().__init__(f"line {line}:{col}: {msg}")
        self.line = line
        self.col  = col


# ---------------------------------------------------------------------------
# Character sets
# ---------------------------------------------------------------------------

# Characters that can appear in a symbol-style operator identifier.
# Examples: +  -  *  /  ==  !=  <=  >=  @  !  */
# These never appear in alpha identifiers (which use [a-zA-Z0-9_-]).
# The two character classes are disjoint, which is what lets the lexer
# dispatch on the first character without lookahead.
_SYM = set('+-*/=<>!@&|~^%')

# Single-character punctuation that maps directly to a token type.
# All of these are unambiguous — they can never be part of a longer token.
# ':' and ';' look like they might start an operator, but they are reserved
# delimiters in Pi (Forth's : ... ; definition syntax).
_PUNCT = {
    ':': TT.COLON,
    ';': TT.SEMI,
    '(': TT.LPAREN,
    ')': TT.RPAREN,
    '{': TT.LBRACE,
    '}': TT.RBRACE,
    '[': TT.LBRACKET,
    ']': TT.RBRACKET,
    '.': TT.DOT,
}


# ---------------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------------

class Lexer:
    """
    Hand-written single-pass lexer for the Pi language.

    The lexer is a simple state machine driven by the current character.
    All state is in three instance variables:
        pos   — index into self.src (the raw source string)
        line  — current 1-based line number (updated by _advance on '\\n')
        col   — current 1-based column number (reset to 1 after each newline)

    The public interface is tokenize(), which returns the complete token list
    including a final EOF sentinel.  The interpreter calls Lexer(source).tokenize()
    once and then walks the resulting list; there is no streaming API because
    Pi programs are small and collecting everything upfront simplifies the
    interpreter's lookahead and backtracking.
    """

    def __init__(self, source: str):
        self.src  = source
        self.pos  = 0      # current read position
        self.line = 1      # current line (1-based)
        self.col  = 1      # current column (1-based)

    # ------------------------------------------------------------------

    def tokenize(self) -> list[Token]:
        """
        Convert the entire source into a token list.

        The loop ends when _next() returns an EOF token.  EOF is always
        appended to the list so the interpreter can use it as a sentinel
        without bounds-checking every index access.
        """
        tokens = []
        while True:
            t = self._next()
            tokens.append(t)
            if t.type == TT.EOF:
                break
        return tokens

    # ------------------------------------------------------------------
    # Main dispatch
    # ------------------------------------------------------------------

    def _next(self) -> Token:
        """
        Skip whitespace/comments and return the next token.

        Dispatch is on the first non-whitespace character.  The character
        sets are mutually exclusive, so each branch is a definitive
        identification — no backtracking needed.

        '-' is the only character that requires lookahead beyond one
        character to classify (see the inline comment block below).
        """
        self._skip()   # consume whitespace and comments first

        if self.pos >= len(self.src):
            return Token(TT.EOF, None, self.line, self.col)

        # Snapshot position for the token we are about to produce.
        # We do this before any _advance() call so the location points at
        # the first character of the token, not the character after it.
        line, col = self.line, self.col
        ch = self.src[self.pos]

        # ---- String literal ----------------------------------------
        if ch == '"':
            return self._read_string(line, col)

        # ---- Hex integer: 0x... or 0X... ---------------------------
        # We check for '0' followed by 'x'/'X' before the general digit
        # check so that the '0' doesn't get consumed as a standalone zero.
        if ch == '0' and self._peek() in ('x', 'X'):
            return self._read_hex(line, col)

        # ---- Positive decimal integer ------------------------------
        if ch.isdigit():
            return self._read_decimal(line, col)

        # ---- The '-' disambiguation --------------------------------
        # '-' is ambiguous.  We must look one character ahead:
        #
        #   '-' followed by digit   →  negative decimal literal (-42)
        #   '-' followed by '>'     →  ARROW token  (->)
        #   '-' followed by anything else  →  fall through to _read_sym
        #       which produces IDENT('-') — the subtraction operator —
        #       or a longer operator like '-='  or '->>' (if we ever add those).
        #
        # Note: we do NOT consume '-' here.  If it falls through, _read_sym
        # will consume it (since '-' is in _SYM).
        if ch == '-':
            nxt = self._peek()
            if nxt and nxt.isdigit():
                # Negative literal: _read_decimal handles the '-' sign
                return self._read_decimal(line, col)
            if nxt == '>':
                # Consume both '-' and '>'
                self._advance(); self._advance()
                return Token(TT.ARROW, '->', line, col)
            # Fall through: '-' is treated as a symbol character

        # ---- Alpha identifier: [a-zA-Z_][a-zA-Z0-9_-]* -----------
        # Starts with a letter or underscore.  Digits are not allowed
        # as the first character (they would have been caught above as
        # a decimal literal).
        if ch.isalpha() or ch == '_':
            return self._read_alpha(line, col)

        # ---- Symbol identifier: one or more operator characters ---
        # Anything in _SYM that wasn't caught above (e.g. '+', '*', '==').
        if ch in _SYM:
            return self._read_sym(line, col)

        # ---- Single-character punctuation -------------------------
        # These are all in _PUNCT and cannot be part of a longer token.
        if ch in _PUNCT:
            self._advance()
            return Token(_PUNCT[ch], ch, line, col)

        raise LexError(f"unexpected character {ch!r}", line, col)

    # ------------------------------------------------------------------
    # Readers — one per token class
    # ------------------------------------------------------------------

    def _read_string(self, line: int, col: int) -> Token:
        """
        Read a double-quoted string literal.

        Supported escape sequences:
            \\n  newline       \\t  tab        \\r  carriage return
            \\"  literal "    \\\\  literal \\  \\0  null byte

        Unknown escape sequences  (e.g. \\k)  pass the character through
        unchanged rather than raising an error — a deliberate leniency
        that keeps the lexer simple without surprising the programmer.

        Raises LexError if the string is not terminated before end-of-file.
        """
        self._advance()          # consume opening '"'
        buf = []
        escapes = {
            'n': '\n', 't': '\t', 'r': '\r',
            '"': '"',  '\\': '\\', '0': '\0',
        }
        while self.pos < len(self.src):
            ch = self.src[self.pos]
            if ch == '"':
                self._advance()          # consume closing '"'
                return Token(TT.STR, ''.join(buf), line, col)
            if ch == '\\':
                self._advance()          # consume '\'
                if self.pos >= len(self.src):
                    raise LexError("unterminated escape", line, col)
                esc = self.src[self.pos]
                buf.append(escapes.get(esc, esc))   # unknown → pass through
                self._advance()
            else:
                buf.append(ch)
                self._advance()
        raise LexError("unterminated string literal", line, col)

    def _read_hex(self, line: int, col: int) -> Token:
        """
        Read a hex integer literal: 0x[0-9a-fA-F]+

        The value is stored as an *unsigned* integer in the range 0..65535.
        This is intentional: a programmer who writes 0xffff almost certainly
        means the 16-bit bit pattern, not -1.  The interpreter's _wrap()
        method converts to signed when the value is pushed onto the stack,
        so 0xffff and -1 are equal at runtime.

        Hex digits above 0xffff are rejected at lex time because Pi cells
        are 16-bit and there is no silent truncation — the error should
        happen here, not silently at runtime.
        """
        self._advance(); self._advance()   # consume '0' and 'x'
        start = self.pos
        while self.pos < len(self.src) and self.src[self.pos] in '0123456789abcdefABCDEF':
            self._advance()
        raw = self.src[start:self.pos]
        if not raw:
            raise LexError("empty hex literal", line, col)
        value = int(raw, 16)
        if value > 0xFFFF:
            raise LexError(
                f"hex literal 0x{raw} exceeds 16-bit cell (max 0xffff)", line, col)
        return Token(TT.INT, value, line, col)

    def _read_decimal(self, line: int, col: int) -> Token:
        """
        Read a decimal integer literal, optionally preceded by '-'.

        Decimal literals are stored as *signed* integers in -32768..32767.
        This range matches a 16-bit two's-complement cell.  Values outside
        this range are rejected at lex time.

        Contrast with hex literals (stored unsigned 0..65535) — the
        different storage reflects programmer intent: you write -1 when you
        mean minus one, you write 0xffff when you mean the bit pattern.
        """
        start = self.pos
        if self.src[self.pos] == '-':
            self._advance()   # consume '-'
        while self.pos < len(self.src) and self.src[self.pos].isdigit():
            self._advance()
        value = int(self.src[start:self.pos])
        if value < -32768 or value > 32767:
            raise LexError(
                f"decimal literal {value} out of 16-bit signed range", line, col)
        return Token(TT.INT, value, line, col)

    def _read_alpha(self, line: int, col: int) -> Token:
        """
        Read an alpha identifier: [a-zA-Z_][a-zA-Z0-9_-]*

        Pi uses kebab-case for multi-word identifiers: 'count-if',
        'go-north', 'int-to-str'.  Hyphens are included in the identifier
        unless the next character after the hyphen is '>', which would make
        it the start of the '->' ARROW token.

        Example tokenisation of  'score-> x:'
            IDENT('score')  ARROW('->')  IDENT('x')  COLON

        Example tokenisation of  'count-if'
            IDENT('count-if')   (single token, hyphen is part of the name)

        Note: keywords (if, while, function, …) are returned as ordinary
        IDENT tokens.  The interpreter, not the lexer, handles keywords.
        This keeps the lexer stateless and makes it easy to add new keywords
        without touching the lexer.
        """
        start = self.pos
        while self.pos < len(self.src):
            ch = self.src[self.pos]
            if ch.isalnum() or ch == '_':
                self._advance()
            elif ch == '-' and self._peek() != '>':
                # Hyphen is part of the identifier unless followed by '>'
                self._advance()
            else:
                break
        return Token(TT.IDENT, self.src[start:self.pos], line, col)

    def _read_sym(self, line: int, col: int) -> Token:
        """
        Read a symbol identifier: one or more characters from _SYM.

        Most symbol sequences become IDENT tokens ('+', '-', '==', '*/').
        The one exception is '->' which is canonicalised to ARROW even if it
        is reached through the sym path (which happens when '-' falls through
        the disambiguation in _next because the '-' is in _SYM).

        This dual path for '->' (disambiguation in _next AND canonicalisation
        here) is belt-and-suspenders: _next catches the common case of a
        standalone '->' token in a binding, while _read_sym catches it if it
        appears glued to other sym characters.
        """
        start = self.pos
        while self.pos < len(self.src) and self.src[self.pos] in _SYM:
            self._advance()
        raw = self.src[start:self.pos]
        if raw == '->':
            return Token(TT.ARROW, '->', line, col)
        return Token(TT.IDENT, raw, line, col)

    # ------------------------------------------------------------------
    # Skip whitespace and comments
    # ------------------------------------------------------------------

    def _skip(self):
        """
        Consume whitespace and comments in a loop.

        Both types of comment can follow each other, so we loop until we find
        a character that is neither whitespace nor the start of a comment.

        We do NOT recurse here (even though a block comment ends and might be
        followed by more whitespace) — the outer while loop handles that.
        Recursion would work but would add stack frames for no benefit.

        Block comment nesting is deliberately NOT supported.  Pi is a simple
        language and nested comments are a complexity that has historically
        caused more confusion than convenience in language implementations.
        /* opens a comment; the next */ closes it, unconditionally.
        """
        while self.pos < len(self.src):
            ch = self.src[self.pos]
            if ch in ' \t\r\n':
                # Plain whitespace — advance and continue
                self._advance()
            elif ch == '/' and self._peek() == '/':
                # Line comment: skip everything up to (but not including) the newline.
                # The newline itself will be consumed as whitespace on the next iteration,
                # which correctly updates self.line.
                while self.pos < len(self.src) and self.src[self.pos] != '\n':
                    self._advance()
            elif ch == '/' and self._peek() == '*':
                # Block comment: delegate to _skip_block_comment
                self._skip_block_comment()
            else:
                # Non-whitespace, non-comment: stop skipping
                break

    def _skip_block_comment(self):
        """
        Consume a /* ... */ block comment.

        Saves the opening location for error reporting (if the comment is
        never closed, the error message points at the /* rather than EOF).

        We walk character-by-character rather than using str.find() so that
        _advance() keeps self.line and self.col accurate throughout —
        important because the comment might span multiple lines.

        The loop condition is  pos < len(src) - 1  so that  src[pos + 1]
        is always a valid index when we check for '*/'.  After the loop,
        if we did not return early, the comment was unterminated.
        """
        line, col = self.line, self.col   # save for error message
        self._advance(); self._advance()  # consume '/*'
        while self.pos < len(self.src) - 1:
            if self.src[self.pos] == '*' and self.src[self.pos + 1] == '/':
                self._advance(); self._advance()   # consume '*/'
                return
            self._advance()
        raise LexError("unterminated block comment", line, col)

    # ------------------------------------------------------------------
    # Low-level character helpers
    # ------------------------------------------------------------------

    def _advance(self):
        """
        Consume the current character and update position tracking.

        If the current character is a newline, increment self.line and reset
        self.col to 1 (the column of the first character on the new line).
        Otherwise, just increment self.col.

        All character consumption in the lexer goes through _advance().
        This single chokepoint guarantees that line/col tracking is always
        correct, regardless of which reader method is running.
        """
        if self.pos < len(self.src) and self.src[self.pos] == '\n':
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        self.pos += 1

    def _peek(self, offset: int = 1) -> Optional[str]:
        """
        Look ahead without consuming.

        Returns the character at pos+offset, or None if that position is
        past the end of the source.  The default offset of 1 gives the
        character immediately after the current position.

        Used in three places:
            • '-' disambiguation in _next (look one ahead)
            • '0x' detection in _next (look one ahead past '0')
            • hyphen-in-identifier test in _read_alpha (look one ahead past '-')
        """
        p = self.pos + offset
        return self.src[p] if p < len(self.src) else None


# ---------------------------------------------------------------------------
# CLI — tokenise a file and print the token stream
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else 'examples/test.pi'
    try:
        with open(path) as f:
            source = f.read()
    except FileNotFoundError:
        print(f"file not found: {path}")
        sys.exit(1)

    try:
        tokens = Lexer(source).tokenize()
    except LexError as e:
        print(f"lex error: {e}")
        sys.exit(1)

    print(f"{'TYPE':<12} {'VALUE':<22} LOCATION")
    print("-" * 45)
    for tok in tokens:
        if tok.type == TT.EOF:
            break
        print(tok)
    print(f"\n{len(tokens) - 1} tokens (excluding EOF)")
