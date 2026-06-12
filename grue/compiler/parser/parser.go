// Package parser implements a recursive descent parser for Grue source files.
// It consumes a token stream from the lexer and produces an *ast.File.
//
// Context-driven design
//
// The lexer emits no keywords — every bareword is a WORD token — so the parser
// must rely on position and context to give words meaning. The same token
// sequence has different interpretations depending on where it appears:
//
//   - A WORD after an INDENT inside a class body is a property key ("light:", "weight:")
//   - A WORD after an INDENT inside a handler body is a statement keyword ("say", "fail")
//     or the start of an assignment/call expression
//   - A WORD immediately after "on" is the first keyword in a handler signature
//   - A capitalised WORD at the start of a line is a class name (instance declaration)
//
// Rather than trying to unify these in a single dispatch table, the parser has
// separate entry points for each syntactic context: parseBodyDecl, parseStmt,
// parseTestCmd, parseSignature, parsePropertyName, etc. Each knows exactly
// which constructs are legal and what to do when it sees an unexpected token.
//
// peek / advance pattern
//
// The parser is a simple one-token lookahead LL parser. p.peek() returns the
// current token without consuming it; p.advance() returns and consumes it.
// For multi-token lookahead (e.g. distinguishing "Type:name" from a keyword
// followed by a colon) the parser uses p.peekAt(offset) to inspect tokens
// further ahead without side effects. There is no separate lookahead buffer:
// p.peekAt(n) indexes directly into the token slice, which is already fully
// materialised before parsing begins.
//
// Body parser separation
//
// There are four distinct body parsers: parseBodyDecls (declarations inside a
// class or instance), parseStmtBlock (imperative statements inside a handler),
// parseTestBlock (test commands), and inline bodies for doors/inline instances.
// They are separate functions rather than a unified body parser because each
// context has a different set of legal constructs and different error-recovery
// semantics. Unifying them would require threading a context flag through every
// recursive call and would make it much harder to produce useful error messages.
package parser

import (
	"fmt"
	"strconv"
	"strings"

	"gruc/ast"
	"gruc/lexer"
)

// reserved is the set of words that may not appear as standalone words inside
// property names. They are valid as keywords in handler signatures and elsewhere.
//
// The list exists to produce better error messages when an author accidentally
// writes something like "on: lit" (intending a property) — without this check
// the parser would try to parse "on: lit" as a handler signature and emit a
// confusing error about a missing handler body.
var reserved = map[string]bool{
	"is": true, "isnt": true, "and": true, "or": true, "not": true,
	"if": true, "unless": true, "on": true,
	"fail": true, "succeed": true,
	"parent": true, "self": true, "true": true, "false": true,
	"unset": true, "set": true, "say": true,
	"stop": true, "choose": true, "directions": true,
	"when": true, "test": true, "interface": true, "library": true,
	"include": true, "kind": true, "class": true, "var": true,
	"filter": true, "silently": true, "modulo": true,
	"floor": true, "ceiling": true, "round": true,
	"absolute": true, "biggest": true, "smallest": true,
	"random": true, "seed": true,
	"extends": true, "internal": true,
}

// builtinFuncs is the set of built-in math function names.
var builtinFuncs = map[string]bool{
	"floor": true, "ceiling": true, "round": true,
	"absolute": true, "biggest": true, "smallest": true,
	"random": true, "seed": true,
	"through": true,
}

// =============================================================================
// Parser
// =============================================================================

type parser struct {
	tokens   []lexer.Token
	pos      int
	testMode bool // true when parsing inside a test block
}

// Parse converts a token stream into a Grue AST.
func Parse(tokens []lexer.Token) (*ast.File, error) {
	p := &parser{tokens: tokens}
	return p.parseFile()
}

// ParseExpr parses a single Grue expression from a source fragment.
// Used by the code generator to compile {expression} segments inside string
// interpolations. The source should be a bare expression — no surrounding
// quotes and no trailing newline required.
func ParseExpr(source string) (ast.Expr, error) {
	tokens, err := lexer.Tokenize(source)
	if err != nil {
		return nil, err
	}
	p := &parser{tokens: tokens}
	return p.parseExpr()
}

// =============================================================================
// Navigation helpers
// =============================================================================

// peek returns the current token without consuming it.
// Equivalent to peekAt(0). All conditional dispatch in the parser goes
// through peek() or peekAt() rather than consuming a token speculatively,
// so that error messages always point at the right position.
func (p *parser) peek() lexer.Token {
	return p.peekAt(0)
}

// peekAt returns the token at pos+offset without advancing. offset=0 is the
// current token; offset=1 is one ahead. Because the full token slice is
// already in memory, random access is O(1) and there is no need for a
// dedicated multi-token lookahead buffer.
func (p *parser) peekAt(offset int) lexer.Token {
	i := p.pos + offset
	if i >= len(p.tokens) {
		return lexer.Token{Type: lexer.EOF}
	}
	return p.tokens[i]
}

// advance consumes and returns the current token. Does not advance past EOF
// so callers can safely call advance() multiple times once the stream is done.
func (p *parser) advance() lexer.Token {
	tok := p.tokens[p.pos]
	if tok.Type != lexer.EOF {
		p.pos++
	}
	return tok
}

func (p *parser) at(t lexer.TokenType) bool {
	return p.peek().Type == t
}

func (p *parser) atWord(w string) bool {
	tok := p.peek()
	return tok.Type == lexer.WORD && tok.Value == w
}

func (p *parser) match(t lexer.TokenType) bool {
	if p.at(t) {
		p.advance()
		return true
	}
	return false
}

func (p *parser) expect(t lexer.TokenType) (lexer.Token, error) {
	tok := p.peek()
	if tok.Type != t {
		return tok, fmt.Errorf("%s: expected %s, got %s %q",
			p.pos2str(tok), t, tok.Type, tok.Value)
	}
	return p.advance(), nil
}

func (p *parser) expectWord(w string) error {
	tok := p.peek()
	if tok.Type != lexer.WORD || tok.Value != w {
		return fmt.Errorf("%s: expected %q, got %s %q",
			p.pos2str(tok), w, tok.Type, tok.Value)
	}
	p.advance()
	return nil
}

func (p *parser) skipNewlines() {
	for p.at(lexer.NEWLINE) {
		p.advance()
	}
}

func (p *parser) pos2str(tok lexer.Token) string {
	return fmt.Sprintf("%d:%d", tok.Line, tok.Col)
}

func (p *parser) currentPos() ast.Pos {
	tok := p.peek()
	return ast.Pos{Line: tok.Line, Col: tok.Col}
}

// =============================================================================
// File
// =============================================================================

func (p *parser) parseFile() (*ast.File, error) {
	file := &ast.File{Pos: p.currentPos()}
	p.skipNewlines()
	for !p.at(lexer.EOF) {
		decl, err := p.parseTopLevelDecl()
		if err != nil {
			return nil, err
		}
		file.Decls = append(file.Decls, decl)
		p.skipNewlines()
	}
	return file, nil
}

// =============================================================================
// Top-level declarations
// =============================================================================

func (p *parser) parseTopLevelDecl() (ast.Decl, error) {
	tok := p.peek()

	// "Title" by Author...
	if tok.Type == lexer.STRING {
		return p.parseGameDecl()
	}

	if tok.Type == lexer.WORD {
		switch tok.Value {
		case "library":
			return p.parseLibraryImport()
		case "include":
			return p.parseIncludeDecl()
		case "kind":
			return p.parseKindDecl()
		case "is":
			return p.parseKindUseDecl()
		case "var":
			return p.parseVarDecl()
		case "class":
			return p.parseClassDecl()
		case "on", "internal":
			if p.atWord("internal") && p.peekAt(1).Type == lexer.WORD && p.peekAt(1).Value == "interface" {
				return p.parseInterfaceHandlerDecl()
			}
			return p.parseHandlerDecl()
		case "test":
			return p.parseTestDecl()
		default:
			// Capitalised word — instance declaration (Room, Object, Door, or any class)
			if isCapitalized(tok.Value) {
				return p.parseInstanceDecl()
			}
			// Lowercase word at top level — property or var assignment
			return p.parsePropertyDecl()
		}
	}

	return nil, fmt.Errorf("%s: unexpected token %s %q at top level",
		p.pos2str(tok), tok.Type, tok.Value)
}

// =============================================================================
// Game declaration
// =============================================================================

// "Passing the Brass Lantern" by Bernd Eickhoff version guttoral goat
func (p *parser) parseGameDecl() (*ast.GameDecl, error) {
	pos := p.currentPos()
	title, err := p.expect(lexer.STRING)
	if err != nil {
		return nil, err
	}
	if err := p.expectWord("by"); err != nil {
		return nil, err
	}
	author := p.parseBareWords([]string{"version"}) // stop at "version" or NEWLINE
	version := ""
	if p.atWord("version") {
		p.advance()
		version = p.parseBareWords(nil)
	}
	if err := p.expectNewline(); err != nil {
		return nil, err
	}
	return &ast.GameDecl{
		Pos:     pos,
		Title:   title.Value,
		Author:  author,
		Version: version,
	}, nil
}

// =============================================================================
// Library / Include
// =============================================================================

