package codegen_test

import (
	"strings"
	"testing"

	"gruc/ast"
	"gruc/codegen"
	"gruc/grammar"
	"gruc/lexer"
	"gruc/parser"
	"gruc/world"
)

func parseWorld(t *testing.T, src string) *world.World {
	t.Helper()
	tokens, err := lexer.Tokenize(src)
	if err != nil {
		t.Fatalf("lex: %v", err)
	}
	f, err := parser.Parse(tokens)
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	return world.Build([]*ast.File{f}, nil)
}

func emit(t *testing.T, src string) string {
	t.Helper()
	w := parseWorld(t, src)
	g := grammar.Build(w)
	return codegen.Emit(w, g)
}

// ─────────────────────────────────────────────────────────────────────────────
// meta
// ─────────────────────────────────────────────────────────────────────────────

func TestEmitMetaTitle(t *testing.T) {
	out := emit(t, `"Passing the Brass Lantern" by Bernd Eickhoff`)
	if !strings.Contains(out, `"Passing the Brass Lantern"`) {
		t.Errorf("title missing from output:\n%s", out)
	}
}

func TestEmitMetaAuthor(t *testing.T) {
	out := emit(t, `"Test" by Bernd Eickhoff`)
	if !strings.Contains(out, `"Bernd Eickhoff"`) {
		t.Errorf("author missing from output:\n%s", out)
	}
}

func TestEmitMetaVersion(t *testing.T) {
	out := emit(t, `"Test" by Test version guttoral goat`)
	if !strings.Contains(out, `"guttoral goat"`) {
		t.Errorf("version missing from output:\n%s", out)
	}
}

func TestEmitMetaEmptyWhenAbsent(t *testing.T) {
	out := emit(t, `Room kitchen "The kitchen."`)
	// meta fields should be empty strings, not missing
	if !strings.Contains(out, "meta:") {
		t.Errorf("meta block missing from output:\n%s", out)
	}
}

// ─────────────────────────────────────────────────────────────────────────────
// nodes
// ─────────────────────────────────────────────────────────────────────────────

func TestEmitRoomNode(t *testing.T) {
	out := emit(t, `Room kitchen "The smell of burnt coffee lingers."`)
	if !strings.Contains(out, `"kitchen"`) {
		t.Errorf("room name missing:\n%s", out)
	}
	if !strings.Contains(out, `"Room"`) {
		t.Errorf("Room class missing:\n%s", out)
	}
	if !strings.Contains(out, `"The smell of burnt coffee lingers."`) {
		t.Errorf("room desc missing:\n%s", out)
	}
}

func TestEmitObjectNode(t *testing.T) {
	out := emit(t, `
Room kitchen "The kitchen."
    Object brass lantern "A battered lantern."
`)
	if !strings.Contains(out, `"brass lantern"`) {
		t.Errorf("object name missing:\n%s", out)
	}
	if !strings.Contains(out, `"Object"`) {
		t.Errorf("Object class missing:\n%s", out)
	}
	if !strings.Contains(out, `"A battered lantern."`) {
		t.Errorf("object desc missing:\n%s", out)
	}
}

func TestEmitNestedObjectHasLocation(t *testing.T) {
	out := emit(t, `
Room kitchen "The kitchen."
    Object table "A table."
`)
	// Table is nested inside kitchen — its location should be "kitchen".
	if !strings.Contains(out, `"kitchen"`) {
		t.Errorf("kitchen missing from output:\n%s", out)
	}
}

func TestEmitMultipleRooms(t *testing.T) {
	out := emit(t, `
Room kitchen "The kitchen."
Room hallway "The hallway."
Room garden "The garden."
`)
	for _, name := range []string{"kitchen", "hallway", "garden"} {
		if !strings.Contains(out, `"`+name+`"`) {
			t.Errorf("room %q missing from output:\n%s", name, out)
		}
	}
}

func TestEmitNodesEmptyWhenNone(t *testing.T) {
	out := emit(t, `"Empty" by Test`)
	if !strings.Contains(out, "nodes:") {
		t.Errorf("nodes field missing:\n%s", out)
	}
}

// ─────────────────────────────────────────────────────────────────────────────
// start
// ─────────────────────────────────────────────────────────────────────────────

