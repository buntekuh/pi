"""
Pi language interpreter.
=========================

Executes Pi source code directly from the token stream produced by pi_lexer.

Architecture: token-stream walker
----------------------------------
Pi does not build an AST.  Instead, _step() walks the flat token list
produced by the lexer, dispatching on each token type and returning the
index of the *next* token to process.  This architecture was chosen for
three reasons:

    1. Simplicity.  Pi programs are small; there is no need for the
       indirection of allocating and traversing a tree.

    2. Directness.  Control-flow words (if, while) can simply call helper
       methods that walk the token list; there is no 'compile to bytecode'
       phase.

    3. Faithfulness to Forth.  Classic Forth interpreters walk a similar
       flat stream (the 'input buffer'), compiling definitions on the fly.
       Pi's design mirrors that mental model even though it runs on Python
       rather than bare metal.

Cell model
----------
Pi is a 16-bit signed-cell machine.  All arithmetic wraps at ±32767/32768
(two's complement, silent overflow).  The _wrap() method enforces this.

The host language (Python) has arbitrary-precision integers, so overflow
is invisible unless we explicitly mask it.  Every arithmetic result passes
through _wrap() before being pushed.

Fixed-point arithmetic
-----------------------
Pi has no floating-point type.  Programs that need decimal fractions use
fixed-point: an integer scaled by a constant (e.g. SCALE=100 means 7716
represents 77.16).

Because Pi is 16-bit, a naïve fixed-point multiply  a * b  overflows for
any values larger than ~181 when SCALE=100, or ~3 when SCALE=10000.
The */ word provides a 32-bit intermediate:

    a b c */   →   int((a * b) / c)

Python integers are arbitrary precision, so the intermediate product is
exact.  The result is then wrapped to 16-bit.  This single word makes
fixed-point arithmetic feasible on a 16-bit machine.

Dictionary layout
-----------------
All user-defined words and variables are stored in self._dict:

    name  →  ('push', value)          — constants and variables
    name  →  ('word', home_ns, body)  — functions and macros

'push' entries simply push the stored value when executed.  For constants
the value is the constant's integer.  For variables the value is the
cell's address in self._memory (a small dict of int→int).

'word' entries store the home namespace (the value of self._namespace at
definition time, e.g. 'stats.') so that sibling calls within a namespace
work correctly at runtime.  See _call_word_name for the restoration logic.

Namespace scoping
-----------------
namespace math:
    function sq  ( Int -> Int ): -> n:  n n *  end
    function sum-of-squares ( Int Int -> Int ): -> a b:  a sq  b sq  +  end
end

'sq' and 'sum-of-squares' are stored as 'math.sq' and 'math.sum-of-squares'.
When sum-of-squares executes it calls 'sq' by its short name.  At that point
_call_word_name first looks up 'sq', fails, then tries 'math.sq' (because
self._namespace == 'math.' during execution of sum-of-squares).  This
namespace fallback makes sibling calls work without qualification.

Local variables
---------------
'-> a b:' pops values from the stack and binds them to names in the current
frame.  Frames are a stack (self._frames); each word call pushes a fresh
frame and pops it on return, so locals are isolated between calls.

The rightmost name gets the top of stack, matching the natural reading of
a function signature '( Int Int -> )' where the last argument is on top:

    3 7 -> a b:    # a=3, b=7  (7 was on top)

Run directly:
    python3 pi_interp.py examples/hello.pi   # run a file
    python3 pi_interp.py                     # interactive REPL
"""

from __future__ import annotations
import sys
from pi_lexer import Lexer, Token, TT, LexError


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class InterpError(Exception):
    """
    Raised for any runtime error in a Pi program.

    Carries the source location so the interpreter can print a helpful
    message before stopping.  Line and col default to 0 when the error
    originates somewhere that has no associated token (e.g. stack underflow
    detected in a built-in helper).
    """
    def __init__(self, msg: str, line: int = 0, col: int = 0):
        loc = f" (line {line}:{col})" if line else ""
        super().__init__(f"error{loc}: {msg}")
        self.line = line
        self.col  = col


# ---------------------------------------------------------------------------
# Interpreter
# ---------------------------------------------------------------------------

# Control-flow keywords that must NOT be treated as the right-hand side of
# a qualified namespace access.
#
# The interpreter uses a 3-token lookahead  IDENT DOT IDENT  to detect
# namespace access like 'stats.sum'.  Without this guard it would also match
# 'dup . end'  as  'dup.end'  — a nonsensical qualified name — because DOT
# appears between two IDENT tokens.  By requiring the RHS not to be a keyword
# we correctly parse  'dup'  then standalone '.'  then  'end'.
_KEYWORDS = frozenset({
    'if', 'elsif', 'else', 'end',
    'while',
    'function', 'namespace',
    'variable', 'constant',
    'use',
})


