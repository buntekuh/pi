package lexer

import "fmt"

type TokenType int

const (
	// Structure
	INDENT  TokenType = iota
	DEDENT
	NEWLINE
	EOF

	// Literals
	WORD
	STRING
	NUMBER
	JS_BLOCK // raw JavaScript — content between js { }

	// Operators
	EQ      // =
	EQEQ    // ==
	PLUSEQ  // +=
	MINUSEQ // -=
	PLUS    // +
	MINUS   // -
	STAR    // *
	SLASH   // /
	LT      // <
	GT      // >
	LTE     // <=
	GTE     // >=

	// Punctuation
	COLON    // :
	DOT      // .
	COMMA    // ,
	LPAREN   // (
	RPAREN   // )
	LBRACE   // {
	RBRACE   // }
	LBRACKET // [
	RBRACKET // ]
)

var tokenNames = map[TokenType]string{
	INDENT:   "INDENT",
	DEDENT:   "DEDENT",
	NEWLINE:  "NEWLINE",
	EOF:      "EOF",
	WORD:     "WORD",
	STRING:   "STRING",
	NUMBER:   "NUMBER",
	JS_BLOCK: "JS_BLOCK",
	EQ:       "=",
	EQEQ:     "==",
	PLUSEQ:   "+=",
	MINUSEQ:  "-=",
	PLUS:     "+",
	MINUS:    "-",
	STAR:     "*",
	SLASH:    "/",
	LT:       "<",
	GT:       ">",
	LTE:      "<=",
	GTE:      ">=",
	COLON:    ":",
	DOT:      ".",
	COMMA:    ",",
	LPAREN:   "(",
	RPAREN:   ")",
	LBRACE:   "{",
	RBRACE:   "}",
	LBRACKET: "[",
	RBRACKET: "]",
}

func (t TokenType) String() string {
	if name, ok := tokenNames[t]; ok {
		return name
	}
	return fmt.Sprintf("TokenType(%d)", int(t))
}

type Token struct {
	Type  TokenType
	Value string
	Line  int
	Col   int
}

func (t Token) String() string {
	switch t.Type {
	case WORD, STRING, NUMBER:
		return fmt.Sprintf("%s(%q) %d:%d", t.Type, t.Value, t.Line, t.Col)
	default:
		return fmt.Sprintf("%s %d:%d", t.Type, t.Line, t.Col)
	}
}
