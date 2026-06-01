package lexer

import (
	"fmt"
	"strings"
	"unicode"
)

// lexer holds the mutable state for a single tokenization run.
//
// The source is stored as []rune rather than []byte so that Unicode characters
// (which may appear directly in Grue strings) are handled naturally.
//
// The indents field is a stack of column numbers representing the current
// nesting of indentation levels. It always has at least one entry (0) for the
// top-level scope. When a block opens, the new column number is pushed; when
// it closes, it is popped and a DEDENT token is emitted.
type lexer struct {
	src     []rune
	pos     int
	line    int
	col     int
	indents []int // stack of indent column numbers; [0] = base level
}

// Tokenize is the public entry point. It converts a complete Grue source file
// into a flat slice of tokens ending with EOF.
//
// Line endings are normalised to \n before lexing, so the rest of the lexer
// only ever sees \n as a line terminator regardless of the source platform.
func Tokenize(source string) ([]Token, error) {
	source = strings.ReplaceAll(source, "\r\n", "\n")
	source = strings.ReplaceAll(source, "\r", "\n")

	l := &lexer{
		src:     []rune(source),
		line:    1,
		col:     1,
		indents: []int{0}, // base indent level is column 0
	}
	return l.run()
}

// =============================================================================
// Navigation helpers
// =============================================================================

func (l *lexer) atEnd() bool {
	return l.pos >= len(l.src)
}

// current returns the character at the current position without advancing.
// Returns 0 at end of source so callers can use it as a sentinel.
func (l *lexer) current() rune {
	if l.atEnd() {
		return 0
	}
	return l.src[l.pos]
}

// advance consumes and returns the current character, updating line/col tracking.
// A newline increments the line counter and resets col to 1 for the next character.
func (l *lexer) advance() rune {
	ch := l.src[l.pos]
	l.pos++
	if ch == '\n' {
		l.line++
		l.col = 1
	} else {
		l.col++
	}
	return ch
}

// =============================================================================
// Main loop
// =============================================================================

// run drives the top-level lexing loop. It processes the source line by line:
//
//  1. Skip blank and comment-only lines (they do not affect indentation).
//  2. Count the leading spaces of the next real line and emit INDENT/DEDENT.
//  3. Lex all tokens on that line.
//  4. Emit NEWLINE and advance past the line terminator.
//
// After the source is exhausted, any open indent levels are closed with DEDENT
// tokens and a final EOF is appended.
func (l *lexer) run() ([]Token, error) {
	var tokens []Token

	for {
		// Step 1: skip blank and comment-only lines.
		// These lines contribute nothing to the token stream — not even NEWLINE.
		// This matches how Grue authors expect blank lines to behave: they can
		// freely add blank lines between handlers or inside class bodies for
		// readability without accidentally closing blocks.
		for !l.atEnd() && l.isBlankLine() {
			l.skipLine()
		}
		if l.atEnd() {
			break
		}

		// Step 2: measure and consume the leading indentation of this real line.
		indent := l.countIndent()

		// Emit INDENT or DEDENT token(s) based on how this line's indent
		// compares to the current top of the indent stack.
		itoks, err := l.handleIndent(indent)
		if err != nil {
			return nil, err
		}
		tokens = append(tokens, itoks...)

		// Step 3: lex tokens until end of line.
		for !l.atEnd() && l.current() != '\n' {
			// Skip whitespace between tokens on the same line.
			if l.current() == ' ' || l.current() == '\t' {
				l.advance()
				continue
			}
			// An inline comment (#) ends the token stream for this line.
			// The comment itself is discarded — it carries no semantic meaning.
			if l.current() == '#' {
				for !l.atEnd() && l.current() != '\n' {
					l.advance()
				}
				break
			}
			tok, err := l.lexToken()
			if err != nil {
				return nil, err
			}
			tokens = append(tokens, tok)
		}

		// Step 4: emit NEWLINE to mark end of this logical line, then consume \n.
		// The parser uses NEWLINE to terminate statements; Grue has no semicolons.
		tokens = append(tokens, Token{NEWLINE, "", l.line, l.col})
		if !l.atEnd() {
			l.advance() // consume the \n
		}
	}

	// Close any blocks that were still open at end of file.
	// For example, the last handler in a file has no following line to trigger
	// its DEDENT, so we emit them here.
	for len(l.indents) > 1 {
		tokens = append(tokens, Token{DEDENT, "", l.line, l.col})
		l.indents = l.indents[:len(l.indents)-1]
	}

	tokens = append(tokens, Token{EOF, "", l.line, l.col})
	return tokens, nil
}

// =============================================================================
// Line classification and indentation
// =============================================================================

// isBlankLine reports whether the current line contains no tokens — only
// optional whitespace followed by a comment, newline, or end of source.
// It does not advance the position.
func (l *lexer) isBlankLine() bool {
	i := l.pos
	for i < len(l.src) && (l.src[i] == ' ' || l.src[i] == '\t') {
		i++
	}
	return i >= len(l.src) || l.src[i] == '\n' || l.src[i] == '#'
}