func (p *parser) parseLibraryImport() (*ast.LibraryImport, error) {
	pos := p.currentPos()
	p.advance() // consume "library"
	path, err := p.expect(lexer.STRING)
	if err != nil {
		return nil, err
	}
	alias := ""
	if p.atWord("as") {
		p.advance()
		tok, err := p.expect(lexer.WORD)
		if err != nil {
			return nil, err
		}
		alias = tok.Value
	}
	if err := p.expectNewline(); err != nil {
		return nil, err
	}
	return &ast.LibraryImport{Pos: pos, Path: path.Value, Alias: alias}, nil
}

func (p *parser) parseIncludeDecl() (*ast.IncludeDecl, error) {
	pos := p.currentPos()
	p.advance() // consume "include"
	path, err := p.expect(lexer.STRING)
	if err != nil {
		return nil, err
	}
	if err := p.expectNewline(); err != nil {
		return nil, err
	}
	return &ast.IncludeDecl{Pos: pos, Path: path.Value}, nil
}

// =============================================================================
// Kind declaration
// =============================================================================

// kind mood: happy, *neutral, sad
func (p *parser) parseKindDecl() (*ast.KindDecl, error) {
	pos := p.currentPos()
	p.advance() // consume "kind"
	name, err := p.expect(lexer.WORD)
	if err != nil {
		return nil, err
	}
	if _, err := p.expect(lexer.COLON); err != nil {
		return nil, err
	}
	var values []string
	defaultIdx := 0
	for !p.at(lexer.NEWLINE) && !p.at(lexer.EOF) {
		isDefault := false
		if p.at(lexer.STAR) {
			p.advance()
			isDefault = true
		}
		val, err := p.expect(lexer.WORD)
		if err != nil {
			return nil, err
		}
		if isDefault {
			defaultIdx = len(values)
		}
		values = append(values, val.Value)
		if !p.match(lexer.COMMA) {
			break
		}
	}
	if err := p.expectNewline(); err != nil {
		return nil, err
	}
	return &ast.KindDecl{
		Pos:        pos,
		Name:       name.Value,
		Values:     values,
		DefaultIdx: defaultIdx,
	}, nil
}

// =============================================================================
// Var declaration
// =============================================================================

// var score
// var energy: 100
func (p *parser) parseVarDecl() (*ast.VarDecl, error) {
	pos := p.currentPos()
	p.advance() // consume "var"
	name, err := p.expect(lexer.WORD)
	if err != nil {
		return nil, err
	}
	var initial ast.Expr
	if p.match(lexer.COLON) {
		initial, err = p.parseExpr()
		if err != nil {
			return nil, err
		}
	}
	if err := p.expectNewline(); err != nil {
		return nil, err
	}
	return &ast.VarDecl{Pos: pos, Name: name.Value, Initial: initial}, nil
}

// =============================================================================
// Class declaration
// =============================================================================

// class Ledger
// class Rolodex extends Ledger
func (p *parser) parseClassDecl() (*ast.ClassDecl, error) {
	pos := p.currentPos()
	p.advance() // consume "class"
	name, err := p.expect(lexer.WORD)
	if err != nil {
		return nil, err
	}
	parent := ""
	if p.atWord("extends") {
		p.advance()
		tok, err := p.expect(lexer.WORD)
		if err != nil {
			return nil, err
		}
		parent = tok.Value
	}
	if err := p.expectNewline(); err != nil {
		return nil, err
	}
	body, err := p.parseBodyDecls()
	if err != nil {
		return nil, err
	}
	return &ast.ClassDecl{Pos: pos, Name: name.Value, Parent: parent, Body: body}, nil
}

// =============================================================================
// Instance declaration (Room, Object, Door, or any user-defined class)
// =============================================================================

// Room kitchen "The smell of burnt coffee lingers."
// Object brass lantern, lamp "A tarnished brass lantern."
// Robot Benson "A stocky iron robot."
func (p *parser) parseInstanceDecl() (*ast.InstanceDecl, error) {
	pos := p.currentPos()
	className := p.advance().Value // consume the class name

	// Parse the primary name: words/numbers/hyphens until comma, string, or newline
	name := p.parseInstanceName()

	// Parse optional aliases
	var aliases []string
	for p.match(lexer.COMMA) {
		aliases = append(aliases, p.parseInstanceName())
	}

	// Optional description string
	desc := ""
	if p.at(lexer.STRING) {
		desc = p.advance().Value
	}

	if err := p.expectNewline(); err != nil {
		return nil, err
	}

	body, err := p.parseBodyDecls()
	if err != nil {
		return nil, err
	}

	return &ast.InstanceDecl{
		Pos:       pos,
		ClassName: className,
		Name:      name,
		Aliases:   aliases,
		Desc:      desc,
		Body:      body,
	}, nil
}

// parseInstanceName collects words, numbers, and hyphens into a name string,
// joining them with spaces (e.g. "brass lantern", "Area 51", "mother-in-law").
//
// The termination conditions are context clues the caller provides implicitly
// by the surrounding syntax:
//   - COMMA or STRING means aliases or a description string follows
//   - NEWLINE/INDENT/DEDENT/EOF means the name extended to end of line
//   - COLON means we're in a property-key context (shouldn't normally be reached
//     from an instance name, but handled defensively)
//
// Hyphens between words are joined without spaces ("mother-in-law"), but a
// bare trailing hyphen terminates the name to avoid consuming arithmetic
// minus operators.
func (p *parser) parseInstanceName() string {
	var parts []string
	for {
		tok := p.peek()
		switch tok.Type {
		case lexer.WORD:
			parts = append(parts, tok.Value)
			p.advance()
		case lexer.NUMBER:
			parts = append(parts, tok.Value)
			p.advance()
		case lexer.MINUS:
			// Hyphen between name parts: consume and join with "-"
			if len(parts) > 0 {
				p.advance()
				next := p.peek()
				if next.Type == lexer.WORD || next.Type == lexer.NUMBER {
					parts[len(parts)-1] = parts[len(parts)-1] + "-" + p.advance().Value
					continue
				}
			}
			return strings.Join(parts, " ")
		default:
			return strings.Join(parts, " ")
		}
	}
}

// =============================================================================
// Body declarations (inside class, room, object, style bodies)
// =============================================================================

// parseBodyDecls parses an optional indented block of declarations.
// Returns an empty slice (not an error) if there is no indented block, because
// many constructs (empty class, instance with no properties) have no body.
//
// This is the declaration body parser — legal inside a class, instance, or
// inline door. It is distinct from parseStmtBlock (handler bodies) and
// parseTestBlock (test bodies) because each context has a different set of
// legal constructs. Mixing them would require a context parameter threaded
// through every recursive call.
func (p *parser) parseBodyDecls() ([]ast.Decl, error) {
	if !p.at(lexer.INDENT) {
		return nil, nil
	}
	p.advance() // consume INDENT
	var decls []ast.Decl
	p.skipNewlines()
	for !p.at(lexer.DEDENT) && !p.at(lexer.EOF) {
		decl, err := p.parseBodyDecl()
		if err != nil {
			return nil, err
		}
		decls = append(decls, decl)
		p.skipNewlines()
	}
	if _, err := p.expect(lexer.DEDENT); err != nil {
		return nil, err
	}
	return decls, nil
}

// parseBodyDecl dispatches to the right declaration parser based on the
// first token of the current line inside a class or instance body.
//
// Capitalised words are class names (nested instance declarations). Lowercase
// words are either known keywords (on, kind, var, test, is) or property names.
// Numbers are also valid property keys (e.g. "0: unset").
func (p *parser) parseBodyDecl() (ast.Decl, error) {
	tok := p.peek()

	if tok.Type == lexer.WORD {
		switch tok.Value {
		case "on", "internal":
			if p.atWord("internal") && p.peekAt(1).Type == lexer.WORD && p.peekAt(1).Value == "interface" {
				return p.parseInterfaceHandlerDecl()
			}
			return p.parseHandlerDecl()
		case "kind":
			return p.parseKindDecl()
		case "var":
			return p.parseVarDecl()
		case "test":
			return p.parseTestDecl()
		case "is":
			return p.parseKindUseDecl()
		}
		// Capitalised word — nested instance declaration
		if isCapitalized(tok.Value) {
			return p.parseInstanceDecl()
		}
		// Lowercase word — property declaration (name: value)
		return p.parsePropertyDecl()
	}

	// Numeric key: 0: unset, 1: "value"
	if tok.Type == lexer.NUMBER {
		return p.parsePropertyDecl()
	}

	return nil, fmt.Errorf("%s: unexpected token %s %q in body",
		p.pos2str(tok), tok.Type, tok.Value)
}

// =============================================================================
// Property declaration
// =============================================================================

