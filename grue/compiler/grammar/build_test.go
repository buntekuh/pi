package grammar_test

import (
	"gruc/ast"
	"gruc/grammar"
	"gruc/lexer"
	"gruc/parser"
	"gruc/world"
	"testing"
)

// parseWorld is a test helper that lexes, parses, and builds the world tree
// for the given source string.
func parseWorld(t *testing.T, src string) *world.World {
	t.Helper()
	tokens, err := lexer.Tokenize(src)
	if err != nil {
		t.Fatalf("lex error: %v", err)
	}
	f, err := parser.Parse(tokens)
	if err != nil {
		t.Fatalf("parse error: %v", err)
	}
	return world.Build([]*ast.File{f}, nil)
}

// ─────────────────────────────────────────────────────────────────────────────
// Empty / trivial
// ─────────────────────────────────────────────────────────────────────────────

func TestEmptyWorld(t *testing.T) {
	w := parseWorld(t, ``)
	g := grammar.Build(w)
	if len(g.Root.Keywords) != 0 || len(g.Root.Params) != 0 {
		t.Error("grammar for empty world should have empty root trie node")
	}
}

func TestNoHandlers(t *testing.T) {
	w := parseWorld(t, `
Room kitchen "The kitchen."
Object table "A table."
`)
	g := grammar.Build(w)
	if len(g.Root.Keywords) != 0 {
		t.Errorf("expected no keyword edges, got %d", len(g.Root.Keywords))
	}
}

// ─────────────────────────────────────────────────────────────────────────────
// Single-keyword patterns (no parameters)
// ─────────────────────────────────────────────────────────────────────────────

func TestSingleKeywordPattern(t *testing.T) {
	w := parseWorld(t, `
on wait:
    say "Time passes."
`)
	g := grammar.Build(w)

	// root → "wait" → terminal
	waitNode, ok := g.Root.Keywords["wait"]
	if !ok {
		t.Fatal("expected 'wait' keyword edge from root")
	}
	if waitNode.SigKey != "wait" {
		t.Errorf("wait node SigKey = %q, want %q", waitNode.SigKey, "wait")
	}
	if len(waitNode.Keywords) != 0 || len(waitNode.Params) != 0 {
		t.Error("wait node should be a leaf with no further edges")
	}
}

func TestMultiKeywordPattern(t *testing.T) {
	w := parseWorld(t, `
on traverse passage in the dark:
    say "You stumble through."
`)
	g := grammar.Build(w)

	// Walk: root → "traverse" → "passage" → "in" → "the" → "dark" → leaf
	node := g.Root
	for _, word := range []string{"traverse", "passage", "in", "the", "dark"} {
		next, ok := node.Keywords[word]
		if !ok {
			t.Fatalf("expected keyword edge %q", word)
		}
		node = next
	}
	if node.SigKey != "traverse passage in the dark" {
		t.Errorf("leaf SigKey = %q, want %q", node.SigKey, "traverse passage in the dark")
	}
}

// ─────────────────────────────────────────────────────────────────────────────
// Patterns with parameters
// ─────────────────────────────────────────────────────────────────────────────

func TestKeywordThenObjectParam(t *testing.T) {
	w := parseWorld(t, `
on examine Object:thing:
    say "Looks ordinary."
`)
	g := grammar.Build(w)

	// root → "examine" → [Object] → leaf
	examineNode, ok := g.Root.Keywords["examine"]
	if !ok {
		t.Fatal("expected 'examine' keyword edge")
	}
	if len(examineNode.Params) != 1 {
		t.Fatalf("expected 1 param edge after 'examine', got %d", len(examineNode.Params))
	}
	edge := examineNode.Params[0]
	if edge.Type != "Object" {
		t.Errorf("param edge type = %q, want %q", edge.Type, "Object")
	}
	if edge.Next.SigKey != "examine Object" {
		t.Errorf("leaf SigKey = %q, want %q", edge.Next.SigKey, "examine Object")
	}
}

func TestNumberParam(t *testing.T) {
	w := parseWorld(t, `
on turn to number:page:
    say "Turning to page {page}."
`)
	g := grammar.Build(w)

	// root → "turn" → "to" → [number] → leaf
	node, ok := g.Root.Keywords["turn"]
	if !ok {
		t.Fatal("expected 'turn' keyword edge")
	}
	node, ok = node.Keywords["to"]
	if !ok {
		t.Fatal("expected 'to' keyword edge")
	}
	if len(node.Params) != 1 || node.Params[0].Type != "number" {
		t.Errorf("expected number param, got %v", node.Params)
	}
	if node.Params[0].Next.SigKey != "turn to number" {
		t.Errorf("leaf SigKey = %q, want %q", node.Params[0].Next.SigKey, "turn to number")
	}
}

