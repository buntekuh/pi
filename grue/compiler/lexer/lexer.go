package lexer

import (
	"fmt"
	"strings"
	"unicode"
)

type lexer struct {
	src     []rune
	pos     int
	line    int
	col     int
	indents []int // stack of indent column numbers
}

// Tokenize converts Grue source text into a flat token stream.
func Tokenize(source string) ([]Token, error) {
	// Normalize line endings
	source = strings.ReplaceAll(source, "\r\n", "\n")
	source = strings.ReplaceAll(source, "\r", "\n")

	l := &lexer{
		src:     []rune(source),
		line:    1,
		col:     1,
		indents: []int{0},
	}
	return l.run()
}

// --- navigation ---

func (l *lexer) atEnd() bool {
	return l.pos >= len(l.src)
}

func (l *lexer) current() rune {
	if l.atEnd() {
		return 0
	}
	return l.src[l.pos]
}

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

// --- main loop ---

func (l *lexer) run() ([]Token, error) {
	var tokens []Token

	for {
		// Skip blank and comment-only lines
		for !l.atEnd() && l.isBlankLine() {
			l.skipLine()
		}
		if l.atEnd() {
			break
		}

		// Count and consume leading spaces
		indent := l.countIndent()

		// Emit INDENT / DEDENT
		itoks, err := l.handleIndent(indent)
		if err != nil {
			return nil, err
		}
		tokens = append(tokens, itoks...)

		// Lex tokens to end of line
		for !l.atEnd() && l.current() != '\n' {
			if l.current() == ' ' || l.current() == '\t' {
				l.advance()
				continue
			}
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

		// Emit NEWLINE and consume the \n
		tokens = append(tokens, Token{NEWLINE, "", l.line, l.col})
		if !l.atEnd() {
			l.advance()
		}
	}

	// Close any remaining open indents
	for len(l.indents) > 1 {
		tokens = append(tokens, Token{DEDENT, "", l.line, l.col})
		l.indents = l.indents[:len(l.indents)-1]
	}

	tokens = append(tokens, Token{EOF, "", l.line, l.col})
	return tokens, nil
}

// isBlankLine returns true if the rest of the current line is empty or a comment.
func (l *lexer) isBlankLine() bool {
	i := l.pos
	for i < len(l.src) && (l.src[i] == ' ' || l.src[i] == '\t') {
		i++
	}
	return i >= len(l.src) || l.src[i] == '\n' || l.src[i] == '#'
}

// skipLine advances past the current line including the trailing newline.
func (l *lexer) skipLine() {
	for !l.atEnd() && l.current() != '\n' {
		l.advance()
	}
	if !l.atEnd() {
		l.advance()
	}
}

// countIndent consumes leading spaces and returns the count.
func (l *lexer) countIndent() int {
	count := 0
	for !l.atEnd() && l.current() == ' ' {
		l.advance()
		count++
	}
	return count
}

// handleIndent emits INDENT / DEDENT tokens by comparing indent to the stack.
func (l *lexer) handleIndent(indent int) ([]Token, error) {
	var tokens []Token
	top := l.indents[len(l.indents)-1]

	switch {
	case indent > top:
		l.indents = append(l.indents, indent)
		tokens = append(tokens, Token{INDENT, "", l.line, 1})
	case indent < top:
		for len(l.indents) > 1 && l.indents[len(l.indents)-1] > indent {
			l.indents = l.indents[:len(l.indents)-1]
			tokens = append(tokens, Token{DEDENT, "", l.line, 1})
		}
		if l.indents[len(l.indents)-1] != indent {
			return nil, fmt.Errorf("line %d: inconsistent indentation", l.line)
		}
	}

	return tokens, nil
}

// --- token dispatch ---

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

// --- individual token lexers ---

func (l *lexer) lexString() (Token, error) {
	line, col := l.line, l.col
	l.advance() // consume opening "

	var buf strings.Builder

	for !l.atEnd() {
		ch := l.current()

		switch ch {
		case '"':
			l.advance()
			return Token{STRING, buf.String(), line, col}, nil

		case '\n':
			// Multi-line string: collapse newline + following whitespace to one space
			l.advance()
			for !l.atEnd() && (l.current() == ' ' || l.current() == '\t') {
				l.advance()
			}
			// Only add space if it would not be leading or duplicate
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

func (l *lexer) lexNumber() Token {
	line, col := l.line, l.col
	var buf strings.Builder
	for !l.atEnd() && unicode.IsDigit(l.current()) {
		buf.WriteRune(l.advance())
	}
	return Token{NUMBER, buf.String(), line, col}
}

func (l *lexer) lexWord() Token {
	line, col := l.line, l.col
	var buf strings.Builder
	for !l.atEnd() && (unicode.IsLetter(l.current()) || unicode.IsDigit(l.current()) || l.current() == '_') {
		buf.WriteRune(l.advance())
	}
	word := buf.String()

	// js { ... } — capture raw JavaScript content as a single token
	if word == "js" {
		// skip whitespace before the opening brace
		for !l.atEnd() && (l.current() == ' ' || l.current() == '\t') {
			l.advance()
		}
		if !l.atEnd() && l.current() == '{' {
			return l.lexJSBlock(line, col)
		}
	}

	return Token{WORD, word, line, col}
}

func (l *lexer) lexJSBlock(line, col int) Token {
	l.advance() // consume opening {
	var buf strings.Builder
	depth := 1
	for !l.atEnd() && depth > 0 {
		ch := l.advance()
		switch ch {
		case '{':
			depth++
			buf.WriteRune(ch)
		case '}':
			depth--
			if depth > 0 {
				buf.WriteRune(ch)
			}
		default:
			buf.WriteRune(ch)
		}
	}
	return Token{JS_BLOCK, strings.TrimSpace(buf.String()), line, col}
}

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
		return Token{DOT, ".", line, col}, nil
	case ',':
		return Token{COMMA, ",", line, col}, nil
	case '(':
		return Token{LPAREN, "(", line, col}, nil
	case ')':
		return Token{RPAREN, ")", line, col}, nil
	case '{':
		return Token{LBRACE, "{", line, col}, nil
	case '}':
		return Token{RBRACE, "}", line, col}, nil
	case '[':
		return Token{LBRACKET, "[", line, col}, nil
	case ']':
		return Token{RBRACKET, "]", line, col}, nil
	}

	return Token{}, fmt.Errorf("%d:%d: unexpected character %q", line, col, ch)
}