// parsePropertyDecl parses a property declaration of the form "key: value".
// The key can be multi-word ("top of ladder", "max occupants") and the value
// can be a number, string, name, array literal, or the special word "unset".
// Multiple comma-separated values are wrapped in a ListLit.
//
// Inline door syntax: a PropertyDecl can hold both a Value AND a Body when the
// property value is a class instance spec and an indented block follows it:
//
//	east: Door brass door "A heavy door."
//	    leads to: kitchen
//	    locked: true
//
// In this case Value is a NameExpr with the instance name ("brass door") and
// Body holds the door's own property declarations. The description string —
// if present — is prepended to Body as a "description" PropertyDecl so the
// rest of the compiler pipeline sees it like any other property regardless of
// whether it was written inline or inside the block.
//
// Examples:
//
//	north: hallway
//	top of ladder: Mare Tranquillitatis
//	max_occupants: 4
//	0: unset
func (p *parser) parsePropertyDecl() (*ast.PropertyDecl, error) {
	pos := p.currentPos()

	// Collect the property name: words and numbers until COLON
	// No reserved keywords allowed as standalone words
	key, err := p.parsePropertyName()
	if err != nil {
		return nil, err
	}

	if _, err := p.expect(lexer.COLON); err != nil {
		return nil, err
	}

	// Parse the value: unset, number, string, or a name (object/room reference).
	// Multiple comma-separated values produce a ListLit.
	value, err := p.parsePropertyValue()
	if err != nil {
		return nil, err
	}
	if p.at(lexer.COMMA) {
		listPos := value.Position()
		items := []ast.Expr{value}
		for p.match(lexer.COMMA) {
			item, err := p.parsePropertyValue()
			if err != nil {
				return nil, err
			}
			items = append(items, item)
		}
		value = &ast.ListLit{Pos: listPos, Items: items}
	}

	// Optional description string after an inline instance name (e.g. Door).
	var inlineDesc string
	if _, ok := value.(*ast.NameExpr); ok && p.at(lexer.STRING) {
		inlineDesc = p.advance().Value
	}

	if err := p.expectNewline(); err != nil {
		return nil, err
	}

	// An inline instance body follows when the property value names a class
	// instance and an indented block is present immediately after:
	//   east: Door brass door
	//       leads to: kitchen
	var body []ast.Decl
	if p.at(lexer.INDENT) {
		body, err = p.parseBodyDecls()
		if err != nil {
			return nil, err
		}
	}

	// Prepend description as a property so the rest of the pipeline sees it
	// the same way as any other property.
	if inlineDesc != "" {
		descPos := value.Position()
		body = append([]ast.Decl{&ast.PropertyDecl{
			Pos:   descPos,
			Key:   "description",
			Value: &ast.StringLit{Pos: descPos, Value: inlineDesc},
		}}, body...)
	}

	return &ast.PropertyDecl{Pos: pos, Key: key, Value: value, Body: body}, nil
}

// parsePropertyName reads the property name — words and numbers separated by
// spaces, stopping at COLON. Raises an error if a reserved keyword appears
// as a standalone word in the name.
//
// The trailing COLON is what unambiguously ends a property name. There is no
// maximum word count — Grue property names can be arbitrarily long phrases
// ("top of ladder", "number of times opened"). The reserved-word check exists
// to catch likely author mistakes rather than to enforce a keyword rule,
// because no character-level distinction separates keywords from names.
func (p *parser) parsePropertyName() (string, error) {
	var parts []string
	for {
		tok := p.peek()
		if tok.Type == lexer.COLON {
			break
		}
		if tok.Type == lexer.NUMBER {
			parts = append(parts, tok.Value)
			p.advance()
			continue
		}
		if tok.Type != lexer.WORD {
			break
		}
		if reserved[tok.Value] {
			return "", fmt.Errorf("%s: reserved word %q may not appear in a property name",
				p.pos2str(tok), tok.Value)
		}
		parts = append(parts, tok.Value)
		p.advance()
	}
	if len(parts) == 0 {
		tok := p.peek()
		return "", fmt.Errorf("%s: expected property name, got %s %q",
			p.pos2str(tok), tok.Type, tok.Value)
	}
	return strings.Join(parts, " "), nil
}

// parsePropertyValue parses the value side of a property declaration.
func (p *parser) parsePropertyValue() (ast.Expr, error) {
	tok := p.peek()
	pos := ast.Pos{Line: tok.Line, Col: tok.Col}

	switch tok.Type {
	case lexer.WORD:
		if tok.Value == "unset" {
			p.advance()
			return &ast.UnsetExpr{Pos: pos}, nil
		}
		// Instance name (room/object reference) — multi-word
		name := p.parseInstanceName()
		return &ast.NameExpr{Pos: pos, Name: name}, nil

	case lexer.NUMBER:
		p.advance()
		n, _ := strconv.Atoi(tok.Value)
		return &ast.NumberLit{Pos: pos, Value: n}, nil

	case lexer.MINUS:
		p.advance()
		next := p.peek()
		if next.Type != lexer.NUMBER {
			return nil, fmt.Errorf("%s: expected number after '-', got %s %q",
				p.pos2str(next), next.Type, next.Value)
		}
		p.advance()
		n, _ := strconv.Atoi(next.Value)
		return &ast.NumberLit{Pos: pos, Value: -n}, nil

	case lexer.STRING:
		p.advance()
		return &ast.StringLit{Pos: pos, Value: tok.Value}, nil

	}

	return nil, fmt.Errorf("%s: expected property value, got %s %q",
		p.pos2str(tok), tok.Type, tok.Value)
}

// =============================================================================
// Kind-use declaration (in instance/class body)
// =============================================================================

// is lockable
// is not lockable
// is sad
func (p *parser) parseKindUseDecl() (*ast.KindUseDecl, error) {
	pos := p.currentPos()
	p.advance() // consume "is"
	negate := false
	if p.atWord("not") {
		p.advance()
		negate = true
	}
	val, err := p.expect(lexer.WORD)
	if err != nil {
		return nil, err
	}
	if err := p.expectNewline(); err != nil {
		return nil, err
	}
	return &ast.KindUseDecl{Pos: pos, Value: val.Value, Negate: negate}, nil
}

// =============================================================================
// Handler declaration
// =============================================================================

// parseHandlerDecl parses a handler declaration.
//
// Forms:
//
//	on open Ledger:ledger at number:page:
//	internal has object:thing:
//	on every turn:
//
// The "internal" modifier is checked before consuming "on" because it changes
// what follows ("internal on ..." with explicit "on", or "internal has ..."
// without it). This flexibility allows library authors to write internal
// handlers without being forced to use the word "on".
func (p *parser) parseHandlerDecl() (ast.Decl, error) {
	pos := p.currentPos()
	internal := false
	if p.atWord("internal") {
		internal = true
		p.advance()
		// "on" is optional after "internal": both forms are valid:
		//   internal on open ...    (explicit)
		//   internal has ...        (implicit, no "on")
		if p.atWord("on") {
			p.advance()
		}
	} else {
		if err := p.expectWord("on"); err != nil {
			return nil, err
		}
	}

	// Special case: "on every turn:"
	if p.atWord("every") {
		p.advance()
		if err := p.expectWord("turn"); err != nil {
			return nil, err
		}
		if _, err := p.expect(lexer.COLON); err != nil {
			return nil, err
		}
		if err := p.expectNewline(); err != nil {
			return nil, err
		}
		body, err := p.parseStmtBlock()
		if err != nil {
			return nil, err
		}
		return &ast.HandlerDecl{
			Pos:       pos,
			Internal:  internal,
			EveryTurn: true,
			Body:      body,
		}, nil
	}

	// Parse handler signature
	sig, err := p.parseSignature()
	if err != nil {
		return nil, err
	}
	if err := p.expectNewline(); err != nil {
		return nil, err
	}
	body, err := p.parseStmtBlock()
	if err != nil {
		return nil, err
	}
	return &ast.HandlerDecl{
		Pos:       pos,
		Internal:  internal,
		Signature: sig,
		Body:      body,
	}, nil
}

// internal interface Object:response Object:request:
//
//	call: js
//	function: "processData"
//	filename: "handlers.js"
func (p *parser) parseInterfaceHandlerDecl() (*ast.InterfaceHandlerDecl, error) {
	pos := p.currentPos()
	p.advance() // consume "internal"
	p.advance() // consume "interface"
	sig, err := p.parseSignature()
	if err != nil {
		return nil, err
	}
	if err := p.expectNewline(); err != nil {
		return nil, err
	}
	body, err := p.parseBodyDecls()
	if err != nil {
		return nil, err
	}
	return &ast.InterfaceHandlerDecl{Pos: pos, Signature: sig, Body: body}, nil
}

// parseSignature reads a handler signature: an alternating sequence of
// keywords and Type:name parameter pairs, terminated by a bare COLON.
//
//	open Ledger:ledger at number:page:
//	→ [Keyword("open"), Param("Ledger","ledger"), Keyword("at"), Param("number","page")]
//
// Why alternate keywords and parameters?
// Grue handler signatures are designed to read like natural English commands
// ("open Ledger:ledger at number:page" reads as "open [a ledger] at [a page
// number]"). The alternation is unambiguous without brackets or explicit
// separators because the WORD COLON WORD pattern can only be a parameter,
// never a keyword — bare COLONs are not legal mid-keyword. This makes long,
// descriptive signatures like "on open Ledger:ledger at number:page:" parse
// without any ambiguity.
//
// "self" in signatures: the word "self" is a special SigParam with both Type
// and Name set to "self". It is not a lexer keyword; the parser recognises it
// by value and emits a SigParam so that the sema/world pass can resolve it to
// the enclosing instance without needing a special AST node kind.
//
// Two-token lookahead is needed: a WORD followed by COLON followed by WORD
// is a parameter; a WORD followed by COLON NOT followed by WORD (i.e. the
// signature-terminating colon) is the end of the signature, not a parameter.
func (p *parser) parseSignature() ([]ast.SigPart, error) {
	var parts []ast.SigPart
	for {
		tok := p.peek()

		// Bare COLON terminates the signature — this is what distinguishes
		// the end-of-signature colon from a Type:name colon (which is always
		// followed by another WORD).
		if tok.Type == lexer.COLON {
			p.advance()
			return parts, nil
		}

		if tok.Type != lexer.WORD {
			return nil, fmt.Errorf("%s: unexpected token %s %q in handler signature",
				p.pos2str(tok), tok.Type, tok.Value)
		}

		word := tok.Value

		// "self" is a special parameter meaning "the enclosing instance". It
		// is resolved by sema/world, not by the parser — the parser just
		// records it as a SigParam so the rest of the pipeline has a uniform
		// type to work with.
		if word == "self" {
			p.advance()
			parts = append(parts, ast.SigParam{Type: "self", Name: "self"})
			continue
		}

		// WORD COLON WORD → typed parameter (Type:name).
		// Two-token lookahead: we need peekAt(1) == COLON AND peekAt(2) == WORD
		// to distinguish "Ledger:ledger" (parameter) from the bare terminating
		// colon (which has nothing after it, or has NEWLINE after it).
		if p.peekAt(1).Type == lexer.COLON && p.peekAt(2).Type == lexer.WORD {
			p.advance()               // consume type word
			p.advance()               // consume COLON
			name := p.advance().Value // consume name word
			parts = append(parts, ast.SigParam{Type: word, Name: name})
			continue
		}

		// Otherwise it's a plain keyword in the signature ("open", "at", "with").
		p.advance()
		parts = append(parts, ast.SigKeyword{Word: word})
	}
}