class Interpreter:
    """
    Pi language interpreter.

    State
    -----
    stack        The data stack.  All Pi values are on this list.
                 Items are Python ints (for integers) or Python strs
                 (for string values), or Python lists (for list values),
                 or ('quotation', tokens) tuples.

    _out         Output function.  Defaults to sys.stdout.write.  Tests
                 pass a list-appending lambda to capture output without
                 touching stdout.

    _dict        The word dictionary.  Maps name → entry tuple.
                 See 'Dictionary layout' in the module docstring.

    _frames      Stack of local-variable frames.  The bottom frame [0] is
                 the global (module-level) scope; each word call pushes a
                 fresh dict and pops it on return.  A name lookup checks
                 only the *top* frame (_frames[-1]); locals do not shadow
                 across call boundaries.

    _memory      The variable store.  Maps cell-address (int) → cell-value (int).
                 Variables are accessed via @ (fetch) and ! (store).

    _next_addr   Next free cell address.  Incremented each time 'variable'
                 allocates a new cell.

    _namespace   Current definition prefix, e.g. 'stats.' while inside a
                 namespace block.  The empty string '' means global scope.
                 Words are stored as  _namespace + name  in _dict.
    """

    def __init__(self, output=None):
        self.stack:      list            = []
        self._out       = output or (lambda s: sys.stdout.write(s))
        self._dict:      dict            = {}
        self._frames:    list[dict]      = [{}]      # [0] = global frame
        self._memory:    dict[int, int]  = {}
        self._next_addr: int             = 0
        self._namespace: str             = ''

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(self, source: str):
        """
        Lex and execute a Pi source string.

        This is the only public entry point.  The lexer runs first and
        produces the complete token list; then _exec_tokens walks it.
        Splitting lexing from execution means the interpreter never has
        to buffer partial input or deal with lexer state mid-execution.
        """
        tokens = Lexer(source).tokenize()
        self._exec_tokens(tokens, 0)

    # ------------------------------------------------------------------
    # Token execution
    # ------------------------------------------------------------------

    def _exec_tokens(self, tokens: list[Token], start: int) -> int:
        """
        Execute tokens[start:] and return the index where execution stopped.

        The only stopping condition is EOF.  All control-flow words
        (if, while, function, …) call into helper methods that consume
        their own closing tokens and return the next index — so this
        loop never needs to know about block structure.
        """
        i = start
        while i < len(tokens):
            if tokens[i].type == TT.EOF:
                break
            i = self._step(tokens, i)
        return i

    def _step(self, tokens: list[Token], i: int) -> int:
        """
        Execute the token at index i and return the index of the next token.

        This is the central dispatch of the interpreter.  Every kind of
        token has exactly one branch here.  The return value is always the
        index the caller should advance to — for most tokens that is i+1,
        but for compound forms (if, while, function definitions, list
        literals, etc.) it is the index past the entire form.

        Order of dispatch:
            INT, STR   — push literals
            DOT        — standalone Forth print-with-space
            COLON      — : name ... ; macro definition
            ARROW      — -> a b: local binding
            LBRACKET   — [ ... ] list literal
            LBRACE     — { ... } quotation
            IDENT      — keywords, qualified names, locals, dict/builtins
        """
        tok = tokens[i]

        # ---- Integer literal ----------------------------------------
        if tok.type == TT.INT:
            # Wrap to signed 16-bit.  Hex literals arrive unsigned
            # (0..65535); decimals arrive already in signed range but
            # we wrap anyway for consistency.  Example: 0xffff → -1.
            self.stack.append(self._wrap(tok.value))
            return i + 1

        # ---- String literal ----------------------------------------
        if tok.type == TT.STR:
            # Strings are pushed as-is; they are not 16-bit values.
            self.stack.append(tok.value)
            return i + 1

        # ---- Standalone '.' ----------------------------------------
        # In Forth, '.' prints the top of stack with a trailing space.
        # In Pi source, '.' also appears as a namespace separator
        # (stats.sum).  The two uses are disambiguated by the 3-token
        # lookahead in the IDENT branch below, so a DOT token that
        # arrives here is always the standalone print word.
        if tok.type == TT.DOT:
            v = self._pop(tok)
            self._out(str(v) + ' ')
            return i + 1

        # ---- Macro definition: : name ... ; -------------------------
        if tok.type == TT.COLON:
            return self._define_macro(tokens, i)

        # ---- Local-variable assignment: -> a b: --------------------
        # The ARROW token was tokenised from '->'.  We pass i+1 so
        # _exec_assign starts reading the name list, not the arrow itself.
        if tok.type == TT.ARROW:
            return self._exec_assign(tokens, i + 1)

        # ---- List literal: [ ... ] ----------------------------------
        # _read_list starts at i+1 (past '['), executes the contents, and
        # returns the index past ']'.  The net effect on the stack is that
        # all values produced inside the brackets are gathered into a single
        # Python list which is then pushed.
        if tok.type == TT.LBRACKET:
            return self._read_list(tokens, i + 1)

        # ---- Quotation: { ... } -------------------------------------
        # _read_quotation collects raw tokens (without executing them)
        # and pushes a ('quotation', body) tuple.  The quotation is not
        # executed until 'call', 'each', 'map', etc. invoke it.
        if tok.type == TT.LBRACE:
            return self._read_quotation(tokens, i + 1)

        # ---- Identifier / keyword dispatch -------------------------
        if tok.type == TT.IDENT:

            # Control-flow and declaration keywords are checked first.
            # They are NOT in the dictionary — they are handled structurally
            # so that their bodies can reference words not yet defined.
            if tok.value == 'if':
                return self._exec_if(tokens, i + 1)
            if tok.value == 'while':
                return self._exec_while(tokens, i + 1)
            if tok.value == 'function':
                return self._define_function(tokens, i + 1)
            if tok.value == 'namespace':
                return self._exec_namespace(tokens, i + 1)
            if tok.value == 'variable':
                return self._define_variable(tokens, i + 1)
            if tok.value == 'constant':
                return self._define_constant(tokens, i + 1)
            if tok.value == 'use':
                return self._exec_use(tokens, i + 1)

            # Qualified namespace access: stats.sum
            # We look ahead at the next two tokens.  If they are DOT then
            # IDENT (and the IDENT is not a control-flow keyword), we treat
            # the sequence as a qualified name and look up 'lhs.rhs' in _dict.
            #
            # The keyword guard on the RHS prevents  'dup . end'  from being
            # read as  'dup.end'.  (See _KEYWORDS above for the full rationale.)
            if (i + 2 < len(tokens)
                    and tokens[i + 1].type == TT.DOT
                    and tokens[i + 2].type == TT.IDENT
                    and tokens[i + 2].value not in _KEYWORDS):
                return self._call_word_name(
                    tok.value + '.' + tokens[i + 2].value,
                    tokens[i + 2], i + 3)

            # Local variable lookup (current frame only).
            # Locals shadow dictionary words: if 'n' is both a local and a
            # dictionary word, the local wins.  This matches Forth's
            # expectation that named stack items shadow global names.
            if tok.value in self._frames[-1]:
                self.stack.append(self._frames[-1][tok.value])
                return i + 1

            # General word lookup: dictionary then builtins
            return self._call_word_name(tok.value, tok, i + 1)

        raise InterpError(
            f"unexpected token {tok.type.name} {tok.value!r}",
            tok.line, tok.col)

    # ------------------------------------------------------------------
    # Locals and function definitions
    # ------------------------------------------------------------------

    def _exec_assign(self, tokens: list[Token], i: int) -> int:
        """
        Parse  '-> name [name ...] :'  and bind stack values to locals.

        The ARROW token has already been consumed; i points at the first
        name.  We collect all names until we hit a COLON, then pop values
        from the stack in reverse order so that the rightmost name gets
        the top-of-stack value.

        Example:
            3 7 -> a b:
            # names = ['a', 'b']
            # pops: first pop → 7 (top), second pop → 3
            # values after reverse → [3, 7]
            # bindings: a=3, b=7

        This matches the natural reading of a signature '( Int Int -> )'
        where the last-mentioned argument is on top of the stack.

        Bindings go into _frames[-1] (the top frame).  If called at the
        top level (no active function call) this is the global frame;
        inside a function call it is that function's private frame.
        """
        arrow_pos = i - 1   # index of the ARROW token — for error messages
        names: list[str] = []

        # Collect names until ':'
        while i < len(tokens) and tokens[i].type != TT.COLON:
            t = tokens[i]
            if t.type != TT.IDENT:
                raise InterpError(
                    f"expected name in '->' binding, got {t.type.name}",
                    t.line, t.col)
            names.append(t.value)
            i += 1
        if i >= len(tokens) or tokens[i].type != TT.COLON:
            raise InterpError("expected ':' after '->' names")
        i += 1   # skip ':'

        # Pop in reverse so rightmost name = top of stack
        values = [self._pop(tokens[arrow_pos]) for _ in names]
        values.reverse()

        frame = self._frames[-1]
        for name, value in zip(names, values):
            frame[name] = value
        return i

    def _define_function(self, tokens: list[Token], i: int) -> int:
        """
        Parse  'function name ( sig ): body end'  and store in the dictionary.

        The FUNCTION token has already been consumed; i points at the name.

        Steps:
        1. Read the function name.
        2. If a '(' follows, skip the type signature '( ... )' — signatures
           are parsed but ignored at runtime (Pi is dynamically typed for now).
        3. Expect ':' to open the body.
        4. Collect body tokens, tracking nesting depth to find the matching
           'end'.  Nested if/while/function/namespace all increase depth;
           'end' decreases depth; we stop at depth-0 'end'.
        5. Store the body as ('word', home_ns, body) in _dict.

        The home_ns (self._namespace at definition time) is stored with the
        body so that sibling calls within a namespace work at runtime.
        See _call_word_name for how home_ns is used.
        """
        if i >= len(tokens) or tokens[i].type != TT.IDENT:
            raise InterpError("expected function name", tokens[i].line, tokens[i].col)
        name = tokens[i].value
        i += 1

        # Skip optional type signature  ( Int -> Str )
        # We track paren depth to handle nested parens in signatures, though
        # in practice Pi signatures are simple and never nest.
        if i < len(tokens) and tokens[i].type == TT.LPAREN:
            depth = 1
            i += 1
            while i < len(tokens) and depth > 0:
                if tokens[i].type == TT.LPAREN:  depth += 1
                if tokens[i].type == TT.RPAREN:  depth -= 1
                i += 1

        # Expect ':'
        if i >= len(tokens) or tokens[i].type != TT.COLON:
            t = tokens[i] if i < len(tokens) else tokens[-1]
            raise InterpError(f"expected ':' after function signature for '{name}'",
                              t.line, t.col)
        i += 1   # skip ':'

        # Collect body tokens until 'end' at depth 0.
        # 'if', 'while', 'function', and 'namespace' all require a matching
        # 'end', so we track nesting.  'function' and 'namespace' inside a
        # function body are unusual but legal (nested definitions).
        body: list[Token] = []
        depth = 0
        while i < len(tokens):
            t = tokens[i]
            if t.type == TT.EOF:
                raise InterpError(f"unterminated function '{name}'", t.line, t.col)
            if t.type == TT.IDENT:
                if t.value in ('if', 'while', 'function', 'namespace'):
                    depth += 1
                elif t.value == 'end':
                    if depth == 0:
                        i += 1   # skip 'end'
                        break
                    depth -= 1
            body.append(t)
            i += 1

        self._dict[self._namespace + name] = ('word', self._namespace, body)
        return i

    def _call_word_name(self, name: str, tok: Token, next_i: int) -> int:
        """
        Look up 'name' and execute it.  Returns next_i (the caller's next index).

        Lookup order:
        1. _dict[name]            — exact match (includes qualified names)
        2. _dict[_namespace+name] — namespace fallback for sibling calls
           (e.g. calling 'sq' inside 'math.sum-of-squares' finds 'math.sq')
        3. BUILTINS[name]         — built-in Python functions

        Executing a 'push' entry simply pushes the stored value (used for
        variables — pushes the address — and constants — pushes the value).

        Executing a 'word' entry (home_ns, body):
        1. Save the current namespace.
        2. Restore self._namespace to the word's home namespace so sibling
           calls inside the body can find their siblings.
        3. Push a fresh locals frame.
        4. Execute the body.
        5. Pop the locals frame and restore the namespace.

        The try/finally ensures the frames stack is always restored even if
        the body raises an exception.
        """
        entry = self._dict.get(name)

        # Namespace fallback: 'sq' → 'math.sq' when inside math namespace
        if entry is None and self._namespace:
            entry = self._dict.get(self._namespace + name)

        if entry is not None:
            if entry[0] == 'push':
                # Constants and variables just push their value/address
                self.stack.append(entry[1])
            else:
                # ('word', home_ns, body)
                _, home_ns, body = entry
                old_ns = self._namespace
                self._namespace = home_ns   # restore home namespace for sibling calls
                self._frames.append({})     # new locals frame
                try:
                    self._exec_tokens(body, 0)
                finally:
                    self._frames.pop()
                    self._namespace = old_ns
            return next_i

        # Fall through to built-ins
        fn = BUILTINS.get(name)
        if fn is None:
            raise InterpError(f"unknown word '{name}'", tok.line, tok.col)
        fn(self, tok)
        return next_i

    def _define_variable(self, tokens: list[Token], i: int) -> int:
        """
        Parse  'variable name'  and allocate a memory cell.

        'variable name' creates a new cell in self._memory at address
        self._next_addr, initialised to 0, and stores that address in
        _dict as a ('push', addr) entry.  Executing 'name' at runtime
        pushes the address; '@' and '!' then read and write the cell.

        Variables are scoped by namespace: inside 'namespace stats:',
        'variable count' creates 'stats.count'.
        """
        if i >= len(tokens) or tokens[i].type != TT.IDENT:
            t = tokens[i] if i < len(tokens) else tokens[-1]
            raise InterpError("expected name after 'variable'", t.line, t.col)
        name = tokens[i].value
        addr = self._next_addr
        self._next_addr += 1
        self._memory[addr] = 0          # initialise cell to zero
        self._dict[self._namespace + name] = ('push', addr)
        return i + 1

    def _define_constant(self, tokens: list[Token], i: int) -> int:
        """
        Parse  'value constant name'  — the value is on the stack.

        'constant name' pops the current stack top and stores it as a
        ('push', value) entry in _dict.  Executing 'name' at runtime
        pushes the value.  Unlike a variable, a constant has no address
        and cannot be written with '!'.

        This matches the Forth convention:  100 constant SCALE.
        """
        if i >= len(tokens) or tokens[i].type != TT.IDENT:
            t = tokens[i] if i < len(tokens) else tokens[-1]
            raise InterpError("expected name after 'constant'", t.line, t.col)
        name = tokens[i].value
        value = self._pop(tokens[i])
        self._dict[self._namespace + name] = ('push', value)
        return i + 1

    def _exec_namespace(self, tokens: list[Token], i: int) -> int:
        """
        Parse  'namespace name: ... end'  and execute the body with a prefix.

        During the body, self._namespace is set to 'name.' so that all word
        definitions (function, variable, constant, :) are stored with the
        prefix.  After 'end', self._namespace is restored to its previous
        value (which is '' at the top level, allowing nested namespaces in
        principle, though Pi programs rarely use them).

        Note: the body is executed with _exec_body, which treats 'end' as a
        stopper.  The 'end' token is consumed here (i + 1 after _exec_body
        returns).
        """
        if i >= len(tokens) or tokens[i].type != TT.IDENT:
            t = tokens[i] if i < len(tokens) else tokens[-1]
            raise InterpError("expected namespace name", t.line, t.col)
        name = tokens[i].value
        i += 1
        if i >= len(tokens) or tokens[i].type != TT.COLON:
            t = tokens[i] if i < len(tokens) else tokens[-1]
            raise InterpError(f"expected ':' after namespace '{name}'", t.line, t.col)
        i += 1   # skip ':'

        old_ns = self._namespace
        self._namespace = name + '.'
        i, _ = self._exec_body(tokens, i, {'end'})
        self._namespace = old_ns
        return i + 1   # skip 'end'

    def _exec_use(self, tokens: list[Token], i: int) -> int:
        """
        Parse  'use name'  — import all name.* words into unqualified scope.

        For every key in _dict that starts with 'name.', an alias is created
        without the prefix.  This lets you write 'sum' instead of 'stats.sum'
        after  'use stats'.

        Aliases share the same entry tuple (they are not copies), so they
        call the same body and have the same home_ns — sibling calls inside
        the namespace still work correctly after use.
        """
        if i >= len(tokens) or tokens[i].type != TT.IDENT:
            t = tokens[i] if i < len(tokens) else tokens[-1]
            raise InterpError("expected namespace name after 'use'", t.line, t.col)
        name = tokens[i].value
        prefix = name + '.'
        for key, val in list(self._dict.items()):
            if key.startswith(prefix):
                self._dict[key[len(prefix):]] = val
        return i + 1

    # ------------------------------------------------------------------
    # Lists and quotations
    # ------------------------------------------------------------------

    def _read_list(self, tokens: list[Token], i: int) -> int:
        """
        Execute a list literal  '[ expr expr ... ]'.

        i points at the first token inside the brackets (just past '[').
        We record the current stack depth, execute tokens until we hit ']',
        then slice off all values produced by the body and push them as a
        single Python list.

        This means list literals can contain arbitrary Pi expressions:
            [ 1 2 1 1 + ]   produces  [1, 2, 2]

        The stack-depth trick avoids any explicit 'collect' mechanism: we
        just observe what the body added to the stack.
        """
        depth = len(self.stack)   # stack depth before the list body runs
        while i < len(tokens):
            t = tokens[i]
            if t.type == TT.EOF:
                raise InterpError("unterminated list literal", t.line, t.col)
            if t.type == TT.RBRACKET:
                # Gather everything the body added
                items = self.stack[depth:]
                del self.stack[depth:]
                self.stack.append(items)
                return i + 1
            i = self._step(tokens, i)
        raise InterpError("unterminated list literal")

    def _read_quotation(self, tokens: list[Token], i: int) -> int:
        """
        Collect a quotation literal  '{ tokens... }'.

        i points at the first token inside the braces (just past '{').
        Unlike a list, a quotation does NOT execute its contents here —
        it collects the raw tokens and pushes them as:
            ('quotation', [Token, Token, ...])

        The quotation is executed later by 'call', 'each', 'map', etc.
        This deferred execution is what makes quotations work as anonymous
        functions (closures, in a simple sense — they capture no environment,
        but they can reference locals through the frames stack if called in
        the same dynamic extent).

        Nested braces are tracked so that  { { a } b }  correctly produces
        one quotation containing  '{ a } b'  rather than stopping at the
        first '}'.
        """
        body: list[Token] = []
        depth = 0
        while i < len(tokens):
            t = tokens[i]
            if t.type == TT.EOF:
                raise InterpError("unterminated quotation", t.line, t.col)
            if t.type == TT.LBRACE:
                depth += 1         # entering a nested quotation
            elif t.type == TT.RBRACE:
                if depth == 0:
                    # This '}' closes our quotation
                    self.stack.append(('quotation', body))
                    return i + 1
                depth -= 1         # closing a nested quotation
            body.append(t)
            i += 1
        raise InterpError("unterminated quotation")

    def _call_quotation(self, q, tok: Token):
        """
        Execute a quotation value that is already on the stack.

        Validates that q is actually a quotation tuple (not an int or string
        that someone accidentally passed to 'call'), then delegates to
        _exec_tokens.

        No frame push/pop here — that is the caller's responsibility if
        the quotation uses locals.  In practice, quotations that use ->
        bindings push into the *current* frame, which is the enclosing
        function's frame.  This is intentional: quotation locals merge
        with the surrounding context.
        """
        if not (isinstance(q, tuple) and q[0] == 'quotation'):
            raise InterpError(f"expected quotation, got {type(q).__name__}",
                              tok.line, tok.col)
        self._exec_tokens(q[1], 0)

    # ------------------------------------------------------------------
    # Control flow
    # ------------------------------------------------------------------

    def _exec_condition(self, tokens: list[Token], i: int) -> tuple[int, bool]:
        """
        Execute tokens up to and including ':', then pop and return the condition.

        Used by both 'if' and 'while':
            if score 90 >=:   body   end
            while i n <:      body   end
                   ^^^^^^^^^^
                   _exec_condition handles this part

        Returns (index_past_colon, bool(condition_value)).
        In Pi, 0 is false and anything else is true (Forth convention).
        """
        while i < len(tokens) and tokens[i].type != TT.COLON:
            if tokens[i].type == TT.EOF:
                raise InterpError("expected ':' to close condition",
                                  tokens[i].line, tokens[i].col)
            i = self._step(tokens, i)
        if i >= len(tokens) or tokens[i].type != TT.COLON:
            raise InterpError("expected ':' to close condition")
        colon = tokens[i]
        i += 1   # skip ':'
        return i, bool(self._pop(colon))

    def _exec_body(self, tokens: list[Token], i: int,
                   stoppers: set[str]) -> tuple[int, str]:
        """
        Execute tokens until a stopper keyword is reached at the surface level.

        'Surface level' means the stopper is not inside a nested if/while/etc.
        But we do NOT need to track nesting here — _step() handles it.
        When _step() sees 'if' it calls _exec_if (or _skip_body), which
        consumes everything up to and including the matching 'end', and
        returns the index past 'end'.  By the time _exec_body's loop
        advances, the nested block has already been fully consumed.

        Returns (index_of_stopper_token, stopper_name).
        The caller is responsible for consuming the stopper itself.
        """
        while i < len(tokens):
            t = tokens[i]
            if t.type == TT.EOF:
                raise InterpError("unterminated block", t.line, t.col)
            if t.type == TT.IDENT and t.value in stoppers:
                # Found a stopper at the surface — return without consuming it
                return i, t.value
            i = self._step(tokens, i)
        raise InterpError("unterminated block")

    def _skip_body(self, tokens: list[Token], i: int,
                   stoppers: set[str]) -> tuple[int, str]:
        """
        Skip tokens without executing until a stopper at depth 0.

        This is the non-executing counterpart of _exec_body.  It is used
        to skip the bodies of branches that should not execute (e.g. the
        else branch when the if condition is true, or the body of a while
        loop when the condition is false).

        Unlike _exec_body, _skip_body cannot rely on _step to handle nesting
        (because we are not executing).  Instead, it maintains an explicit
        depth counter:
            depth increases for: if, while, function, namespace (all need 'end')
            depth decreases for: end
        Stoppers (elsif, else, end) are only returned when depth == 0.

        Returns (index_of_stopper_token, stopper_name).
        """
        depth = 0
        while i < len(tokens):
            t = tokens[i]
            if t.type == TT.EOF:
                raise InterpError("unterminated block", t.line, t.col)
            if t.type == TT.IDENT:
                if t.value in ('if', 'while', 'function', 'namespace'):
                    depth += 1
                elif t.value == 'end':
                    if depth == 0:
                        return i, 'end'
                    depth -= 1
                elif t.value in stoppers and depth == 0:
                    return i, t.value
            i += 1
        raise InterpError("unterminated block")

    def _skip_past_end(self, tokens: list[Token], i: int) -> int:
        """
        i points to an elsif/else/end token.  Skip to past the matching end.

        After executing the true branch of an if, we need to skip all
        remaining elsif/else branches and consume the final 'end'.
        _skip_body finds the matching 'end' and returns its index;
        we return i+1 to step past it.
        """
        i, _ = self._skip_body(tokens, i, {'end'})
        return i + 1

    def _exec_if(self, tokens: list[Token], i: int) -> int:
        """
        Execute  'if cond: body [elsif cond: body]* [else: body] end'.

        i points to the token after 'if' (the start of the first condition).
        Returns the index past 'end'.

        The loop handles an arbitrary chain of elsif branches:
        1. Execute the condition expression up to ':'.
        2. If true: execute the body, then skip all remaining branches to 'end'.
        3. If false: skip the body to the next branch keyword.
           • 'end'   → no more branches; return.
           • 'else'  → execute the else body; return.
           • 'elsif' → loop back with the next condition.
        """
        while True:
            i, cond = self._exec_condition(tokens, i)

            if cond:
                # Execute the true branch, then skip everything to 'end'
                i, stopper = self._exec_body(tokens, i, {'elsif', 'else', 'end'})
                return self._skip_past_end(tokens, i)

            # Condition false: skip this branch's body to the next keyword
            i, stopper = self._skip_body(tokens, i, {'elsif', 'else', 'end'})

            if stopper == 'end':
                return i + 1   # no more branches
            elif stopper == 'else':
                i += 1   # skip 'else'
                if i < len(tokens) and tokens[i].type == TT.COLON:
                    i += 1   # skip optional ':' after else
                # Execute the else body, then consume 'end'
                i, _ = self._exec_body(tokens, i, {'end'})
                return i + 1   # skip 'end'
            else:
                # 'elsif' — advance past the keyword and loop for the next condition
                i += 1

    def _exec_while(self, tokens: list[Token], i: int) -> int:
        """
        Execute  'while cond: body end'.

        i points to the token after 'while' (the start of the condition).
        Returns the index past 'end'.

        The condition is re-evaluated from cond_start on every iteration.
        When the condition becomes false, _skip_body skips the body and
        returns the 'end' index; we return past it.

        Note: Pi's while loop evaluates the condition as part of the token
        stream, so the condition expression is re-lexed and re-executed on
        every loop iteration.  This is correct: the condition tokens are not
        consumed; they are re-walked each time.
        """
        cond_start = i   # remember where the condition starts for re-evaluation
        while True:
            i, cond = self._exec_condition(tokens, cond_start)

            if not cond:
                # Condition false: skip the body and return past 'end'
                i, _ = self._skip_body(tokens, i, {'end'})
                return i + 1

            # Condition true: execute the body
            i, _ = self._exec_body(tokens, i, {'end'})
            # Reset to condition start for the next iteration
            i = cond_start

    def _define_macro(self, tokens: list[Token], i: int) -> int:
        """
        Parse  ': name tokens... ;'  and store as a word.

        i points at the COLON token itself (not past it).  This is because
        _step dispatches on tok.type == TT.COLON and passes i (not i+1).

        The body is all tokens between the name and the terminating ';'.
        Macros cannot nest (';;' would be malformed Pi) so we don't need
        depth tracking — we just stop at the first SEMI.

        Like functions, macros store their home namespace so sibling calls
        work.  The name is stored as _namespace + name, so a macro defined
        inside 'namespace stats:' becomes 'stats.macro-name'.
        """
        colon_tok = tokens[i]
        i += 1   # skip ':'

        if i >= len(tokens) or tokens[i].type == TT.EOF:
            raise InterpError("expected word name after ':'",
                              colon_tok.line, colon_tok.col)
        name_tok = tokens[i]
        if name_tok.type != TT.IDENT:
            raise InterpError(
                f"expected word name after ':', got {name_tok.type.name}",
                name_tok.line, name_tok.col)
        name = name_tok.value
        i += 1   # skip name

        # Collect body tokens until ';'
        body: list[Token] = []
        while i < len(tokens):
            t = tokens[i]
            if t.type == TT.EOF:
                raise InterpError(f"unterminated definition of '{name}'",
                                  colon_tok.line, colon_tok.col)
            if t.type == TT.SEMI:
                i += 1   # skip ';'
                break
            body.append(t)
            i += 1

        self._dict[self._namespace + name] = ('word', self._namespace, body)
        return i

    # ------------------------------------------------------------------
    # Stack helpers
    # ------------------------------------------------------------------

    def _pop(self, tok: Token | None = None):
        """
        Pop and return the top of the stack.

        Raises InterpError with the token's location if the stack is empty.
        The tok parameter is optional so that internal code (e.g. _exec_assign)
        can call _pop without always having a token on hand.
        """
        if not self.stack:
            line = tok.line if tok else 0
            col  = tok.col  if tok else 0
            raise InterpError("stack underflow", line, col)
        return self.stack.pop()

    def _pop2(self, tok: Token):
        """
        Pop two values and return them as (a, b) where b was on top.

        Used by binary operations:
            a b +   →  _pop2 returns (a, b)
        """
        b = self._pop(tok)
        a = self._pop(tok)
        return a, b

    # ------------------------------------------------------------------
    # 16-bit signed wrapping
    # ------------------------------------------------------------------

    @staticmethod
    def _wrap(v: int) -> int:
        """
        Wrap a Python integer to the 16-bit signed range -32768..32767.

        Step 1: mask to 16 bits (0x0000..0xFFFF).
        Step 2: if the result has the sign bit set (>= 0x8000), subtract
                0x10000 to get the corresponding negative value.

        Examples:
            32768  → 0x8000 → -32768   (overflow wraps to min)
            65535  → 0xFFFF → -1       (0xffff is -1 in two's complement)
            -32769 → 0x7FFF → 32767    (underflow wraps to max)
            42     → 42               (in range, unchanged)

        This is applied to every arithmetic result and to every integer
        pushed from a literal.  It makes Pi silently overflow like a real
        16-bit machine.
        """
        v &= 0xFFFF
        return v - 0x10000 if v >= 0x8000 else v