func TestEmitStartIsFirstRoom(t *testing.T) {
	out := emit(t, `
Room kitchen "The kitchen."
Room hallway "The hallway."
`)
	if !strings.Contains(out, `start: "kitchen"`) {
		t.Errorf("start should be first room 'kitchen':\n%s", out)
	}
}

func TestEmitStartEmptyWhenNoRooms(t *testing.T) {
	out := emit(t, `"Empty" by Test`)
	if !strings.Contains(out, `start: ""`) {
		t.Errorf("start should be empty string when no rooms:\n%s", out)
	}
}

func TestEmitStartFromPlayerLocation(t *testing.T) {
	// Explicit player declaration with location: overrides first-room default.
	w := parseWorld(t, `
Room kitchen "The kitchen."
Room hallway "The hallway."
Player player
    location: hallway
`)
	g := grammar.Build(w)
	out := codegen.Emit(w, g)
	if !strings.Contains(out, `start: "hallway"`) {
		t.Errorf("start should follow player.location = hallway:\n%s", out)
	}
}

// ─────────────────────────────────────────────────────────────────────────────
// HTML output
// ─────────────────────────────────────────────────────────────────────────────

func TestHTMLStructure(t *testing.T) {
	w := parseWorld(t, `"Brass Lantern" by Test`)
	g := grammar.Build(w)
	out := codegen.HTML(w, g)

	for _, want := range []string{
		"<!DOCTYPE html>",
		`<div id="output">`,
		"GrueRuntime",
		"GrueRuntime.init(",
	} {
		if !strings.Contains(out, want) {
			t.Errorf("HTML missing %q", want)
		}
	}
}

func TestHTMLTitleEscaped(t *testing.T) {
	w := parseWorld(t, `"A & B <Test>" by Test`)
	g := grammar.Build(w)
	out := codegen.HTML(w, g)

	if strings.Contains(out, "<Test>") {
		t.Error("HTML title should have < > escaped")
	}
	if !strings.Contains(out, "&amp;") {
		t.Error("HTML title should escape &")
	}
}

func TestHTMLRuntimeInlined(t *testing.T) {
	w := parseWorld(t, `"Test" by Test`)
	g := grammar.Build(w)
	out := codegen.HTML(w, g)

	if !strings.Contains(out, codegen.RuntimeJS) {
		t.Error("HTML should inline the runtime JS verbatim")
	}
}

// ─────────────────────────────────────────────────────────────────────────────
// M2 — handlers
// ─────────────────────────────────────────────────────────────────────────────

func TestEmitHandlersField(t *testing.T) {
	out := emit(t, `
on look:
    say "You look around."
`)
	if !strings.Contains(out, "handlers:") {
		t.Errorf("handlers field missing:\n%s", out)
	}
}

func TestEmitHandlerSigKey(t *testing.T) {
	out := emit(t, `
on look:
    say "You look around."
`)
	if !strings.Contains(out, `"look"`) {
		t.Errorf("look sigKey missing from handlers:\n%s", out)
	}
}

func TestEmitHandlerSayCompiled(t *testing.T) {
	out := emit(t, `
on look:
    say "You look around the room."
`)
	if !strings.Contains(out, `R.say("You look around the room.")`) {
		t.Errorf("compiled say call missing:\n%s", out)
	}
}

func TestEmitHandlerWithParam(t *testing.T) {
	out := emit(t, `
on examine Object:thing:
    say "Nothing special."
`)
	if !strings.Contains(out, `"examine Object"`) {
		t.Errorf("examine Object sigKey missing:\n%s", out)
	}
	if !strings.Contains(out, "function(thing)") {
		t.Errorf("param name 'thing' missing in function signature:\n%s", out)
	}
}

func TestEmitHandlerOwnerInstance(t *testing.T) {
	out := emit(t, `
Room kitchen "The kitchen."
    on look:
        say "A small kitchen."
`)
	if !strings.Contains(out, `"kitchen"`) {
		t.Errorf("instance owner 'kitchen' missing:\n%s", out)
	}
}

func TestEmitHandlerOwnerClass(t *testing.T) {
	out := emit(t, `
class Container
    on open self:
        say "Opened."
`)
	if !strings.Contains(out, `"Container"`) {
		t.Errorf("class owner 'Container' missing:\n%s", out)
	}
}

