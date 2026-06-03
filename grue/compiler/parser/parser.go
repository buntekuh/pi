// Package parser implements a recursive descent parser for Grue source files.
// It consumes a token stream from the lexer and produces an *ast.File.
//
// The parser is context-driven: the same token sequence may mean different
// things in different positions (declaration body vs handler body vs test body),
// so each context has its own parsing functions.
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
var reserved = map[string]bool{
	"is": true, "isnt": true, "and": true, "or": true, "not": true,
	"if": true, "unless": true, "on": true,
	"fail": true, "succeed": true,
	"parent": true, "self": true, "true": true, "false": true,
	"unset": true, "set": true, "say": true, "print": true,
	"stop": true, "choose": true,
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

// =============================================================================
// Navigation helpers
// =============================================================================

func (p *parser) peek() lexer.Token {
	return p.peekAt(0)
}

func (p *parser) peekAt(offset int) lexer.Token {
	i := p.pos + offset
	if i >= len(p.tokens) {
		return lexer.Token{Type: lexer.EOF}
	}
	return p.tokens[i]
}

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
			// Capitalised word — instance declaration (Room, Object, Door, Ai, etc.)
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
// Instance declaration (Room, Object, Door, Ai, user class)
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

// parseInstanceName collects words, numbers, and hyphens into a name string.
// Stops at comma, string, newline, indent, dedent, eof, or colon.
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
// Returns an empty slice if there is no indented block.
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
// first token of the current line.
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

// north: hallway
// top of ladder: Mare Tranquillitatis
// max_occupants: 4
// 0: unset
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

	return &ast.PropertyDecl{Pos: pos, Key: key, Value: value, Body: body}, nil
}

// parsePropertyName reads the property name — words and numbers separated by
// spaces, stopping at COLON. Raises an error if a reserved keyword appears
// as a standalone word in the name.
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

	case lexer.STRING:
		p.advance()
		return &ast.StringLit{Pos: pos, Value: tok.Value}, nil

	case lexer.LBRACKET:
		return p.parseArrayLit()
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