// =============================================================================
// Statement block
// =============================================================================

// parseStmtBlock parses an indented block of imperative statements (the body
// of a handler, if/unless, for, when, choose, etc.).
//
// When testMode is active the parser is already inside a test block. In that
// case parseStmtBlock delegates to parseTestBlock so that nested control
// structures (if/for/when inside a test) still treat their lines as test
// commands rather than ordinary statements. Without this delegation, a "for"
// loop inside a test block would expect assignment/call statements but find
// player-command lines and produce confusing errors.
func (p *parser) parseStmtBlock() ([]ast.Stmt, error) {
	if p.testMode {
		return p.parseTestBlock()
	}
	if !p.at(lexer.INDENT) {
		return nil, nil
	}
	p.advance() // consume INDENT
	var stmts []ast.Stmt
	p.skipNewlines()
	for !p.at(lexer.DEDENT) && !p.at(lexer.EOF) {
		stmt, err := p.parseStmt()
		if err != nil {
			return nil, err
		}
		stmts = append(stmts, stmt)
		p.skipNewlines()
	}
	if _, err := p.expect(lexer.DEDENT); err != nil {
		return nil, err
	}
	return stmts, nil
}

// =============================================================================
// Statements
// =============================================================================

func (p *parser) parseStmt() (ast.Stmt, error) {
	tok := p.peek()

	if tok.Type == lexer.LBRACE {
		return p.parseCallStmt()
	}

	if tok.Type != lexer.WORD {
		return nil, fmt.Errorf("%s: expected statement, got %s %q",
			p.pos2str(tok), tok.Type, tok.Value)
	}

	switch tok.Value {
	case "say":
		return p.parseSayStmt()
	case "fail":
		return p.parseFailStmt()
	case "succeed":
		return p.parseSucceedStmt()
	case "parent":
		p.advance()
		stmt := &ast.ParentStmt{Pos: ast.Pos{Line: tok.Line, Col: tok.Col}}
		if p.peek().Value == "silently" {
			p.advance()
			stmt.Silently = true
		}
		if err := p.expectNewline(); err != nil {
			return nil, err
		}
		return stmt, nil
	case "is":
		return p.parseKindUseDecl()
	case "if", "unless":
		return p.parseIfStmt()
	case "for":
		return p.parseForStmt()
	case "from":
		return p.parseRepeatStmt()
	case "when":
		return p.parseWhenStmt()
	case "choose":
		return p.parseChooseStmt()
	case "var":
		return p.parseVarDeclStmt()
	case "stop":
		p.advance()
		stmt := &ast.StopStmt{Pos: ast.Pos{Line: tok.Line, Col: tok.Col}}
		if err := p.expectNewline(); err != nil {
			return nil, err
		}
		return stmt, nil
	case "directions":
		return p.parseDirectionsStmt()
	default:
		return p.parseAssignOrMutateStmt()
	}
}

// =============================================================================
// Say
// =============================================================================

// say "text"
// say mono "text"
// say "text" if cond
func (p *parser) parseSayStmt() (*ast.SayStmt, error) {
	pos := p.currentPos()
	p.advance() // consume "say"

	// Optional block style name (a word before the string)
	style := ""
	if p.at(lexer.WORD) && p.peekAt(1).Type == lexer.STRING {
		style = p.advance().Value
	}

	str, err := p.expect(lexer.STRING)
	if err != nil {
		return nil, err
	}
	text := &ast.StringLit{Pos: ast.Pos{Line: str.Line, Col: str.Col}, Value: str.Value}

	guard, err := p.parseOptionalGuard()
	if err != nil {
		return nil, err
	}
	if err := p.expectNewline(); err != nil {
		return nil, err
	}
	return &ast.SayStmt{Pos: pos, Style: style, Text: text, Guard: guard}, nil
}

// directions "go east"
// directions "go east" if cond
func (p *parser) parseDirectionsStmt() (*ast.DirectionsStmt, error) {
	pos := p.currentPos()
	p.advance() // consume "directions"
	str, err := p.expect(lexer.STRING)
	if err != nil {
		return nil, err
	}
	text := &ast.StringLit{Pos: ast.Pos{Line: str.Line, Col: str.Col}, Value: str.Value}
	guard, err := p.parseOptionalGuard()
	if err != nil {
		return nil, err
	}
	if err := p.expectNewline(); err != nil {
		return nil, err
	}
	return &ast.DirectionsStmt{Pos: pos, Text: text, Guard: guard}, nil
}

// =============================================================================
// Fail / Succeed
// =============================================================================

func (p *parser) parseFailStmt() (*ast.FailStmt, error) {
	pos := p.currentPos()
	p.advance() // consume "fail"

	var token ast.Expr
	// Optional token: a bare word (identifier token) or quoted string
	if p.at(lexer.WORD) && !isGuardKeyword(p.peek().Value) && !p.at(lexer.NEWLINE) {
		tok := p.advance()
		token = &ast.NameExpr{Pos: ast.Pos{Line: tok.Line, Col: tok.Col}, Name: tok.Value}
	} else if p.at(lexer.STRING) {
		tok := p.advance()
		token = &ast.StringLit{Pos: ast.Pos{Line: tok.Line, Col: tok.Col}, Value: tok.Value}
	}

	guard, err := p.parseOptionalGuard()
	if err != nil {
		return nil, err
	}
	if err := p.expectNewline(); err != nil {
		return nil, err
	}
	return &ast.FailStmt{Pos: pos, Token: token, Guard: guard}, nil
}

func (p *parser) parseSucceedStmt() (*ast.SucceedStmt, error) {
	pos := p.currentPos()
	p.advance() // consume "succeed"

	var token ast.Expr
	if !p.at(lexer.NEWLINE) && !p.at(lexer.EOF) && !isGuardKeyword(p.peek().Value) {
		var err error
		token, err = p.parseExpr()
		if err != nil {
			return nil, err
		}
	}

	guard, err := p.parseOptionalGuard()
	if err != nil {
		return nil, err
	}
	if err := p.expectNewline(); err != nil {
		return nil, err
	}
	return &ast.SucceedStmt{Pos: pos, Token: token, Guard: guard}, nil
}

// =============================================================================
// If / Unless
// =============================================================================

func (p *parser) parseIfStmt() (*ast.IfStmt, error) {
	pos := p.currentPos()
	unless := p.peek().Value == "unless"
	p.advance() // consume "if" or "unless"

	cond, err := p.parseCond()
	if err != nil {
		return nil, err
	}
	if _, err := p.expect(lexer.COLON); err != nil {
		return nil, err
	}
	if err := p.expectNewline(); err != nil {
		return nil, err
	}
	body, err := p.parseStmtBlock()
	if err != nil {
		return nil, err
	}

	stmt := &ast.IfStmt{Pos: pos, Unless: unless, Cond: cond, Body: body}

	// else if / else
	p.skipNewlines()
	for p.atWord("else") {
		p.advance() // consume "else"
		if p.atWord("if") || p.atWord("unless") {
			elif, err := p.parseIfStmt()
			if err != nil {
				return nil, err
			}
			stmt.ElseIf = append(stmt.ElseIf, elif)
		} else {
			if _, err := p.expect(lexer.COLON); err != nil {
				return nil, err
			}
			if err := p.expectNewline(); err != nil {
				return nil, err
			}
			elseBody, err := p.parseStmtBlock()
			if err != nil {
				return nil, err
			}
			stmt.Else = elseBody
			break
		}
	}
	return stmt, nil
}

// =============================================================================
// For / From (iterators)
// =============================================================================

func (p *parser) parseForStmt() (ast.Stmt, error) {
	pos := p.currentPos()
	p.advance() // consume "for"

	// for i from 0 to n:
	if p.peekAt(1).Type == lexer.WORD && p.peekAt(1).Value == "from" {
		return p.parseForFromStmt(pos)
	}

	// for key, value in collection:  OR  for item in collection:
	return p.parseForInStmt(pos)
}