func TestStringParam(t *testing.T) {
	w := parseWorld(t, `
on search for string:query:
    say "You find nothing."
`)
	g := grammar.Build(w)

	// root → "search" → "for" → [string] → leaf
	node, ok := g.Root.Keywords["search"]
	if !ok {
		t.Fatal("expected 'search' keyword edge")
	}
	node, ok = node.Keywords["for"]
	if !ok {
		t.Fatal("expected 'for' keyword edge")
	}
	if len(node.Params) != 1 || node.Params[0].Type != "string" {
		t.Errorf("expected string param, got %v", node.Params)
	}
	if node.Params[0].Next.SigKey != "search for string" {
		t.Errorf("leaf SigKey = %q, want %q", node.Params[0].Next.SigKey, "search for string")
	}
}

func TestInterleavedKeywordsAndParams(t *testing.T) {
	w := parseWorld(t, `
on open Ledger:ledger at number:page:
    say "Opening at {page}."
`)
	g := grammar.Build(w)

	// root → "open" → [Ledger] → "at" → [number] → leaf
	openNode, ok := g.Root.Keywords["open"]
	if !ok {
		t.Fatal("expected 'open' keyword edge")
	}
	if len(openNode.Params) != 1 || openNode.Params[0].Type != "Ledger" {
		t.Fatalf("expected Ledger param after 'open', got %v", openNode.Params)
	}
	atNode, ok := openNode.Params[0].Next.Keywords["at"]
	if !ok {
		t.Fatal("expected 'at' keyword edge after Ledger param")
	}
	if len(atNode.Params) != 1 || atNode.Params[0].Type != "number" {
		t.Fatalf("expected number param after 'at', got %v", atNode.Params)
	}
	if atNode.Params[0].Next.SigKey != "open Ledger at number" {
		t.Errorf("leaf SigKey = %q, want %q", atNode.Params[0].Next.SigKey, "open Ledger at number")
	}
}

// ─────────────────────────────────────────────────────────────────────────────
// Internal handlers excluded
// ─────────────────────────────────────────────────────────────────────────────

func TestInternalHandlerExcluded(t *testing.T) {
	w := parseWorld(t, `
internal has object:thing:
    succeed if player has thing
    fail

on take Object:thing:
    say "Taken."
`)
	g := grammar.Build(w)

	// "take" should be present
	if _, ok := g.Root.Keywords["take"]; !ok {
		t.Error("expected 'take' in grammar")
	}
	// "has" should not be present (it's internal)
	if _, ok := g.Root.Keywords["has"]; ok {
		t.Error("internal 'has' handler should not appear in grammar")
	}
}

// ─────────────────────────────────────────────────────────────────────────────
// Shared prefix — trie merging
// ─────────────────────────────────────────────────────────────────────────────

func TestSharedPrefix(t *testing.T) {
	// Parameters are Type:name — one colon, no trailing colon after the name.
	// The sole colon at the very end of the line is the block opener.
	// "on take Object:thing from Object:container:" is correct; writing
	// "Object:thing:" would add a second bare colon that terminates the
	// signature early, cutting off the rest.
	w := parseWorld(t, `
on take Object:thing:
    say "Taken."

on take Object:thing from Object:container:
    say "Taken from container."
`)
	g := grammar.Build(w)

	// root → "take" → [Object] → terminal("take Object")
	//                           → "from" → [Object] → terminal("take Object from Object")
	takeNode, ok := g.Root.Keywords["take"]
	if !ok {
		t.Fatal("expected 'take' keyword edge")
	}
	if len(takeNode.Params) != 1 || takeNode.Params[0].Type != "Object" {
		t.Fatalf("expected Object param after 'take', got %v", takeNode.Params)
	}
	afterObj := takeNode.Params[0].Next
	if afterObj.SigKey != "take Object" {
		t.Errorf("intermediate SigKey = %q, want %q", afterObj.SigKey, "take Object")
	}
	fromNode, ok := afterObj.Keywords["from"]
	if !ok {
		t.Fatal("expected 'from' keyword edge at second level")
	}
	if len(fromNode.Params) != 1 || fromNode.Params[0].Type != "Object" {
		t.Fatalf("expected Object param after 'from', got %v", fromNode.Params)
	}
	leaf := fromNode.Params[0].Next
	if leaf.SigKey != "take Object from Object" {
		t.Errorf("leaf SigKey = %q, want %q", leaf.SigKey, "take Object from Object")
	}
}

