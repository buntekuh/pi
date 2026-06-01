// Package lexer converts Grue source text into a flat stream of tokens.
// The token stream is consumed by the parser to build the world tree AST.
//
// Grue is an indentation-sensitive language (like Python). The lexer handles
// indentation by emitting synthetic INDENT and DEDENT tokens, so the parser
// never needs to count spaces — it just sees block structure as token pairs.
package lexer

import "fmt"

// TokenType identifies the category of a token.
type TokenType int

const (
	// --- Structural tokens ---
	//
	// These are synthetic — they do not correspond to characters in the source
	// but are emitted by the lexer to make block structure explicit.

	// INDENT is emitted when a line is indented further than the previous line.
	// It marks the opening of a new block (handler body, class body, etc.).
	INDENT TokenType = iota

	// DEDENT is emitted when a line is indented less than the previous line.
	// One DEDENT is emitted for each level closed. If a handler body and the
	// enclosing class body both close at the same point, two DEDENTs are emitted.
	DEDENT

	// NEWLINE is emitted at the end of each non-blank logical line.
	// Blank lines and comment-only lines do not produce NEWLINE tokens.
	NEWLINE

	// EOF marks the end of the token stream. The parser stops here.
	EOF

	// --- Literal tokens ---
	//
	// These carry a Value string with the literal content.

	// WORD is any sequence of letters, digits, and underscores starting with a
	// letter or underscore. This covers keywords (on, fail, kind, class, Room...),
	// identifier parts (brass, lantern, kitchen), and kind values (sad, lit).
	//
	// Grue does not distinguish keywords from identifiers at the lexer level.
	// Multi-word identifiers ("brass lantern", "iron door") are sequences of
	// consecutive WORD tokens — the parser groups them using context.
	WORD

	// STRING is a double-quoted string literal. The Value holds the content
	// after processing:
	//   - Multi-line strings: a newline followed by any amount of whitespace
	//     is collapsed to a single space, allowing long descriptions to be
	//     wrapped across source lines without affecting the output.
	//   - {interpolation} and [directives] are preserved verbatim in the
	//     Value; the parser handles them in a later pass.
	STRING

	// NUMBER is an integer literal (Grue has no floating-point literals).
	// The Value holds the raw digit string; conversion to int is done by the parser.
	NUMBER

	// JS_BLOCK is the content of a js { } escape block — raw JavaScript captured
	// verbatim between the braces. Brace depth is tracked so nested JS objects
	// and functions are captured correctly. The Value is the trimmed JS source.
	//
	// js { } blocks are the only place single quotes and other non-Grue syntax
	// can appear; capturing them as a single opaque token avoids lexer confusion.
	JS_BLOCK

	// --- Operator tokens ---
	//
	// Two-character operators are recognised greedily: <= is LTE, not LT + EQ.

	EQ      // =   assignment
	EQEQ    // ==  equality comparison
	PLUSEQ  // +=  compound addition
	MINUSEQ // -=  compound subtraction
	PLUS    // +   addition / shorthand score + 10
	MINUS   // -   subtraction
	STAR    // *   multiplication, also kind default marker (*neutral)
	SLASH   // /   division (result is float; assignment rounds)
	LT      // <   less than
	GT      // >   greater than
	LTE     // <=  less than or equal
	GTE     // >=  greater than or equal

	// --- Punctuation tokens ---

	COLON    // :  separates property name from value, ends handler signatures
	DOT      // .  property access (log.0), test assertion separator (open x. "y")
	COMMA    // ,  separates object aliases, kind values
	LPAREN   // (  function call: floor(score / 2)
	RPAREN   // )
	LBRACE   // {  dynamic property access (log.{pos}), string interpolation
	RBRACE   // }
	LBRACKET // [  string directives [nobreak], inline style spans [key]...[/key]
	RBRACKET // ]
)

// tokenNames maps each TokenType to its display string for debugging and errors.
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

// Token is a single unit of lexed source. Line and Col are 1-based and point
// to the first character of the token in the original source, useful for
// error messages and IDE integration.
type Token struct {
	Type  TokenType
	Value string // non-empty for WORD, STRING, NUMBER, JS_BLOCK
	Line  int
	Col   int
}

// String returns a human-readable representation for debugging.
// Tokens with values include the quoted value; structural tokens show only type and position.
func (t Token) String() string {
	switch t.Type {
	case WORD, STRING, NUMBER, JS_BLOCK:
		return fmt.Sprintf("%s(%q) %d:%d", t.Type, t.Value, t.Line, t.Col)
	default:
		return fmt.Sprintf("%s %d:%d", t.Type, t.Line, t.Col)
	}
}