# ---------------------------------------------------------------------------
# Built-in words
# ---------------------------------------------------------------------------
# Each entry maps a word name to a callable  fn(interp: Interpreter, tok: Token).
# The token is passed for error reporting (line/col).
# Built-ins are the last resort — _call_word_name checks _dict first.

def _arith_op(op):
    """
    Factory for the five basic arithmetic built-ins: + - * / mod.

    Division is truncated toward zero (matching C semantics and the common
    expectation for integer division).  Python's // rounds toward negative
    infinity, so we use  int(a / b)  instead.

    mod is defined consistently:  a - b * int(a / b)
    This matches the truncate-toward-zero convention rather than Python's
    floor-division remainder.

    All results are wrapped to 16-bit signed before being pushed.
    Division and modulo by zero raise InterpError.
    """
    def fn(self, tok):
        a, b = self._pop2(tok)
        if op in ('/', 'mod') and b == 0:
            raise InterpError(
                f"{'division' if op == '/' else 'modulo'} by zero",
                tok.line, tok.col)
        if op == '+':     v = a + b
        elif op == '-':   v = a - b
        elif op == '*':   v = a * b
        elif op == '/':   v = int(a / b)            # truncate toward zero
        elif op == 'mod': v = a - b * int(a / b)    # consistent with /
        self.stack.append(Interpreter._wrap(v))
    return fn