func (p *parser) parseForFromStmt(pos ast.Pos) (*ast.ForFromStmt, error) {
	varName, err := p.expect(lexer.WORD)
	if err != nil {
		return nil, err
	}
	if err := p.expectWord("from"); err != nil {
		return nil, err
	}
	from, err := p.parseExpr()
	if err != nil {
		return nil, err
	}
	if err := p.expectWord("to"); err != nil {
		return nil, err
	}
	to, err := p.parseExpr()
	if err != nil {
		return nil, err
	}
	if _, err := p.expect(lexer.COLON); err != nil {
		return nil, err
	}
	if err := p.expectNewline(); err != nil {
		return nil, err
	}
	body, err := p.parseStmtBlock()
	if err != nil {
		return nil, err
	}
	return &ast.ForFromStmt{Pos: pos, Var: varName.Value, From: from, To: to, Body: body}, nil
}

func (p *parser) parseForInStmt(pos ast.Pos) (*ast.ForInStmt, error) {
	key, err := p.expect(lexer.WORD)
	if err != nil {
		return nil, err
	}
	value := ""
	if p.match(lexer.COMMA) {
		tok, err := p.expect(lexer.WORD)
		if err != nil {
			return nil, err
		}
		value = tok.Value
	}
	if err := p.expectWord("in"); err != nil {
		return nil, err
	}
	coll, err := p.parseExpr()
	if err != nil {
		return nil, err
	}
	if _, err := p.expect(lexer.COLON); err != nil {
		return nil, err
	}
	if err := p.expectNewline(); err != nil {
		return nil, err
	}
	body, err := p.parseStmtBlock()
	if err != nil {
		return nil, err
	}
	return &ast.ForInStmt{Pos: pos, Key: key.Value, Value: value, Collection: coll, Body: body}, nil
}

// from 0 to 3:   (range repeat — no variable)
func (p *parser) parseRepeatStmt() (*ast.RepeatStmt, error) {
	pos := p.currentPos()
	p.advance() // consume "from"
	from, err := p.parseExpr()
	if err != nil {
		return nil, err
	}
	if err := p.expectWord("to"); err != nil {
		return nil, err
	}
	to, err := p.parseExpr()
	if err != nil {
		return nil, err
	}
	if _, err := p.expect(lexer.COLON); err != nil {
		return nil, err
	}
	if err := p.expectNewline(); err != nil {
		return nil, err
	}
	body, err := p.parseStmtBlock()
	if err != nil {
		return nil, err
	}
	return &ast.RepeatStmt{Pos: pos, From: from, To: to, Body: body}, nil
}

// =============================================================================
// When
// =============================================================================

func (p *parser) parseWhenStmt() (*ast.WhenStmt, error) {
	pos := p.currentPos()
	p.advance() // consume "when"
	expr, err := p.parseExpr()
	if err != nil {
		return nil, err
	}
	if _, err := p.expect(lexer.COLON); err != nil {
		return nil, err
	}
	if err := p.expectNewline(); err != nil {
		return nil, err
	}
	if _, err := p.expect(lexer.INDENT); err != nil {
		return nil, err
	}
	var arms []ast.WhenArm
	p.skipNewlines()
	for !p.at(lexer.DEDENT) && !p.at(lexer.EOF) {
		arm, err := p.parseWhenArm()
		if err != nil {
			return nil, err
		}
		arms = append(arms, arm)
		p.skipNewlines()
	}
	if _, err := p.expect(lexer.DEDENT); err != nil {
		return nil, err
	}
	return &ast.WhenStmt{Pos: pos, Expr: expr, Arms: arms}, nil
}

func (p *parser) parseWhenArm() (ast.WhenArm, error) {
	pos := p.currentPos()
	tok := p.peek()

	// Label: identifier token (word), quoted string, "fail", "succeed", or "default"
	var label string
	quoted := false
	if tok.Type == lexer.STRING {
		label = tok.Value
		quoted = true
		p.advance()
	} else if tok.Type == lexer.WORD {
		label = tok.Value
		p.advance()
	} else {
		return ast.WhenArm{}, fmt.Errorf("%s: expected when arm label, got %s",
			p.pos2str(tok), tok.Type)
	}
	if _, err := p.expect(lexer.COLON); err != nil {
		return ast.WhenArm{}, err
	}
	if err := p.expectNewline(); err != nil {
		return ast.WhenArm{}, err
	}
	body, err := p.parseStmtBlock()
	if err != nil {
		return ast.WhenArm{}, err
	}
	return ast.WhenArm{Pos: pos, Label: label, Quoted: quoted, Body: body}, nil
}

// =============================================================================
// Choose
// =============================================================================

func (p *parser) parseChooseStmt() (*ast.ChooseStmt, error) {
	pos := p.currentPos()
	p.advance() // consume "choose"
	prompt := ""
	if p.at(lexer.STRING) {
		prompt = p.advance().Value
	}
	if _, err := p.expect(lexer.COLON); err != nil {
		return nil, err
	}
	if err := p.expectNewline(); err != nil {
		return nil, err
	}
	if _, err := p.expect(lexer.INDENT); err != nil {
		return nil, err
	}
	var arms []ast.ChooseArm
	p.skipNewlines()
	for !p.at(lexer.DEDENT) && !p.at(lexer.EOF) {
		arm, err := p.parseChooseArm()
		if err != nil {
			return nil, err
		}
		arms = append(arms, arm)
		p.skipNewlines()
	}
	if _, err := p.expect(lexer.DEDENT); err != nil {
		return nil, err
	}
	return &ast.ChooseStmt{Pos: pos, Prompt: prompt, Arms: arms}, nil
}

func (p *parser) parseChooseArm() (ast.ChooseArm, error) {
	pos := p.currentPos()
	label, err := p.expect(lexer.STRING)
	if err != nil {
		return ast.ChooseArm{}, err
	}
	if _, err := p.expect(lexer.COLON); err != nil {
		return ast.ChooseArm{}, err
	}
	if err := p.expectNewline(); err != nil {
		return ast.ChooseArm{}, err
	}
	body, err := p.parseStmtBlock()
	if err != nil {
		return ast.ChooseArm{}, err
	}
	return ast.ChooseArm{Pos: pos, Label: label.Value, Body: body}, nil
}

// =============================================================================
// Call statement  {handler args}
// =============================================================================

func (p *parser) parseCallStmt() (*ast.CallStmt, error) {
	pos := p.currentPos()
	call, err := p.parseHandlerCallExpr()
	if err != nil {
		return nil, err
	}
	guard, err := p.parseOptionalGuard()
	if err != nil {
		return nil, err
	}
	if err := p.expectNewline(); err != nil {
		return nil, err
	}
	return &ast.CallStmt{Pos: pos, Call: call, Guard: guard}, nil
}

// parseVarDeclStmt parses a local var declaration inside a handler body.
// It produces a VarStmt (Stmt) instead of a VarDecl (Decl).
func (p *parser) parseVarDeclStmt() (*ast.VarStmt, error) {
	pos := p.currentPos()
	p.advance() // consume "var"

	// Node var: var ClassName varName  (ClassName starts with uppercase, then varName, then newline)
	if p.at(lexer.WORD) && len(p.peek().Value) > 0 && p.peek().Value[0] >= 'A' && p.peek().Value[0] <= 'Z' {
		tok1 := p.peekAt(1)
		tok2 := p.peekAt(2)
		if tok1.Type == lexer.WORD && (tok2.Type == lexer.NEWLINE || tok2.Type == lexer.EOF) {
			className := p.advance().Value
			varName := p.advance().Value
			if err := p.expectNewline(); err != nil {
				return nil, err
			}
			return &ast.VarStmt{Pos: pos, Name: varName, TypeName: className, IsNodeVar: true}, nil
		}
	}

	name, err := p.expect(lexer.WORD)
	if err != nil {
		return nil, err
	}
	var typeName string
	var initial ast.Expr
	// Optional type annotation: var name TypeName: expr
	// Detected by WORD followed immediately by COLON (distinguishes from plain var name: expr).
	if p.at(lexer.WORD) && p.peekAt(1).Type == lexer.COLON {
		typeName = p.advance().Value
		p.advance() // consume ":"
		initial, err = p.parseExpr()
		if err != nil {
			return nil, err
		}
	} else if p.match(lexer.COLON) {
		initial, err = p.parseExpr()
		if err != nil {
			return nil, err
		}
	}
	if err := p.expectNewline(); err != nil {
		return nil, err
	}
	return &ast.VarStmt{Pos: pos, Name: name.Value, TypeName: typeName, Initial: initial}, nil
}

// =============================================================================
// Assignment / Mutation
// =============================================================================