// on open Ledger:ledger at number:page:
// internal has object:thing:
// on every turn:
// on turn 1:  /  on turn 5-6:  /  on turn 7-:  /  on turn -8:
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

	// Special case: "on turn N:" / "on turn N-M:" / "on turn N-:" / "on turn -N:"
	if p.atWord("turn") {
		next := p.peekAt(1)
		if next.Type == lexer.NUMBER || next.Type == lexer.MINUS {
			_ = internal // turn handlers fire unconditionally; internal is ignored
			return p.parseTurnHandlerDecl(pos)
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

// parseTurnHandlerDecl parses:
//
//	on turn 1:        exact turn
//	on turn 5-6:      inclusive range
//	on turn 7-:       7 and beyond (To = -1)
//	on turn -8:       up to and including 8 (From = 0)
func (p *parser) parseTurnHandlerDecl(pos ast.Pos) (*ast.TurnHandlerDecl, error) {
	p.advance() // consume "turn"

	from, to := 0, -1

	if p.at(lexer.MINUS) {
		// "-N" form: up to and including N
		p.advance() // consume "-"
		tok, err := p.expect(lexer.NUMBER)
		if err != nil {
			return nil, err
		}
		to = atoi(tok.Value)
	} else {
		// starts with a number
		tok, err := p.expect(lexer.NUMBER)
		if err != nil {
			return nil, err
		}
		from = atoi(tok.Value)
		to = from // default: exact turn

		if p.at(lexer.MINUS) {
			p.advance() // consume "-"
			if p.at(lexer.NUMBER) {
				// "N-M" range
				tok2, err := p.expect(lexer.NUMBER)
				if err != nil {
					return nil, err
				}
				to = atoi(tok2.Value)
			} else {
				// "N-" form: N and beyond
				to = -1
			}
		}
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
	return &ast.TurnHandlerDecl{Pos: pos, From: from, To: to, Body: body}, nil
}

func atoi(s string) int {
	n := 0
	for _, c := range s {
		n = n*10 + int(c-'0')
	}
	return n
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

// parseSignature reads a handler signature: alternating keywords and type:name
// parameters, ending with a bare COLON before NEWLINE.
//
// Example: open Ledger:ledger at number:page
// → [Keyword("open"), Param(Ledger,ledger), Keyword("at"), Param(number,page)]
func (p *parser) parseSignature() ([]ast.SigPart, error) {
	var parts []ast.SigPart
	for {
		tok := p.peek()

		// Bare COLON terminates the signature
		if tok.Type == lexer.COLON {
			p.advance()
			return parts, nil
		}

		if tok.Type != lexer.WORD {
			return nil, fmt.Errorf("%s: unexpected token %s %q in handler signature",
				p.pos2str(tok), tok.Type, tok.Value)
		}

		word := tok.Value

		// "self" alone is a self-parameter
		if word == "self" {
			p.advance()
			parts = append(parts, ast.SigParam{Type: "self", Name: "self"})
			continue
		}

		// WORD COLON WORD → typed parameter (Type:name)
		if p.peekAt(1).Type == lexer.COLON && p.peekAt(2).Type == lexer.WORD {
			p.advance()               // consume type word
			p.advance()               // consume COLON
			name := p.advance().Value // consume name word
			parts = append(parts, ast.SigParam{Type: word, Name: name})
			continue
		}

		// Otherwise it's a keyword
		p.advance()
		parts = append(parts, ast.SigKeyword{Word: word})
	}
}

// =============================================================================
// Statement block
// =============================================================================

// parseStmtBlock parses an indented block of statements.
// When testMode is active (inside a test block), it delegates to
// parseTestBlock so that nested loops and conditionals keep test-command
// semantics for their bodies.
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
		if err := p.expectNewline(); err != nil {
			return nil, err
		}
		return stmt, nil
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
	return &ast.VarStmt{Pos: pos, Name: name.Value, Initial: initial}, nil
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

	return nil, fmt.Errorf("%s: expected assignment or mutation, got %s %q",
		p.pos2str(tok), tok.Type, tok.Value)
}

// =============================================================================
// Test declaration
// =============================================================================

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

// parseTestBlock parses test command lines: command. "assertion" or command. not "assertion"
// Lines that contain an assignment operator or start with a statement keyword
// are parsed as regular Grue statements. Everything else is a player command.
// Sets testMode so that nested statement blocks (from/for/if/when bodies)
// continue using test-command semantics.
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
	return false
}

// lineHasAssignment returns true if the current line contains an assignment
// operator (=, +=, -=) before NEWLINE. Scans past DOT so that property
// assignments like "lamp.light = lit" are correctly detected.
func (p *parser) lineHasAssignment() bool {
	for i := p.pos; i < len(p.tokens); i++ {
		switch p.tokens[i].Type {
		case lexer.EQ, lexer.PLUSEQ, lexer.MINUSEQ:
			return true
		case lexer.NEWLINE, lexer.EOF:
			return false
		}
	}
	return false
}

// parseTestCmd parses one test command line.
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
	// Handle unary "not"
	if p.atWord("not") {
		pos := p.currentPos()
		p.advance()
		expr, err := p.parseBinaryExpr(8)
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
	return p.parsePostfix()
}

// parsePostfix handles property access chains: a.b, a.{expr}
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

	case lexer.LBRACKET:
		return p.parseArrayLit()

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
// Use this in expression context instead of parseInstanceName to avoid
// consuming arithmetic operators as part of a hyphenated name.
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

// parseArrayLit parses an Array literal: [expr, expr, ...]
// Keys are auto-assigned 0, 1, 2, ... in declaration order.
// NEWLINE, INDENT, and DEDENT tokens are skipped so multiline arrays work:
//
//	primes: [
//	    2, 3, 5,
//	    7, 11
//	]
func (p *parser) parseArrayLit() (*ast.ArrayLit, error) {
	pos := p.currentPos()
	p.advance() // consume [
	p.skipArrayWhitespace()
	var items []ast.Expr
	for !p.at(lexer.RBRACKET) && !p.at(lexer.EOF) {
		item, err := p.parseExpr()
		if err != nil {
			return nil, err
		}
		p.skipArrayWhitespace()
		if p.at(lexer.COLON) {
			tok := p.peek()
			return nil, fmt.Errorf("%s: named properties are not allowed in array literals; use an Object instead",
				p.pos2str(tok))
		}
		items = append(items, item)
		if !p.match(lexer.COMMA) {
			p.skipArrayWhitespace()
			break
		}
		p.skipArrayWhitespace()
	}
	if _, err := p.expect(lexer.RBRACKET); err != nil {
		return nil, err
	}
	return &ast.ArrayLit{Pos: pos, Items: items}, nil
}

// skipArrayWhitespace discards NEWLINE, INDENT, and DEDENT tokens that the
// lexer emits inside a multiline [...] literal. These are structural tokens
// whose indentation meaning is irrelevant once we are inside brackets.
func (p *parser) skipArrayWhitespace() {
	for p.at(lexer.NEWLINE) || p.at(lexer.INDENT) || p.at(lexer.DEDENT) {
		p.advance()
	}
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

// isCapitalized reports whether a string starts with an uppercase letter.
func isCapitalized(s string) bool {
	if len(s) == 0 {
		return false
	}
	return s[0] >= 'A' && s[0] <= 'Z'
}