def _cmp_op(pred):
    """
    Factory for comparison built-ins: == != < > <= >=

    Returns -1 for true and 0 for false, following the Forth convention.
    -1 (0xFFFF, all bits set) is the canonical true value; it works
    naturally with bitwise 'and' and 'or'.

    Note: comparisons do NOT wrap — the result is always exactly -1 or 0.
    """
    def fn(self, tok):
        a, b = self._pop2(tok)
        self.stack.append(-1 if pred(a, b) else 0)
    return fn

BUILTINS: dict[str, object] = {
    # ---- Arithmetic ---------------------------------------------------
    '+':   _arith_op('+'),
    '-':   _arith_op('-'),
    '*':   _arith_op('*'),
    '/':   _arith_op('/'),
    'mod': _arith_op('mod'),

    # ---- Unary --------------------------------------------------------
    # 'neg' and 'negate' are synonyms — Pi is forgiving about spelling.
    'neg':    lambda self, tok: self.stack.append(Interpreter._wrap(-self._pop(tok))),
    'negate': lambda self, tok: self.stack.append(Interpreter._wrap(-self._pop(tok))),
    # abs returns the mathematical absolute value (no wrapping needed —
    # the only edge case would be abs(-32768) = 32768 which overflows back,
    # but that is the correct machine behaviour).
    'abs':    lambda self, tok: self.stack.append(abs(self._pop(tok))),

    # ---- Comparison (-1 = true, 0 = false) --------------------------
    '==':  _cmp_op(lambda a, b: a == b),
    '!=':  _cmp_op(lambda a, b: a != b),
    '<':   _cmp_op(lambda a, b: a <  b),
    '>':   _cmp_op(lambda a, b: a >  b),
    '<=':  _cmp_op(lambda a, b: a <= b),
    '>=':  _cmp_op(lambda a, b: a >= b),

    # ---- Logic (bitwise, Forth-style) --------------------------------
    # 'and' and 'or' are bitwise operations, not short-circuit booleans.
    # This matches Forth: -1 & -1 = -1 (true), 0 | -1 = -1 (true).
    'and': lambda self, tok: (lambda a, b: self.stack.append(a & b))(*self._pop2(tok)),
    'or':  lambda self, tok: (lambda a, b: self.stack.append(a | b))(*self._pop2(tok)),
    # 'not' is bitwise NOT — ~(-1) = 0, ~0 = -1.  Wrapped to stay in range.
    'not': lambda self, tok: self.stack.append(Interpreter._wrap(~self._pop(tok))),

    # ---- I/O ---------------------------------------------------------
    # 'print' and 'println' accept either an int or a string; ints are
    # converted via str().  This avoids the need for explicit conversion
    # in simple programs.
    'print':   lambda self, tok: self._out(
                   v if isinstance(v := self._pop(tok), str) else str(v)),
    'println': lambda self, tok: self._out(
                   (v if isinstance(v := self._pop(tok), str) else str(v)) + '\n'),
    # 'emit' outputs one character by ASCII/Unicode code point.
    # Only the low 8 bits are used (& 0xFF) for compatibility with 8-bit usage.
    'emit':    lambda self, tok: self._out(chr(self._pop(tok) & 0xFF)),

    # ---- String / type conversion ------------------------------------
    'int-to-str': lambda self, tok: self.stack.append(str(self._pop(tok))),
    # int-to-hex / int-to-HEX: format as hex string (lower/upper case).
    # & 0xFFFF renders negative numbers as unsigned hex (e.g. -1 → 'ffff').
    'int-to-hex': lambda self, tok: self.stack.append(
                      f'{self._pop(tok) & 0xFFFF:x}'),
    'int-to-HEX': lambda self, tok: self.stack.append(
                      f'{self._pop(tok) & 0xFFFF:X}'),
    # concat: pop two values (str or int), convert both to str, concatenate.
    'concat': lambda self, tok: (
        (lambda a, b: self.stack.append(str(a) + str(b)))(*self._pop2(tok))),
    # length: works on strings (character count) and lists (element count).
    'length': lambda self, tok: self.stack.append(len(self._pop(tok))),

    # ---- Stack inspection --------------------------------------------
    # depth: push the current stack depth BEFORE the push (i.e. depth before 'depth' ran).
    'depth': lambda self, tok: self.stack.append(len(self.stack)),
}