// skipLine advances past the current line, consuming the trailing newline.
// Used to discard blank and comment-only lines.
func (l *lexer) skipLine() {
	for !l.atEnd() && l.current() != '\n' {
		l.advance()
	}
	if !l.atEnd() {
		l.advance() // consume \n
	}
}

// countIndent consumes and counts the leading spaces on the current line.
// Only spaces are counted; tabs in indentation are not supported.
func (l *lexer) countIndent() int {
	count := 0
	for !l.atEnd() && l.current() == ' ' {
		l.advance()
		count++
	}
	return count
}

// handleIndent compares the given indent level against the top of the indent
// stack and emits INDENT or DEDENT tokens as needed.
//
// The indent stack always holds the column number of each currently open block.
// Pushing a new level opens a block; popping closes it.
//
// Example: if the stack is [0, 4] and the new indent is 8, we push 8 and emit
// one INDENT. If the new indent is 0, we pop 8 and 4 and emit two DEDENTs.
//
// An indent that does not match any level on the stack is a syntax error —
// for example, dedenting to column 2 when the stack holds [0, 4] is illegal.
func (l *lexer) handleIndent(indent int) ([]Token, error) {
	var tokens []Token
	top := l.indents[len(l.indents)-1]

	switch {
	case indent > top:
		// New block opened.
		l.indents = append(l.indents, indent)
		tokens = append(tokens, Token{INDENT, "", l.line, 1})

	case indent < top:
		// One or more blocks closed. Pop until the stack top matches.
		for len(l.indents) > 1 && l.indents[len(l.indents)-1] > indent {
			l.indents = l.indents[:len(l.indents)-1]
			tokens = append(tokens, Token{DEDENT, "", l.line, 1})
		}
		// After popping, the top must exactly match the target indent.
		// If it doesn't, the author has used a column number that was never
		// opened, which is an indentation error.
		if l.indents[len(l.indents)-1] != indent {
			return nil, fmt.Errorf("line %d: inconsistent indentation", l.line)
		}
	// case indent == top: nothing to emit, same block continues.
	}

	return tokens, nil
}

// =============================================================================
// Token dispatch
// =============================================================================

// lexToken dispatches to the appropriate lexer based on the current character.
func (l *lexer) lexToken() (Token, error) {
	ch := l.current()
	switch {
	case ch == '"':
		return l.lexString()
	case unicode.IsDigit(ch):
		return l.lexNumber(), nil
	case unicode.IsLetter(ch) || ch == '_':
		return l.lexWord(), nil
	default:
		return l.lexOperator()
	}
}

// =============================================================================
// Individual token lexers
// =============================================================================

// lexString lexes a double-quoted string literal.
//
// Multi-line strings: a newline inside a string followed by any amount of
// whitespace is collapsed to a single space. This allows long room descriptions
// and messages to be wrapped across source lines for readability without
// affecting the output text.
//
//	Room drawing room "A long description that wraps
//	    across two lines."
//	→ "A long description that wraps across two lines."
//
// String interpolation ({...}) and inline directives ([...]) are preserved
// verbatim in the token value. The parser resolves them in a later pass.
func (l *lexer) lexString() (Token, error) {
	line, col := l.line, l.col
	l.advance() // consume opening "

	var buf strings.Builder

	for !l.atEnd() {
		ch := l.current()

		switch ch {
		case '"':
			// Closing quote — string complete.
			l.advance()
			return Token{STRING, buf.String(), line, col}, nil

		case '\n':
			// Multi-line continuation: skip the newline and all following
			// whitespace, then insert a single space — but only if the buffer
			// is non-empty and does not already end in a space, and we are not
			// about to hit the closing quote.
			l.advance()
			for !l.atEnd() && (l.current() == ' ' || l.current() == '\t') {
				l.advance()
			}
			s := buf.String()
			if len(s) > 0 && s[len(s)-1] != ' ' && l.current() != '"' {
				buf.WriteByte(' ')
			}

		default:
			buf.WriteRune(ch)
			l.advance()
		}
	}

	return Token{}, fmt.Errorf("%d:%d: unterminated string", line, col)
}

// lexNumber lexes an integer literal. Grue has no floating-point literals;
// floats exist only as intermediate values during arithmetic evaluation.
// The digit string is stored as-is; the parser converts it to int.
func (l *lexer) lexNumber() Token {
	line, col := l.line, l.col
	var buf strings.Builder
	for !l.atEnd() && unicode.IsDigit(l.current()) {
		buf.WriteRune(l.advance())
	}
	return Token{NUMBER, buf.String(), line, col}
}