// Handles: score = expr, score += expr, score -= expr, score + expr, score - expr
// and property assignment: lamp.light = lit, log.{position} = "Jason"
func (p *parser) parseAssignOrMutateStmt() (ast.Stmt, error) {
	pos := p.currentPos()

	// Use parsePostfix so that LHS can be a property chain: log.{pos}, lamp.light
	lhs, err := p.parsePostfix()
	if err != nil {
		return nil, err
	}

	tok := p.peek()

	// "topic is jason" — kind-value assignment using "is" keyword
	if tok.Type == lexer.WORD && tok.Value == "is" {
		p.advance()
		valuePos := p.currentPos()
		valueName := p.parseInstanceName()
		rhs := &ast.NameExpr{Pos: valuePos, Name: valueName}
		guard, err := p.parseOptionalGuard()
		if err != nil {
			return nil, err
		}
		if err := p.expectNewline(); err != nil {
			return nil, err
		}
		return &ast.AssignStmt{Pos: pos, Target: lhs, Operator: "is", Value: rhs, Guard: guard}, nil
	}

	switch tok.Type {
	case lexer.EQ:
		p.advance()
		rhs, err := p.parseExpr()
		if err != nil {
			return nil, err
		}
		guard, err := p.parseOptionalGuard()
		if err != nil {
			return nil, err
		}
		if err := p.expectNewline(); err != nil {
			return nil, err
		}
		return &ast.AssignStmt{Pos: pos, Target: lhs, Operator: "=", Value: rhs, Guard: guard}, nil

	case lexer.PLUSEQ:
		p.advance()
		rhs, err := p.parseExpr()
		if err != nil {
			return nil, err
		}
		guard, err := p.parseOptionalGuard()
		if err != nil {
			return nil, err
		}
		if err := p.expectNewline(); err != nil {
			return nil, err
		}
		return &ast.AssignStmt{Pos: pos, Target: lhs, Operator: "+=", Value: rhs, Guard: guard}, nil

	case lexer.MINUSEQ:
		p.advance()
		rhs, err := p.parseExpr()
		if err != nil {
			return nil, err
		}
		guard, err := p.parseOptionalGuard()
		if err != nil {
			return nil, err
		}
		if err := p.expectNewline(); err != nil {
			return nil, err
		}
		return &ast.AssignStmt{Pos: pos, Target: lhs, Operator: "-=", Value: rhs, Guard: guard}, nil

	case lexer.PLUS:
		p.advance()
		rhs, err := p.parseExpr()
		if err != nil {
			return nil, err
		}
		guard, err := p.parseOptionalGuard()
		if err != nil {
			return nil, err
		}
		if err := p.expectNewline(); err != nil {
			return nil, err
		}
		return &ast.MutateStmt{Pos: pos, Target: lhs, Operator: "+", Value: rhs, Guard: guard}, nil

	case lexer.MINUS:
		p.advance()
		rhs, err := p.parseExpr()
		if err != nil {
			return nil, err
		}
		guard, err := p.parseOptionalGuard()
		if err != nil {
			return nil, err
		}
		if err := p.expectNewline(); err != nil {
			return nil, err
		}
		return &ast.MutateStmt{Pos: pos, Target: lhs, Operator: "-", Value: rhs, Guard: guard}, nil
	}

	// Bare handler call with inline object body — no operator, next line is indented:
	//   play Sound:sound:
	//       file: "pling.wav"
	if tok.Type == lexer.NEWLINE && p.peekAt(1).Type == lexer.INDENT {
		p.advance() // consume NEWLINE
		body, err := p.parseBodyDecls()
		if err != nil {
			return nil, err
		}
		return &ast.BareCallWithBodyStmt{Pos: pos, Expr: lhs, Body: body}, nil
	}

	// Bare handler call with no body — plain statement call:
	//   operate car
	//   fix machine with spanner
	if tok.Type == lexer.NEWLINE || tok.Type == lexer.EOF {
		if err := p.expectNewline(); err != nil {
			return nil, err
		}
		return &ast.BareCallStmt{Pos: pos, Expr: lhs}, nil
	}

	// Bare handler call with non-word argument (number, string, or braced expression):
	//   score 10
	//   say "text"  — but "say" is dispatched earlier, so this handles other handlers
	if nameExpr, ok := lhs.(*ast.NameExpr); ok {
		if tok.Type == lexer.NUMBER || tok.Type == lexer.STRING ||
			tok.Type == lexer.LBRACE || tok.Type == lexer.LPAREN || tok.Type == lexer.LBRACKET {
			call, err := p.parseBareCallTail(pos, nameExpr.Name)
			if err != nil {
				return nil, err
			}
			guard, err := p.parseOptionalGuard()
			if err != nil {
				return nil, err
			}
			if err := p.expectNewline(); err != nil {
				return nil, err
			}
			return &ast.CallStmt{Pos: pos, Call: call, Guard: guard}, nil
		}
	}

	return nil, fmt.Errorf("%s: expected assignment or mutation, got %s %q",
		p.pos2str(tok), tok.Type, tok.Value)
}

// parseBareCallTail builds a HandlerCallExpr from an initial word-only name plus
// any following non-word arguments. Words that follow an argument are added as
// additional keywords. "silently" is recognised as a modifier rather than a keyword.
//
//	score 10           → HandlerCallExpr[Word("score"), Arg(10)]
//	foo 5 bar "baz"    → HandlerCallExpr[Word("foo"), Arg(5), Word("bar"), Arg("baz")]
func (p *parser) parseBareCallTail(pos ast.Pos, initialName string) (*ast.HandlerCallExpr, error) {
	var parts []ast.HandlerCallPart
	for _, word := range strings.Fields(initialName) {
		parts = append(parts, ast.HandlerCallWord{Word: word})
	}
	silently := false
	for !p.at(lexer.NEWLINE) && !p.at(lexer.EOF) {
		tok := p.peek()
		if tok.Type == lexer.WORD {
			if isGuardKeyword(tok.Value) {
				break
			}
			if tok.Value == "silently" {
				silently = true
				p.advance()
				continue
			}
			parts = append(parts, ast.HandlerCallWord{Word: tok.Value})
			p.advance()
		} else if tok.Type == lexer.NUMBER || tok.Type == lexer.STRING ||
			tok.Type == lexer.LBRACE || tok.Type == lexer.LPAREN ||
			tok.Type == lexer.LBRACKET {
			expr, err := p.parsePrimary()
			if err != nil {
				return nil, err
			}
			parts = append(parts, ast.HandlerCallArg{Expr: expr})
		} else {
			break
		}
	}
	return &ast.HandlerCallExpr{Pos: pos, Parts: parts, Silently: silently}, nil
}

// =============================================================================
// Test declaration
// =============================================================================

// parseTestDecl parses a top-level or nested "test" block.
// Test blocks contain TestCmdStmt nodes rather than regular statements.
// The parser enters testMode for the duration of the block so that all
// nested control-flow bodies (if/for/when) also use test-command parsing.
func (p *parser) parseTestDecl() (*ast.TestDecl, error) {
	pos := p.currentPos()
	p.advance() // consume "test"
	name := ""
	if p.at(lexer.STRING) {
		name = p.advance().Value
	}
	if err := p.expectNewline(); err != nil {
		return nil, err
	}
	body, err := p.parseTestBlock()
	if err != nil {
		return nil, err
	}
	return &ast.TestDecl{Pos: pos, Name: name, Body: body}, nil
}

// parseTestBlock parses the body of a test block as a mix of test commands and
// regular Grue statements.
//
// Why TestCmdStmt rather than regular statements?
// Test commands are player-command strings ("open rolodex at 3") that are
// dispatched at runtime by the game engine, not Grue statements executed
// directly. They need a different AST node type so the code generator can emit
// "run this player command and check the output" rather than "execute this
// assignment". If test bodies used regular statements, the compiler would have
// to infer at the code-gen stage whether a given line was a player command or
// an assignment — which is fragile and context-dependent.
//
// Lines that look like assignments (contain =, +=, -=) or start with a
// statement keyword (if, for, say, etc.) are parsed as regular statements so
// that test setup logic (setting variables, conditional logic) still works.
// Everything else on a line is treated as a player command.
//
// testMode is a boolean flag on the parser struct rather than a parameter so
// that it propagates automatically into all recursive calls (parseStmtBlock,
// parseIfStmt, etc.) without requiring callers to thread it through.
func (p *parser) parseTestBlock() ([]ast.Stmt, error) {
	if !p.at(lexer.INDENT) {
		return nil, nil
	}
	saved := p.testMode
	p.testMode = true
	p.advance() // consume INDENT
	var stmts []ast.Stmt
	p.skipNewlines()
	for !p.at(lexer.DEDENT) && !p.at(lexer.EOF) {
		var stmt ast.Stmt
		var err error
		if p.isTestStmtKeyword() || p.lineHasAssignment() {
			stmt, err = p.parseStmt()
		} else {
			stmt, err = p.parseTestCmd()
		}
		if err != nil {
			p.testMode = saved
			return nil, err
		}
		stmts = append(stmts, stmt)
		p.skipNewlines()
	}
	if _, err := p.expect(lexer.DEDENT); err != nil {
		p.testMode = saved
		return nil, err
	}
	p.testMode = saved
	return stmts, nil
}

// isTestStmtKeyword reports whether the current token is a Grue statement
// keyword that should be parsed as a statement (not a player command) inside
// a test block.
func (p *parser) isTestStmtKeyword() bool {
	if !p.at(lexer.WORD) {
		return false
	}
	switch p.peek().Value {
	case "say", "if", "unless", "for", "from", "when",
		"var", "fail", "succeed", "stop", "parent":
		return true
	}
	// WORD immediately followed by '(' is a function call — always a statement.
	if p.pos+1 < len(p.tokens) && p.tokens[p.pos+1].Type == lexer.LPAREN {
		return true
	}
	return false
}