# */ — multiply-divide with a 32-bit intermediate product.
#
# Pi cells are 16-bit signed, so a*b overflows for values as small as
# 183 * 183 = 33489 > 32767.  Fixed-point arithmetic (e.g. SCALE=100 for
# two decimal places) requires multiplying integers by SCALE before dividing,
# which would overflow on any real 16-bit machine.
#
# The solution: use the host language's full integer width for the
# intermediate product.  Python integers are arbitrary precision, so
# a * b is always exact regardless of size.  The final result is then
# wrapped to 16-bit.
#
# Stack effect: ( a b c -- int(a*b/c) )
#
# Example: 355 10000 113 */   →   int(355 * 10000 / 113) = 31415
#          (approximation of pi × 10000 = 31415.926...)
#
# This word is modelled on Forth's  */  with the same semantics.
def _muldiv(self, tok):
    c = self._pop(tok)
    b = self._pop(tok)
    a = self._pop(tok)
    if c == 0:
        raise InterpError("division by zero", tok.line, tok.col)
    self.stack.append(Interpreter._wrap(int((a * b) / c)))

BUILTINS['*/'] = _muldiv


# The stack manipulation words are defined as proper functions rather than
# lambdas because their implementations are multi-line and the lambda form
# becomes unreadable.  They are registered into BUILTINS at the bottom.