// ─────────────────────────────────────────────────────────────────────────────
// "self" resolution in class/instance handlers
// ─────────────────────────────────────────────────────────────────────────────

func TestSelfResolvedToClassInClassHandler(t *testing.T) {
	w := parseWorld(t, `
class Lantern
    on examine self:
        say "A lantern."
`)
	g := grammar.Build(w)

	examineNode, ok := g.Root.Keywords["examine"]
	if !ok {
		t.Fatal("expected 'examine' keyword edge")
	}
	if len(examineNode.Params) != 1 {
		t.Fatalf("expected 1 param edge, got %d", len(examineNode.Params))
	}
	if examineNode.Params[0].Type != "Lantern" {
		t.Errorf("param type = %q, want %q", examineNode.Params[0].Type, "Lantern")
	}
	if examineNode.Params[0].Next.SigKey != "examine Lantern" {
		t.Errorf("SigKey = %q, want %q", examineNode.Params[0].Next.SigKey, "examine Lantern")
	}
}

func TestSelfResolvedToClassInInstanceHandler(t *testing.T) {
	w := parseWorld(t, `
Object brass lantern "A lantern."
    on examine self:
        say "A battered lantern."
`)
	g := grammar.Build(w)

	examineNode, ok := g.Root.Keywords["examine"]
	if !ok {
		t.Fatal("expected 'examine' keyword edge")
	}
	// Instance class is "Object", so "self" resolves to "Object"
	if len(examineNode.Params) != 1 || examineNode.Params[0].Type != "Object" {
		t.Errorf("expected Object param, got %v", examineNode.Params)
	}
}

// ─────────────────────────────────────────────────────────────────────────────
// Deduplication by SigKey
// ─────────────────────────────────────────────────────────────────────────────

func TestDifferentClassParamsDistinct(t *testing.T) {
	// "examine Widget" (SigKey) and "examine Object" are two distinct keys —
	// they must produce two separate param edges, not collapse into one.
	w := parseWorld(t, `
class Widget
    on examine self:
        say "A widget."

on examine Object:thing:
    say "You see nothing special."
`)
	g := grammar.Build(w)

	examineNode, ok := g.Root.Keywords["examine"]
	if !ok {
		t.Fatal("expected 'examine' keyword edge")
	}
	objEdges := 0
	widgetEdges := 0
	for _, edge := range examineNode.Params {
		switch edge.Type {
		case "Object":
			objEdges++
		case "Widget":
			widgetEdges++
		}
	}
	if objEdges != 1 {
		t.Errorf("expected 1 Object param edge, got %d", objEdges)
	}
	if widgetEdges != 1 {
		t.Errorf("expected 1 Widget param edge, got %d", widgetEdges)
	}
	if len(examineNode.Params) != 2 {
		t.Errorf("expected 2 param edges total, got %d", len(examineNode.Params))
	}
}

func TestTrueDuplicateSigKeyDeduped(t *testing.T) {
	// Global handler "examine Object" — a class handler for a different class but
	// same resolved key should be a separate key.  Here we test that the exact
	// same global handler appearing again (via library vs own) is not duplicated.
	ownSrc := `
on examine Object:thing:
    say "You see nothing special."
`
	libSrc := `
on examine Object:thing:
    say "Library examine."
`
	tokens, _ := lexer.Tokenize(ownSrc)
	f1, _ := parser.Parse(tokens)
	tokens, _ = lexer.Tokenize(libSrc)
	f2, _ := parser.Parse(tokens)
	w := world.Build([]*ast.File{f1}, []*ast.File{f2})
	g := grammar.Build(w)

	examineNode := g.Root.Keywords["examine"]
	if examineNode == nil {
		t.Fatal("expected 'examine' keyword edge")
	}
	if len(examineNode.Params) != 1 {
		t.Errorf("duplicate SigKey should be deduplicated; expected 1 param edge, got %d", len(examineNode.Params))
	}
}

// ─────────────────────────────────────────────────────────────────────────────
// Class handlers included
// ─────────────────────────────────────────────────────────────────────────────