// lineHasAssignment scans forward from the current position to determine
// whether this line is an assignment statement. It looks for =, +=, -=, or
// the "is" keyword (kind assignment) before the next NEWLINE/EOF, without
// consuming any tokens.
//
// This scan is needed in test blocks to distinguish:
//   - "lamp.light = lit"   → regular assignment statement (set up test state)
//   - "topic is nothing"   → kind assignment (= and is are equivalent)
//   - "lamp lit"           → player command (issue to the game engine)
//   - "open box. "Opened"" → player command with assertion (DOT present)
//
// "is" is only treated as an assignment indicator when no DOT appears on the
// line — a DOT marks the end of a player command, so "open box." stays a
// command even if some other word on the line could be "is".
func (p *parser) lineHasAssignment() bool {
	hasIs := false
	for i := p.pos; i < len(p.tokens); i++ {
		switch p.tokens[i].Type {
		case lexer.EQ, lexer.PLUSEQ, lexer.MINUSEQ:
			return true
		case lexer.DOT:
			// DOT followed by a WORD or LBRACE is a property access (lamp.light,
			// log.{page}) — keep scanning. DOT followed by anything else (STRING,
			// NEWLINE, EOF) ends a player command.
			if i+1 < len(p.tokens) {
				next := p.tokens[i+1].Type
				if next == lexer.WORD || next == lexer.LBRACE {
					continue
				}
			}
			return false
		case lexer.NEWLINE, lexer.EOF:
			return hasIs
		case lexer.WORD:
			if p.tokens[i].Value == "is" {
				hasIs = true
			}
		}
	}
	return hasIs
}

// parseTestCmd parses one test command line.
//
// The DOT is the separator between the player command and the assertion. This
// role is context-sensitive: mid-expression a DOT is a property access
// separator, but at the end of a test command it signals "check that the
// response contains this string". The parser knows it is in test-command
// context (not an expression) because parseTestBlock is the caller.
//
// A bare dot at the start of the line (. "expected") means "wait one turn and
// check the output" — useful for testing timed events without issuing a command.
//
// Forms:
//
//	open rolodex at 3. "Opened"
//	open rolodex at 3. not "Opened"
//	open rolodex at 3.
//	test "other".
//	. "expected"          (bare dot — wait one turn)
func (p *parser) parseTestCmd() (*ast.TestCmdStmt, error) {
	pos := p.currentPos()

	// Bare dot: . "expected" — wait one turn
	if p.at(lexer.DOT) {
		p.advance()
		cmd := &ast.TestCmdStmt{Pos: pos}
		if err := p.parseTestAssertion(cmd); err != nil {
			return nil, err
		}
		if err := p.expectNewline(); err != nil {
			return nil, err
		}
		return cmd, nil
	}

	// "test" followed by string: sub-test call
	if p.atWord("test") && p.peekAt(1).Type == lexer.STRING {
		p.advance() // consume "test"
		name := p.advance().Value
		cmd := &ast.TestCmdStmt{Pos: pos, SubTest: name}
		if _, err := p.expect(lexer.DOT); err != nil {
			return nil, err
		}
		// sub-test calls may have no assertion
		if !p.at(lexer.NEWLINE) {
			if err := p.parseTestAssertion(cmd); err != nil {
				return nil, err
			}
		}
		if err := p.expectNewline(); err != nil {
			return nil, err
		}
		return cmd, nil
	}

	// "choose" followed by string: choice-selection step — the label is sent as
	// the player's input when the runtime is in pending-choice mode.
	if p.atWord("choose") && p.peekAt(1).Type == lexer.STRING {
		p.advance() // consume "choose"
		label := p.advance().Value
		cmd := &ast.TestCmdStmt{Pos: pos, Command: []string{label}}
		if _, err := p.expect(lexer.DOT); err != nil {
			return nil, err
		}
		if !p.at(lexer.NEWLINE) {
			if err := p.parseTestAssertion(cmd); err != nil {
				return nil, err
			}
		}
		if err := p.expectNewline(); err != nil {
			return nil, err
		}
		return cmd, nil
	}

	// {expr} command — evaluate a Grue expression and assert on its string value.
	// The expression is compiled to a JS closure at code-gen time; at runtime
	// the closure is called and its return value is checked against the assertion.
	if p.at(lexer.LBRACE) {
		p.advance() // consume {
		expr, err := p.parseExpr()
		if err != nil {
			return nil, err
		}
		if _, err := p.expect(lexer.RBRACE); err != nil {
			return nil, err
		}
		cmd := &ast.TestCmdStmt{Pos: pos, Expr: expr}
		if p.match(lexer.DOT) {
			if !p.at(lexer.NEWLINE) {
				if err := p.parseTestAssertion(cmd); err != nil {
					return nil, err
				}
			}
		}
		if err := p.expectNewline(); err != nil {
			return nil, err
		}
		return cmd, nil
	}

	// Normal command: collect words/numbers/strings until DOT
	var parts []string
	for !p.at(lexer.DOT) && !p.at(lexer.NEWLINE) && !p.at(lexer.EOF) {
		tok := p.peek()
		switch tok.Type {
		case lexer.WORD, lexer.NUMBER:
			parts = append(parts, tok.Value)
			p.advance()
		case lexer.STRING:
			parts = append(parts, `"`+tok.Value+`"`)
			p.advance()
		default:
			parts = append(parts, tok.Value)
			p.advance()
		}
	}

	cmd := &ast.TestCmdStmt{Pos: pos, Command: parts}

	if p.match(lexer.DOT) {
		if !p.at(lexer.NEWLINE) {
			if err := p.parseTestAssertion(cmd); err != nil {
				return nil, err
			}
		}
	}

	if err := p.expectNewline(); err != nil {
		return nil, err
	}
	return cmd, nil
}

func (p *parser) parseTestAssertion(cmd *ast.TestCmdStmt) error {
	if p.atWord("not") {
		p.advance()
		str, err := p.expect(lexer.STRING)
		if err != nil {
			return err
		}
		cmd.NotAssertion = true
		s := str.Value
		cmd.Assertion = &s
		return nil
	}
	if p.at(lexer.STRING) {
		s := p.advance().Value
		cmd.Assertion = &s
		return nil
	}
	return nil
}

// =============================================================================
// Guard (postfix if / unless)
// =============================================================================

// parseOptionalGuard checks for a postfix "if expr" or "unless expr" after a statement.
func (p *parser) parseOptionalGuard() (*ast.Guard, error) {
	if !p.at(lexer.WORD) {
		return nil, nil
	}
	val := p.peek().Value
	if val != "if" && val != "unless" {
		return nil, nil
	}
	unless := val == "unless"
	p.advance()
	cond, err := p.parseCond()
	if err != nil {
		return nil, err
	}
	return &ast.Guard{Unless: unless, Cond: cond}, nil
}

// isGuardKeyword reports whether a word starts a postfix guard or ends a statement.
func isGuardKeyword(w string) bool {
	return w == "if" || w == "unless"
}

// =============================================================================
// Expressions
// =============================================================================

// parseExpr parses a full expression including binary operators.
func (p *parser) parseExpr() (ast.Expr, error) {
	return p.parseBinaryExpr(0)
}

// parseCond parses a condition expression (stops before COLON).
func (p *parser) parseCond() (ast.Expr, error) {
	return p.parseBinaryExpr(0)
}

// operator precedence levels
var precedence = map[string]int{
	"or":     1,
	"and":    2,
	"is":     3, "isnt": 3,
	"<": 4, ">": 4, "<=": 4, ">=": 4, "==": 4,
	"modulo": 5,
	"+": 6, "-": 6,
	"*": 7, "/": 7,
}

func (p *parser) parseBinaryExpr(minPrec int) (ast.Expr, error) {
	// Handle unary "not".
	// Precedence 2 means "not" binds tighter than "and"/"or" (prec 1/2) but
	// looser than comparison operators (prec 3+), so "not a is b" parses as
	// "not (a is b)" and "not a and b" parses as "(not a) and b".
	if p.atWord("not") {
		pos := p.currentPos()
		p.advance()
		expr, err := p.parseBinaryExpr(2)
		if err != nil {
			return nil, err
		}
		return &ast.UnaryExpr{Pos: pos, Op: "not", Expr: expr}, nil
	}

	left, err := p.parseUnary()
	if err != nil {
		return nil, err
	}

	for {
		op, prec := p.peekBinaryOp()
		if prec <= minPrec {
			break
		}

		// "is set" / "is unset" — special forms
		if op == "is" {
			next := p.peekAt(1)
			if next.Type == lexer.WORD && next.Value == "set" {
				pos := left.Position()
				p.advance() // consume "is"
				p.advance() // consume "set"
				left = &ast.IsSetExpr{Pos: pos, Expr: left, Set: true}
				continue
			}
			if next.Type == lexer.WORD && next.Value == "unset" {
				pos := left.Position()
				p.advance() // consume "is"
				p.advance() // consume "unset"
				left = &ast.IsSetExpr{Pos: pos, Expr: left, Set: false}
				continue
			}
		}

		pos := left.Position()
		p.advance() // consume operator
		right, err := p.parseBinaryExpr(prec)
		if err != nil {
			return nil, err
		}
		left = &ast.BinaryExpr{Pos: pos, Left: left, Op: op, Right: right}
	}
	return left, nil
}

// peekBinaryOp looks at the current token and returns the operator string and
// its precedence. Returns ("", 0) if the current token is not a binary operator.
func (p *parser) peekBinaryOp() (string, int) {
	tok := p.peek()
	switch tok.Type {
	case lexer.PLUS:
		return "+", precedence["+"]
	case lexer.MINUS:
		return "-", precedence["-"]
	case lexer.STAR:
		return "*", precedence["*"]
	case lexer.SLASH:
		return "/", precedence["/"]
	case lexer.EQEQ:
		return "==", precedence["=="]
	case lexer.LT:
		return "<", precedence["<"]
	case lexer.GT:
		return ">", precedence[">"]
	case lexer.LTE:
		return "<=", precedence["<="]
	case lexer.GTE:
		return ">=", precedence[">="]
	case lexer.WORD:
		if prec, ok := precedence[tok.Value]; ok {
			return tok.Value, prec
		}
	}
	return "", 0
}