def _dup(self, tok):
    """dup  ( a -- a a )  — duplicate top of stack."""
    v = self._pop(tok)
    self.stack.append(v)
    self.stack.append(v)

def _swap(self, tok):
    """swap  ( a b -- b a )  — exchange top two values."""
    a, b = self._pop2(tok)
    self.stack.append(b)
    self.stack.append(a)

def _over(self, tok):
    """over  ( a b -- a b a )  — copy second item to top."""
    b = self._pop(tok)
    a = self._pop(tok)
    self.stack.append(a)
    self.stack.append(b)
    self.stack.append(a)

def _rot(self, tok):
    """rot  ( a b c -- b c a )  — rotate third item to top."""
    c = self._pop(tok)
    b = self._pop(tok)
    a = self._pop(tok)
    self.stack.append(b)
    self.stack.append(c)
    self.stack.append(a)

def _nip(self, tok):
    """nip  ( a b -- b )  — drop second item."""
    b = self._pop(tok)
    self._pop(tok)   # discard a
    self.stack.append(b)

def _drop(self, tok):
    """drop  ( a -- )  — discard top of stack."""
    self._pop(tok)

def _tuck(self, tok):
    """tuck  ( a b -- b a b )  — copy top below second item."""
    b = self._pop(tok)
    a = self._pop(tok)
    self.stack.append(b)
    self.stack.append(a)
    self.stack.append(b)