// lexWord lexes a word — any run of letters, digits, and underscores starting
// with a letter or underscore.
//
// All keywords (on, fail, kind, class, Room, Object, ...) and all identifier
// parts (brass, lantern, sad, lit, ...) are emitted as plain WORD tokens.
// The parser uses context to distinguish keywords from names.
//
// Special case: the word "js" followed by "{" triggers lexJSBlock, which
// captures the entire JavaScript block as a single JS_BLOCK token rather than
// trying to lex JavaScript with the Grue operator set.
func (l *lexer) lexWord() Token {
	line, col := l.line, l.col
	var buf strings.Builder
	for !l.atEnd() && (unicode.IsLetter(l.current()) || unicode.IsDigit(l.current()) || l.current() == '_') {
		buf.WriteRune(l.advance())
	}
	word := buf.String()

	// Check for js { } escape block. Skip any whitespace between "js" and "{".
	if word == "js" {
		for !l.atEnd() && (l.current() == ' ' || l.current() == '\t') {
			l.advance()
		}
		if !l.atEnd() && l.current() == '{' {
			return l.lexJSBlock(line, col)
		}
	}

	return Token{WORD, word, line, col}
}

// lexJSBlock captures a raw JavaScript block between matching braces.
//
// When Grue source contains js { ... }, the content is arbitrary JavaScript
// that the Grue lexer cannot understand (single quotes, semicolons, etc.).
// Rather than trying to tokenize it, we capture everything between the braces
// as a single opaque JS_BLOCK token. Brace depth is tracked so nested JS
// objects and function literals ({ key: { value: 1 } }) are handled correctly.
//
// The captured content is whitespace-trimmed. The opening { has already been
// confirmed by the caller; this function consumes it and the matching }.
func (l *lexer) lexJSBlock(line, col int) Token {
	l.advance() // consume opening {
	var buf strings.Builder
	depth := 1 // we are one brace deep

	for !l.atEnd() && depth > 0 {
		ch := l.advance()
		switch ch {
		case '{':
			depth++
			buf.WriteRune(ch)
		case '}':
			depth--
			if depth > 0 {
				// Inner closing brace — still inside the block.
				buf.WriteRune(ch)
			}
			// Outermost closing brace is consumed but not written.
		default:
			buf.WriteRune(ch)
		}
	}

	return Token{JS_BLOCK, strings.TrimSpace(buf.String()), line, col}
}

// lexOperator lexes a one- or two-character operator or punctuation token.
// Two-character operators (==, +=, -=, <=, >=) are matched greedily by
// peeking at the character following the first.
func (l *lexer) lexOperator() (Token, error) {
	line, col := l.line, l.col
	ch := l.advance()

	switch ch {
	case '=':
		if !l.atEnd() && l.current() == '=' {
			l.advance()
			return Token{EQEQ, "==", line, col}, nil
		}
		return Token{EQ, "=", line, col}, nil
	case '+':
		if !l.atEnd() && l.current() == '=' {
			l.advance()
			return Token{PLUSEQ, "+=", line, col}, nil
		}
		return Token{PLUS, "+", line, col}, nil
	case '-':
		if !l.atEnd() && l.current() == '=' {
			l.advance()
			return Token{MINUSEQ, "-=", line, col}, nil
		}
		return Token{MINUS, "-", line, col}, nil
	case '*':
		// * is multiplication in expressions and the default-value marker in
		// kind declarations (kind mood: happy, *neutral, sad). The parser
		// distinguishes the two uses by context.
		return Token{STAR, "*", line, col}, nil
	case '/':
		return Token{SLASH, "/", line, col}, nil
	case '<':
		if !l.atEnd() && l.current() == '=' {
			l.advance()
			return Token{LTE, "<=", line, col}, nil
		}
		return Token{LT, "<", line, col}, nil
	case '>':
		if !l.atEnd() && l.current() == '=' {
			l.advance()
			return Token{GTE, ">=", line, col}, nil
		}
		return Token{GT, ">", line, col}, nil
	case ':':
		return Token{COLON, ":", line, col}, nil
	case '.':
		// . is used for property access (lamp.light) and as the separator in
		// test assertions (open rolodex at 3. "Opened"). The parser determines
		// which role it plays from context.
		return Token{DOT, ".", line, col}, nil
	case ',':
		return Token{COMMA, ",", line, col}, nil
	case '(':
		return Token{LPAREN, "(", line, col}, nil
	case ')':
		return Token{RPAREN, ")", line, col}, nil
	case '{':
		// { outside a string is dynamic property access (log.{position}) or
		// an inline handler call ({has ledger silently}).
		return Token{LBRACE, "{", line, col}, nil
	case '}':
		return Token{RBRACE, "}", line, col}, nil
	case '[':
		// [ outside a string is array/index syntax (not currently used at the
		// top level; reserved for future use or inside interpolated expressions).
		return Token{LBRACKET, "[", line, col}, nil
	case ']':
		return Token{RBRACKET, "]", line, col}, nil
	}

	return Token{}, fmt.Errorf("%d:%d: unexpected character %q", line, col, ch)
}