func (p *parser) parseUnary() (ast.Expr, error) {
	if p.at(lexer.MINUS) {
		pos := p.currentPos()
		p.advance()
		expr, err := p.parsePrimary()
		if err != nil {
			return nil, err
		}
		return &ast.UnaryExpr{Pos: pos, Op: "-", Expr: expr}, nil
	}
	// `is <kindvalue>` / `isnt <kindvalue>` — implicit world-level kind check.
	if p.atWord("is") || p.atWord("isnt") {
		pos := p.currentPos()
		negate := p.peek().Value == "isnt"
		p.advance() // consume "is" / "isnt"
		val, err := p.expect(lexer.WORD)
		if err != nil {
			return nil, err
		}
		return &ast.ImplicitIsExpr{Pos: pos, Value: val.Value, Negate: negate}, nil
	}
	return p.parsePostfix()
}

// parsePostfix handles property access chains: a.b, a.{expr}, and collection
// filters: collection.filter(ClassName).
//
// DOT is used for both static access (lamp.light) and dynamic access
// (log.{position}). The distinction is made here by checking whether a LBRACE
// follows the DOT: if so, we parse a full expression as the key and wrap it in
// a PropertyAccess with KeyExpr set; otherwise we expect a plain WORD and set
// the static Key field. Both are represented by the same AST node type so the
// code generator only needs one case.
func (p *parser) parsePostfix() (ast.Expr, error) {
	expr, err := p.parsePrimary()
	if err != nil {
		return nil, err
	}
	for p.at(lexer.DOT) {
		pos := p.currentPos()
		p.advance() // consume "."

		// Dynamic: .{expr}
		if p.at(lexer.LBRACE) {
			p.advance() // consume "{"
			keyExpr, err := p.parseExpr()
			if err != nil {
				return nil, err
			}
			if _, err := p.expect(lexer.RBRACE); err != nil {
				return nil, err
			}
			expr = &ast.PropertyAccess{Pos: pos, Object: expr, KeyExpr: keyExpr}
			continue
		}

		// filter(ClassName)
		if p.atWord("filter") {
			p.advance() // consume "filter"
			if _, err := p.expect(lexer.LPAREN); err != nil {
				return nil, err
			}
			cls, err := p.expect(lexer.WORD)
			if err != nil {
				return nil, err
			}
			if _, err := p.expect(lexer.RPAREN); err != nil {
				return nil, err
			}
			expr = &ast.FilterExpr{Pos: pos, Collection: expr, ClassName: cls.Value}
			continue
		}

		// Static: .word
		key, err := p.expect(lexer.WORD)
		if err != nil {
			return nil, err
		}
		expr = &ast.PropertyAccess{Pos: pos, Object: expr, Key: key.Value}
	}
	return expr, nil
}

// parsePrimary parses the innermost expression unit.
func (p *parser) parsePrimary() (ast.Expr, error) {
	tok := p.peek()
	pos := ast.Pos{Line: tok.Line, Col: tok.Col}

	switch tok.Type {
	case lexer.NUMBER:
		p.advance()
		n, _ := strconv.Atoi(tok.Value)
		return &ast.NumberLit{Pos: pos, Value: n}, nil

	case lexer.STRING:
		p.advance()
		return &ast.StringLit{Pos: pos, Value: tok.Value}, nil

	case lexer.LBRACE:
		// Inline handler call: {handler args silently?}
		return p.parseHandlerCallExpr()

	case lexer.LPAREN:
		p.advance()
		expr, err := p.parseExpr()
		if err != nil {
			return nil, err
		}
		if _, err := p.expect(lexer.RPAREN); err != nil {
			return nil, err
		}
		return expr, nil

	case lexer.WORD:
		if tok.Value == "unset" {
			p.advance()
			return &ast.UnsetExpr{Pos: pos}, nil
		}
		// Built-in function call: floor(expr), biggest(a, b)
		if builtinFuncs[tok.Value] && p.peekAt(1).Type == lexer.LPAREN {
			return p.parseFuncCall()
		}
		// Name reference: use expression-safe name parser that stops at
		// arithmetic operators and binary-op keywords so "fuse - 1" is not
		// consumed as the name "fuse-1".
		name := p.parseExprName()
		return &ast.NameExpr{Pos: pos, Name: name}, nil
	}

	return nil, fmt.Errorf("%s: unexpected token %s %q in expression",
		p.pos2str(tok), tok.Type, tok.Value)
}

// exprNameStop is the set of WORD values that terminate a multi-word name
// in expression context. These are all binary operators or statement keywords
// that cannot be part of a name reference.
var exprNameStop = map[string]bool{
	"is": true, "isnt": true,
	"and": true, "or": true, "not": true,
	"modulo": true,
	"if":     true, "unless": true,
}

// parseExprName collects consecutive WORD tokens into a space-joined name,
// stopping at MINUS (arithmetic operator) and any word in exprNameStop.
//
// Expression context requires a stricter stopping rule than instance names:
// "fuse - 1" must parse as (NameExpr "fuse") MINUS (NumberLit 1), not as a
// single name "fuse-1". parseInstanceName happily joins hyphenated parts because
// in name context (instance declarations, property values) a hyphen is
// unambiguously a name component. In expression context a minus sign is almost
// certainly arithmetic, so we stop immediately at MINUS rather than peeking.
func (p *parser) parseExprName() string {
	var parts []string
	for {
		tok := p.peek()
		if tok.Type != lexer.WORD {
			break
		}
		if exprNameStop[tok.Value] {
			break
		}
		parts = append(parts, tok.Value)
		p.advance()
	}
	return strings.Join(parts, " ")
}

// parseFuncCall parses floor(expr), biggest(a, b), etc.
func (p *parser) parseFuncCall() (*ast.FuncCallExpr, error) {
	pos := p.currentPos()
	name := p.advance().Value // consume function name
	if _, err := p.expect(lexer.LPAREN); err != nil {
		return nil, err
	}
	var args []ast.Expr
	for !p.at(lexer.RPAREN) && !p.at(lexer.EOF) {
		arg, err := p.parseExpr()
		if err != nil {
			return nil, err
		}
		args = append(args, arg)
		if !p.match(lexer.COMMA) {
			break
		}
	}
	if _, err := p.expect(lexer.RPAREN); err != nil {
		return nil, err
	}
	return &ast.FuncCallExpr{Pos: pos, Name: name, Args: args}, nil
}


// parseHandlerCallExpr parses {handler args silently?}
func (p *parser) parseHandlerCallExpr() (*ast.HandlerCallExpr, error) {
	pos := p.currentPos()
	if _, err := p.expect(lexer.LBRACE); err != nil {
		return nil, err
	}
	var parts []ast.HandlerCallPart
	silently := false
	for !p.at(lexer.RBRACE) && !p.at(lexer.EOF) {
		tok := p.peek()
		if tok.Type == lexer.WORD && tok.Value == "silently" {
			silently = true
			p.advance()
			continue
		}
		// Argument expressions start with string/number/lbrace/lparen/lbracket
		if tok.Type == lexer.STRING || tok.Type == lexer.NUMBER ||
			tok.Type == lexer.LBRACE || tok.Type == lexer.LPAREN ||
			tok.Type == lexer.LBRACKET {
			expr, err := p.parseExpr()
			if err != nil {
				return nil, err
			}
			parts = append(parts, ast.HandlerCallArg{Expr: expr})
		} else if tok.Type == lexer.WORD {
			// A word followed by . or [ is a property/index access — parse as expr.
			// Plain words are handler keywords or name arguments.
			next := p.peekAt(1).Type
			if next == lexer.DOT || next == lexer.LBRACKET {
				expr, err := p.parseExpr()
				if err != nil {
					return nil, err
				}
				parts = append(parts, ast.HandlerCallArg{Expr: expr})
			} else {
				parts = append(parts, ast.HandlerCallWord{Word: tok.Value})
				p.advance()
			}
		} else {
			break
		}
	}
	if _, err := p.expect(lexer.RBRACE); err != nil {
		return nil, err
	}
	return &ast.HandlerCallExpr{Pos: pos, Parts: parts, Silently: silently}, nil
}

// =============================================================================
// Utility
// =============================================================================

func (p *parser) expectNewline() error {
	if p.at(lexer.NEWLINE) {
		p.advance()
		return nil
	}
	if p.at(lexer.EOF) {
		return nil
	}
	tok := p.peek()
	return fmt.Errorf("%s: expected newline, got %s %q", p.pos2str(tok), tok.Type, tok.Value)
}

// parseBareWords collects WORD tokens into a space-joined string,
// stopping at any word in the stopAt set, or at NEWLINE/EOF.
func (p *parser) parseBareWords(stopAt []string) string {
	stop := make(map[string]bool)
	for _, s := range stopAt {
		stop[s] = true
	}
	var parts []string
	for p.at(lexer.WORD) {
		if stop[p.peek().Value] {
			break
		}
		parts = append(parts, p.advance().Value)
	}
	return strings.Join(parts, " ")
}

// isCapitalized reports whether a string starts with an uppercase ASCII letter.
// Used to distinguish class names (Room, Object, Ledger) from property keys
// and statement keywords (north, say, on) at the start of a declaration line.
// Only ASCII uppercase is checked because Grue class names are conventionally
// ASCII identifiers, even if strings and property values may contain Unicode.
func isCapitalized(s string) bool {
	if len(s) == 0 {
		return false
	}
	return s[0] >= 'A' && s[0] <= 'Z'
}