# str-to-int and hex-to-int follow a two-result convention borrowed from
# Forth: they push the converted value AND a success flag (-1 or 0).
# This lets the caller detect conversion failures without exceptions.
def _str_to_int(self, tok):
    """str-to-int  ( str -- int -1 | 0 0 )  — parse decimal integer."""
    s = str(self._pop(tok))
    try:
        self.stack.append(int(s, 10))
        self.stack.append(-1)   # success
    except ValueError:
        self.stack.append(0)
        self.stack.append(0)    # failure

def _hex_to_int(self, tok):
    """hex-to-int  ( str -- int -1 | 0 0 )  — parse hex integer."""
    s = str(self._pop(tok))
    try:
        self.stack.append(int(s, 16))
        self.stack.append(-1)   # success
    except ValueError:
        self.stack.append(0)
        self.stack.append(0)    # failure

def _nth(self, tok):
    """nth  ( seq idx -- item )  — 0-based indexing into string or list."""
    idx = self._pop(tok)
    s   = self._pop(tok)
    if idx < 0 or idx >= len(s):
        raise InterpError(
            f"index {idx} out of bounds (length {len(s)})",
            tok.line, tok.col)
    self.stack.append(s[idx])

def _format(self, tok):
    """
    format  ( str list -- str )  — substitute list values into '{}' placeholders.

    Example:  "x={} y={}" [ 3 7 ] format   →   "x=3 y=7"

    Each '{}' in the template is replaced left-to-right with the string
    representation of the corresponding list element.  More elements than
    placeholders, or more placeholders than elements, both raise errors.
    """
    args = self._pop(tok)
    tmpl = self._pop(tok)
    if not isinstance(args, list):
        raise InterpError("format: expected list as second argument", tok.line, tok.col)
    result = str(tmpl)
    for a in args:
        idx = result.find('{}')
        if idx < 0:
            raise InterpError("format: more arguments than placeholders", tok.line, tok.col)
        result = result[:idx] + str(a) + result[idx + 2:]
    self.stack.append(result)


# ---- Higher-order list words -----------------------------------------
# These all operate on Python lists (produced by [ ] literals) and
# quotations (produced by { } literals).
#
# Stack effects follow the convention:  ( list quot -- ... )
# 'fold' also takes an initial accumulator:  ( list init quot -- result )