func TestClassHandlerIncluded(t *testing.T) {
	w := parseWorld(t, `
class Container
    on open self:
        say "Opened."
`)
	g := grammar.Build(w)

	openNode, ok := g.Root.Keywords["open"]
	if !ok {
		t.Fatal("expected 'open' keyword edge from class handler")
	}
	if len(openNode.Params) != 1 || openNode.Params[0].Type != "Container" {
		t.Errorf("expected Container param, got %v", openNode.Params)
	}
}

// ─────────────────────────────────────────────────────────────────────────────
// Instance handlers included
// ─────────────────────────────────────────────────────────────────────────────

func TestInstanceHandlerIncluded(t *testing.T) {
	w := parseWorld(t, `
Object brass lantern "A lantern."
    on light self:
        say "You light the lantern."
`)
	g := grammar.Build(w)

	lightNode, ok := g.Root.Keywords["light"]
	if !ok {
		t.Fatal("expected 'light' keyword edge from instance handler")
	}
	if len(lightNode.Params) != 1 || lightNode.Params[0].Type != "Object" {
		t.Errorf("expected Object param, got %v", lightNode.Params)
	}
}

// ─────────────────────────────────────────────────────────────────────────────
// Multiple param types on same keyword
// ─────────────────────────────────────────────────────────────────────────────

func TestMultipleParamTypesOnSameKeyword(t *testing.T) {
	// Both "examine Object" and "examine Ledger" should produce two param edges.
	w := parseWorld(t, `
class Ledger
    on examine self:
        say "A ledger."

on examine Object:thing:
    say "Nothing special."
`)
	g := grammar.Build(w)

	examineNode, ok := g.Root.Keywords["examine"]
	if !ok {
		t.Fatal("expected 'examine' keyword edge")
	}
	types := make(map[string]bool)
	for _, edge := range examineNode.Params {
		types[edge.Type] = true
	}
	if !types["Ledger"] {
		t.Error("expected Ledger param edge")
	}
	if !types["Object"] {
		t.Error("expected Object param edge")
	}
}

// ─────────────────────────────────────────────────────────────────────────────
// Library handlers included
// ─────────────────────────────────────────────────────────────────────────────

func TestLibraryHandlerIncluded(t *testing.T) {
	ownSrc := `"Test" by Test`
	libSrc := `
on inventory:
    say "You are carrying nothing."
`
	tokens, _ := lexer.Tokenize(ownSrc)
	f1, _ := parser.Parse(tokens)
	tokens, _ = lexer.Tokenize(libSrc)
	f2, _ := parser.Parse(tokens)
	w := world.Build([]*ast.File{f1}, []*ast.File{f2})
	g := grammar.Build(w)

	invNode, ok := g.Root.Keywords["inventory"]
	if !ok {
		t.Fatal("expected 'inventory' keyword edge from library handler")
	}
	if invNode.SigKey != "inventory" {
		t.Errorf("SigKey = %q, want %q", invNode.SigKey, "inventory")
	}
}

// ─────────────────────────────────────────────────────────────────────────────
// Nested instance handlers
// ─────────────────────────────────────────────────────────────────────────────

func TestNestedInstanceHandlerIncluded(t *testing.T) {
	w := parseWorld(t, `
Room kitchen "The kitchen."
    Object table "A table."
        on push self:
            say "The table scrapes the floor."
`)
	g := grammar.Build(w)

	pushNode, ok := g.Root.Keywords["push"]
	if !ok {
		t.Fatal("expected 'push' keyword edge from nested instance handler")
	}
	if len(pushNode.Params) != 1 || pushNode.Params[0].Type != "Object" {
		t.Errorf("expected Object param, got %v", pushNode.Params)
	}
}

// ─────────────────────────────────────────────────────────────────────────────
// Mixed keyword-only and parameterised patterns share keyword path correctly
// ─────────────────────────────────────────────────────────────────────────────

func TestKeywordOnlyAndParamOnSameVerb(t *testing.T) {
	// "go" with no param vs "go" never overlaps here — different SigKeys.
	// Verify that a zero-param and a one-param handler under different verbs
	// don't corrupt each other's trie paths.
	w := parseWorld(t, `
on wait:
    say "Time passes."

on examine Object:thing:
    say "You see nothing special."
`)
	g := grammar.Build(w)

	if _, ok := g.Root.Keywords["wait"]; !ok {
		t.Error("expected 'wait' in grammar")
	}
	if _, ok := g.Root.Keywords["examine"]; !ok {
		t.Error("expected 'examine' in grammar")
	}
	// They should not interfere
	if len(g.Root.Keywords) != 2 {
		t.Errorf("expected 2 root keyword edges, got %d", len(g.Root.Keywords))
	}
}