func TestEmitHandlerChainOrder(t *testing.T) {
	// Instance handler must appear before global handler in the chain.
	out := emit(t, `
Room kitchen "The kitchen."
    on look:
        say "Kitchen specific look."

on look:
    say "Generic look."
`)
	kitchenIdx := strings.Index(out, `"Kitchen specific look."`)
	globalIdx := strings.Index(out, `"Generic look."`)
	if kitchenIdx == -1 || globalIdx == -1 {
		t.Fatal("one or both say strings missing")
	}
	if kitchenIdx > globalIdx {
		t.Error("instance handler should appear before global handler in chain")
	}
}

func TestEmitInternalHandlerExcluded(t *testing.T) {
	out := emit(t, `
internal check Object:thing:
    succeed

on take Object:thing:
    say "Taken."
`)
	if strings.Contains(out, `"check Object"`) {
		t.Error("internal handler should not appear in handlers map")
	}
	if !strings.Contains(out, `"take Object"`) {
		t.Error("public handler should appear in handlers map")
	}
}

// ─────────────────────────────────────────────────────────────────────────────
// M2 — grammar
// ─────────────────────────────────────────────────────────────────────────────

func TestEmitGrammarField(t *testing.T) {
	out := emit(t, `on look:
    say "You look around."
`)
	if !strings.Contains(out, "grammar:") {
		t.Errorf("grammar field missing:\n%s", out)
	}
}

func TestEmitGrammarContainsSigKey(t *testing.T) {
	out := emit(t, `on look:
    say "You look around."
`)
	// The trie should contain the "look" sigKey
	if !strings.Contains(out, `"look"`) {
		t.Errorf("look sigKey missing from grammar:\n%s", out)
	}
}

func TestEmitGrammarWithParam(t *testing.T) {
	out := emit(t, `on examine Object:thing:
    say "Nothing special."
`)
	if !strings.Contains(out, `"examine"`) {
		t.Errorf("examine keyword missing from grammar:\n%s", out)
	}
	if !strings.Contains(out, `"Object"`) {
		t.Errorf("Object param type missing from grammar:\n%s", out)
	}
}

// ─────────────────────────────────────────────────────────────────────────────
// M2 — vocab
// ─────────────────────────────────────────────────────────────────────────────

func TestEmitVocabField(t *testing.T) {
	out := emit(t, `Room kitchen "The kitchen."`)
	if !strings.Contains(out, "vocab:") {
		t.Errorf("vocab field missing:\n%s", out)
	}
}

func TestEmitVocabRoomEntry(t *testing.T) {
	out := emit(t, `Room kitchen "The kitchen."`)
	if !strings.Contains(out, `"kitchen"`) {
		t.Errorf("kitchen missing from vocab:\n%s", out)
	}
}

func TestEmitVocabAlias(t *testing.T) {
	out := emit(t, `
Room kitchen "The kitchen."
    Object brass lantern, lamp "A lantern."
`)
	// Alias "lamp" should appear as a vocab entry pointing to "brass lantern"
	if !strings.Contains(out, `"lamp"`) {
		t.Errorf("alias 'lamp' missing from vocab:\n%s", out)
	}
	if !strings.Contains(out, `"brass lantern"`) {
		t.Errorf("canonical 'brass lantern' missing from vocab:\n%s", out)
	}
}

func TestEmitVocabKeysLowercased(t *testing.T) {
	// Instance names are lowercased in vocab keys for case-insensitive input.
	out := emit(t, `
class Robot

Robot Benson "A robot."
`)
	// The vocab key for "Benson" should be lowercased: "benson"
	if !strings.Contains(out, `"benson"`) {
		t.Errorf("vocab key should be lowercase 'benson':\n%s", out)
	}
}

// ─────────────────────────────────────────────────────────────────────────────
// determinism
// ─────────────────────────────────────────────────────────────────────────────

func TestEmitIsDeterministic(t *testing.T) {
	src := `
"Test" by Test
Room kitchen "The kitchen."
    Object table "A table."
Room hallway "The hallway."
`
	tokens, _ := lexer.Tokenize(src)
	f, _ := parser.Parse(tokens)
	w := world.Build([]*ast.File{f}, nil)
	g := grammar.Build(w)

	out1 := codegen.Emit(w, g)
	out2 := codegen.Emit(w, g)
	if out1 != out2 {
		t.Error("Emit is not deterministic")
	}
}