def _call_word(self, tok):
    """call  ( quot -- ... )  — execute a quotation."""
    q = self._pop(tok)
    self._call_quotation(q, tok)

def _each(self, tok):
    """each  ( list quot -- )  — execute quot for each element.
    Each element is pushed before the quotation runs."""
    q   = self._pop(tok)
    lst = self._pop(tok)
    if not isinstance(lst, list):
        raise InterpError("each: expected list", tok.line, tok.col)
    for item in lst:
        self.stack.append(item)
        self._call_quotation(q, tok)

def _map_word(self, tok):
    """map  ( list quot -- list )  — transform each element via quot.
    quot receives one element and must leave exactly one value on the stack."""
    q   = self._pop(tok)
    lst = self._pop(tok)
    if not isinstance(lst, list):
        raise InterpError("map: expected list", tok.line, tok.col)
    result = []
    for item in lst:
        self.stack.append(item)
        self._call_quotation(q, tok)
        result.append(self._pop(tok))
    self.stack.append(result)

def _filter_word(self, tok):
    """filter  ( list quot -- list )  — keep elements where quot returns non-zero."""
    q   = self._pop(tok)
    lst = self._pop(tok)
    if not isinstance(lst, list):
        raise InterpError("filter: expected list", tok.line, tok.col)
    result = []
    for item in lst:
        self.stack.append(item)
        self._call_quotation(q, tok)
        if self._pop(tok):
            result.append(item)
    self.stack.append(result)

def _fold(self, tok):
    """
    fold  ( list init quot -- result )  — left fold over the list.

    quot receives ( acc item ) and must leave one value (the new accumulator).
    The final accumulator is left on the stack.

    Example:  [ 1 2 3 ] 0 { + } fold   →   6

    Note: the accumulator is NOT pushed as a final result separate from the
    stack — it is simply left on top of the stack after the last quotation
    call.  This means quot must leave exactly one extra value each time.
    """
    q    = self._pop(tok)
    init = self._pop(tok)
    lst  = self._pop(tok)
    if not isinstance(lst, list):
        raise InterpError("fold: expected list", tok.line, tok.col)
    self.stack.append(init)   # push initial accumulator
    for item in lst:
        self.stack.append(item)
        self._call_quotation(q, tok)
        # After the quotation, the stack top is the new accumulator.
        # We do NOT pop and re-push it — the quotation's result simply
        # stays on the stack and is consumed as 'acc' in the next iteration.

def _first(self, tok):
    """first  ( list -- item )  — return the first element."""
    lst = self._pop(tok)
    if not isinstance(lst, list) or len(lst) == 0:
        raise InterpError("first: empty list", tok.line, tok.col)
    self.stack.append(lst[0])

def _rest(self, tok):
    """rest  ( list -- list )  — return all elements except the first."""
    lst = self._pop(tok)
    if not isinstance(lst, list):
        raise InterpError("rest: expected list", tok.line, tok.col)
    self.stack.append(lst[1:])

def _cons(self, tok):
    """cons  ( item list -- list )  — prepend item to list."""
    lst  = self._pop(tok)
    item = self._pop(tok)
    if not isinstance(lst, list):
        raise InterpError("cons: expected list", tok.line, tok.col)
    self.stack.append([item] + lst)


def _error_word(self, tok):
    """error  ( str -- )  — raise InterpError with the given message."""
    raise InterpError(str(self._pop(tok)), tok.line, tok.col)

def _panic_word(self, tok):
    """panic  ( str -- )  — like error but prefixes 'panic:' to the message."""
    raise InterpError(f"panic: {self._pop(tok)}", tok.line, tok.col)


def _fetch(self, tok):
    """@  ( addr -- value )  — fetch the value stored at addr.
    Raises if the address has never been written (uninitialised cell)."""
    addr = self._pop(tok)
    if addr not in self._memory:
        raise InterpError(f"fetch from uninitialised address {addr}", tok.line, tok.col)
    self.stack.append(self._memory[addr])

def _store(self, tok):
    """!  ( value addr -- )  — store value at addr.
    The stored value is wrapped to 16-bit signed."""
    addr  = self._pop(tok)
    value = self._pop(tok)
    self._memory[addr] = self._wrap(value)


# Register all the properly-defined functions into BUILTINS.
# This is done in two steps: the lambdas above were registered at dict
# creation time; these functions are registered here to override the
# placeholder lambda versions for dup/swap/over.
BUILTINS.update({
    'dup':        _dup,
    'drop':       _drop,
    'swap':       _swap,
    'over':       _over,
    'rot':        _rot,
    'nip':        _nip,
    'tuck':       _tuck,
    'str-to-int': _str_to_int,
    'hex-to-int': _hex_to_int,
    'nth':        _nth,
    'error':      _error_word,
    'panic':      _panic_word,
    '@':          _fetch,
    '!':          _store,
    'format':     _format,
    'call':       _call_word,
    'each':       _each,
    'map':        _map_word,
    'filter':     _filter_word,
    'fold':       _fold,
    'first':      _first,
    'rest':       _rest,
    'cons':       _cons,
})


# ---------------------------------------------------------------------------
# REPL + CLI
# ---------------------------------------------------------------------------

def repl(interp: Interpreter):
    """
    Interactive Read-Eval-Print Loop.

    Each line of input is lexed and executed as a complete Pi snippet.
    The stack is printed after each successful execution so the programmer
    can see what is on it.  Errors are caught and printed but the interpreter
    state is preserved (the stack is not reset on error).
    """
    print("Pi interpreter — interactive mode.  Ctrl-D to quit.")
    print("Stack is shown after each line.\n")
    while True:
        try:
            line = input("pi> ")
        except EOFError:
            print()
            break
        if not line.strip():
            continue
        try:
            interp.run(line)
        except (LexError, InterpError) as e:
            print(f"  {e}")
            continue
        if interp.stack:
            print(f"  stack: {interp.stack}")
        else:
            print("  stack: (empty)")


if __name__ == '__main__':
    interp = Interpreter()

    if len(sys.argv) > 1:
        # File mode: run a Pi source file
        path = sys.argv[1]
        try:
            with open(path) as f:
                source = f.read()
        except FileNotFoundError:
            print(f"file not found: {path}")
            sys.exit(1)
        try:
            interp.run(source)
        except (LexError, InterpError) as e:
            print(e)
            sys.exit(1)
    else:
        # Interactive mode
        repl(interp)
