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
	// Internal handlers must be in the handlers map (so _call() can invoke them
	// from code) but must NOT be in the grammar trie (players can't type them).
	out := emit(t, `
internal check Object:thing:
    succeed

on take Object:thing:
    say "Taken."
`)
	if !strings.Contains(out, `"check Object"`) {
		t.Error("internal handler should appear in handlers map (callable from code)")
	}
	if !strings.Contains(out, `"take Object"`) {
		t.Error("public handler should appear in handlers map")
	}
	// The grammar trie has sigKey leaves like `sigKey: "take Object"`.
	// The internal handler must not appear there.
	if strings.Contains(out, `sigKey: "check Object"`) {
		t.Error("internal handler should not appear in grammar trie")
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

// ─────────────────────────────────────────────────────────────────────────────
// R-parameter wrapper
// ─────────────────────────────────────────────────────────────────────────────

func TestEmitRWrapper(t *testing.T) {
	// Handler and exprFn closures close over R = GrueRuntime so they can call
	// R.say(), R._prop(), etc. without globals.
	out := emit(t, `"Test" by T`)
	if !strings.Contains(out, "(function(R) { return {") {
		t.Errorf("R-wrapper header missing:\n%s", out)
	}
	if !strings.Contains(out, "})(GrueRuntime)") {
		t.Errorf("R-wrapper tail missing:\n%s", out)
	}
}

func TestEmitSayUsesRPrefix(t *testing.T) {
	out := emit(t, `
on look:
    say "Hello."
`)
	if !strings.Contains(out, "R.say(") {
		t.Errorf("say should be prefixed with R.:\n%s", out)
	}
}

// ─────────────────────────────────────────────────────────────────────────────
// string interpolation
// ─────────────────────────────────────────────────────────────────────────────

func TestEmitInterpolationUsesRStr(t *testing.T) {
	out := emit(t, `
on examine Object:thing:
    say "You see {thing}."
`)
	if !strings.Contains(out, "${R._str(thing)}") {
		t.Errorf("interpolated {thing} should compile to ${R._str(thing)}:\n%s", out)
	}
}

func TestEmitInterpolationWorldPropUsesRGet(t *testing.T) {
	out := emit(t, `
on look:
    say "Score: {score}."
`)
	if !strings.Contains(out, `R._get("score")`) {
		t.Errorf("unknown bare name in interpolation should use R._get:\n%s", out)
	}
}

func TestEmitInterpolationPropAccessUsesRProp(t *testing.T) {
	out := emit(t, `
on examine Object:thing:
    say "Weight: {thing.weight}."
`)
	if !strings.Contains(out, `R._prop(thing, "weight")`) {
		t.Errorf("prop access in interpolation should use R._prop:\n%s", out)
	}
}

// ─────────────────────────────────────────────────────────────────────────────
// exprFn (test assertions)
// ─────────────────────────────────────────────────────────────────────────────

func TestEmitExprFnUsesRStr(t *testing.T) {
	out := emit(t, `
"Test" by T
test
    test "math".
test "math"
    {3 + 4}. "7"
`)
	if !strings.Contains(out, "exprFn: function()") {
		t.Errorf("exprFn step missing:\n%s", out)
	}
	if !strings.Contains(out, "R._str(") {
		t.Errorf("exprFn should use R._str:\n%s", out)
	}
	if !strings.Contains(out, `assert: "7"`) {
		t.Errorf("assert value missing from exprFn step:\n%s", out)
	}
}

func TestEmitExprFnNoAssert(t *testing.T) {
	// Bare {expr} step (no assertion) should emit exprFn without assert field.
	out := emit(t, `
"Test" by T
test
    test "bare".
test "bare"
    {seed(42)}
`)
	if !strings.Contains(out, "exprFn: function()") {
		t.Errorf("bare exprFn step missing:\n%s", out)
	}
	if strings.Contains(out, "assert:") {
		t.Errorf("bare exprFn step should not emit assert:\n%s", out)
	}
}

// ─────────────────────────────────────────────────────────────────────────────
// fail / succeed / parent / stop
// ─────────────────────────────────────────────────────────────────────────────

func TestEmitFailNoToken(t *testing.T) {
	out := emit(t, `
on take Object:thing:
    fail
`)
	if !strings.Contains(out, `R._fail("")`) {
		t.Errorf(`fail should compile to R._fail(""):\n%s`, out)
	}
}

func TestEmitSucceedWithToken(t *testing.T) {
	out := emit(t, `
internal check Object:thing:
    succeed yes
`)
	if !strings.Contains(out, `R._succeed("yes")`) {
		t.Errorf(`succeed yes should compile to R._succeed("yes"):\n%s`, out)
	}
}

func TestEmitParentCompilesWithR(t *testing.T) {
	out := emit(t, `
Room kitchen "The kitchen."
    on look:
        parent
`)
	if !strings.Contains(out, "R._parent()") {
		t.Errorf("parent should compile to R._parent():\n%s", out)
	}
}

// ─────────────────────────────────────────────────────────────────────────────
// property access
// ─────────────────────────────────────────────────────────────────────────────

func TestEmitPropAccessUsesRProp(t *testing.T) {
	out := emit(t, `
on examine Object:thing:
    say "Weight: {thing.weight}."
`)
	if !strings.Contains(out, `R._prop(thing, "weight")`) {
		t.Errorf("prop access should compile to R._prop:\n%s", out)
	}
}

func TestEmitWorldPropUsesRGet(t *testing.T) {
	out := emit(t, `
on look:
    say "Score: {score}."
`)
	if !strings.Contains(out, `R._get("score")`) {
		t.Errorf("world prop access should compile to R._get:\n%s", out)
	}
}

func TestEmitSelfClassPropUsesRProp(t *testing.T) {
	// Inside a class handler, a bare class-property name resolves to R._prop(self, key).
	out := emit(t, `
class Container
    capacity: 10
    on open self:
        say "Capacity: {capacity}."
`)
	if !strings.Contains(out, `R._prop(self, "capacity")`) {
		t.Errorf("bare class prop in class handler should compile to R._prop(self, key):\n%s", out)
	}
}

// ─────────────────────────────────────────────────────────────────────────────
// instanceof / is-set
// ─────────────────────────────────────────────────────────────────────────────

func TestEmitInstanceofUsesRInstanceof(t *testing.T) {
	out := emit(t, `
class Container

on examine Object:thing:
    say "It's a container." if thing is Container
`)
	if !strings.Contains(out, `R._instanceof(thing, "Container")`) {
		t.Errorf("instanceof check should compile to R._instanceof:\n%s", out)
	}
}

func TestEmitIsSetUsesRIsset(t *testing.T) {
	out := emit(t, `
on examine Object:thing:
    say "Has label." if thing.label is set
`)
	if !strings.Contains(out, `R._isset(`) {
		t.Errorf("is set should compile to R._isset:\n%s", out)
	}
}

// ─────────────────────────────────────────────────────────────────────────────
// kinds
// ─────────────────────────────────────────────────────────────────────────────

func TestEmitKindIsUsesRProp(t *testing.T) {
	// "peter is wet" — kind-value comparison compiles to R._prop(peter, "wetness") === "wet"
	out := emit(t, `
kind wetness: *dry, damp, wet

Object peter "A person."

on look:
    say "Wet." if peter is wet
`)
	if !strings.Contains(out, `R._prop(`) {
		t.Errorf("kind 'is' check should use R._prop for the kind property:\n%s", out)
	}
}

func TestEmitKindOrdUsesRKindOrd(t *testing.T) {
	// Kind ordering comparison (>=, <, etc.) compiles to R._kindOrd(...).
	out := emit(t, `
kind wetness: *dry, damp, wet

Object peter "A person."

on look:
    say "Damp or worse." if peter.wetness >= damp
`)
	if !strings.Contains(out, `R._kindOrd(`) {
		t.Errorf("kind ordinal comparison should use R._kindOrd:\n%s", out)
	}
}

// ─────────────────────────────────────────────────────────────────────────────
// if / guard / unless
// ─────────────────────────────────────────────────────────────────────────────

func TestEmitIfElseCompiles(t *testing.T) {
	out := emit(t, `
on look:
    if score > 10:
        say "Doing well."
    else:
        say "Keep trying."
`)
	if !strings.Contains(out, "if (") {
		t.Errorf("if statement missing:\n%s", out)
	}
	if !strings.Contains(out, "} else {") {
		t.Errorf("else clause missing:\n%s", out)
	}
}

func TestEmitPostfixIfGuard(t *testing.T) {
	out := emit(t, `
on take Object:thing:
    say "Done." if score > 0
`)
	if !strings.Contains(out, "if (") {
		t.Errorf("postfix if guard should compile to if:\n%s", out)
	}
}

func TestEmitPostfixUnlessGuard(t *testing.T) {
	out := emit(t, `
on take Object:thing:
    fail unless score > 0
`)
	if !strings.Contains(out, "if (!(") {
		t.Errorf("postfix unless guard should compile to if (!(...)):\n%s", out)
	}
}

// ─────────────────────────────────────────────────────────────────────────────
// handler calls (_call / _callS) — sigKey uses type names, not var names
// ─────────────────────────────────────────────────────────────────────────────

func TestEmitHandlerCallUsesVarType(t *testing.T) {
	// {has item} where item is declared Object:item → sigKey "has Object", arg item.
	out := emit(t, `
internal has Object:thing:
    succeed yes

on take Object:item:
    say "No." unless {has item silently}
    say "Taken."
`)
	if !strings.Contains(out, `R._callS("has Object", item)`) {
		t.Errorf("handler call should use type name 'Object' in sigKey, not var name 'item':\n%s", out)
	}
}

func TestEmitHandlerCallNumberArg(t *testing.T) {
	// {score 10} with a number literal → sigKey "score number", arg 10.
	out := emit(t, `
internal score points:number:
    score + points

on look:
    {score 10}
`)
	if !strings.Contains(out, `R._call("score number", 10)`) {
		t.Errorf("numeric literal arg should produce 'number' in sigKey:\n%s", out)
	}
}

func TestEmitHandlerCallMultiVarArg(t *testing.T) {
	// {move item to room} where item:Object and room:Room → "move Object to Room".
	out := emit(t, `
internal move Object:thing to Room:dest:
    thing.location = dest

on deposit Object:item in Room:room:
    {move item to room}
`)
	if !strings.Contains(out, `R._call("move Object to Room", item, room)`) {
		t.Errorf("multi-var handler call should use type names in sigKey:\n%s", out)
	}
}

func TestEmitHandlerCallForLoopVarIsNumber(t *testing.T) {
	// Loop index from a for-from loop has type "number".
	out := emit(t, `
internal ping number:n:
    say "ping"

on look:
    for i from 0 to 5:
        {ping i}
`)
	if !strings.Contains(out, `R._call("ping number", i)`) {
		t.Errorf("for-loop index should have type 'number' in handler call sigKey:\n%s", out)
	}
}

// ─────────────────────────────────────────────────────────────────────────────
// Bug fix: for/in filter — filter result must not be wrapped in _children
// ─────────────────────────────────────────────────────────────────────────────

func TestForInFilterIteratesDirectly(t *testing.T) {
	// for item in X.filter(Class) must iterate the filter result directly.
	// Previously compiled to _children(R._filter(...)), passing an array where
	// a node name is expected — _children silently returned nothing.
	out := emit(t, `
Room kitchen "The kitchen."
    Object bowl "A bowl."
    Object cup "A cup."

on list:
    for item in kitchen.filter(Object):
        say "{item}"
`)
	if strings.Contains(out, `_children(R._filter(`) {
		t.Errorf("filter result must not be wrapped in _children:\n%s", out)
	}
	if !strings.Contains(out, `R._filter("kitchen", "Object")`) {
		t.Errorf("expected direct R._filter call in output:\n%s", out)
	}
}

func TestForInPlainCollectionUsesChildren(t *testing.T) {
	// A plain node reference (no filter) must still use _children — regression guard.
	out := emit(t, `
Room kitchen "The kitchen."
    Object bowl "A bowl."

on list:
    for item in kitchen:
        say "{item}"
`)
	if !strings.Contains(out, `R._children("kitchen")`) {
		t.Errorf("plain for/in over a node should use R._children:\n%s", out)
	}
}

// ─────────────────────────────────────────────────────────────────────────────
// Bug fix: _filter runtime — tautological condition and O(n²) reverse lookup
// ─────────────────────────────────────────────────────────────────────────────

func TestRuntimeFilterNoBogusLookup(t *testing.T) {
	// _filter previously had a tautological `nameOrRef === nameOrRef` guard
	// (always true) and recovered the node name via an O(n) Object.keys().find()
	// scan even though the name was already in the Object.entries destructuring.
	if strings.Contains(codegen.RuntimeJS, "nameOrRef === nameOrRef") {
		t.Error("_filter still contains tautological nameOrRef === nameOrRef condition")
	}
	if strings.Contains(codegen.RuntimeJS, "Object.keys(nodes).find(") {
		t.Error("_filter still uses O(n²) Object.keys().find() reverse lookup")
	}
}

// ─────────────────────────────────────────────────────────────────────────────
// Bug fix: when handler call uses _callT so fail tokens are returned
// ─────────────────────────────────────────────────────────────────────────────

func TestWhenHandlerCallUsesCallT(t *testing.T) {
	// when {handler}: must use R._callT, which returns the token for both
	// _SucceedSignal and _FailSignal. Plain R._call drops _FailSignal and
	// returns null, so named failure arms in a when block never fire.
	out := emit(t, `
internal check Object:thing:
    fail not_here

on examine Object:thing:
    when {check thing}:
        not_here:
            say "Not here."
`)
	if !strings.Contains(out, `R._callT(`) {
		t.Errorf("when-switch expression should use R._callT:\n%s", out)
	}
	if strings.Contains(out, `switch (R._call(`) {
		t.Errorf("when-switch expression must not use plain R._call:\n%s", out)
	}
}

func TestHandlerCallOutsideWhenUsesCall(t *testing.T) {
	// Handler calls outside a when expression must use plain R._call (or R._callS),
	// preserving the null-on-fail behaviour relied on in boolean guard contexts.
	out := emit(t, `
internal has Object:thing:
    succeed yes

on take Object:item:
    say "No." unless {has item silently}
    say "Taken."
`)
	if strings.Contains(out, `R._callT(`) {
		t.Errorf("handler call outside when must not use R._callT:\n%s", out)
	}
}

// ─────────────────────────────────────────────────────────────────────────────
// M5 — Classes, built-in hierarchy, inheritance chains
// ─────────────────────────────────────────────────────────────────────────────

func TestBuiltinClassStubsEmitted(t *testing.T) {
	// Built-in class stubs (Object, Room, Person, …) must appear in the
	// descriptor's classes map with isLibrary: true so the runtime
	// _instanceof walk spans the full hierarchy.
	out := emit(t, `Room kitchen "The kitchen."`)
	for _, name := range []string{"Object", "Room", "Item", "Person", "Player"} {
		if !strings.Contains(out, `"`+name+`"`) {
			t.Errorf("built-in class %q missing from classes descriptor:\n%s", name, out)
		}
	}
	if !strings.Contains(out, "isLibrary: true") {
		t.Errorf("built-in classes should have isLibrary: true:\n%s", out)
	}
}

func TestUserClassDefaultParentIsObject(t *testing.T) {
	// A user-declared class with no explicit parent should get parent: "Object"
	// so it participates in the _instanceof hierarchy.
	out := emit(t, `
class Chest
    on open self:
        say "Creak!"
`)
	if !strings.Contains(out, `parent: "Object"`) {
		t.Errorf("user class with no explicit parent should emit parent: \"Object\":\n%s", out)
	}
}

func TestInheritanceChainParentHandlerInSubclassChain(t *testing.T) {
	// When Rolodex extends Ledger and both have "on open self:" handlers, the
	// compiled "open Rolodex" chain must contain BOTH handlers so _parent()
	// from the Rolodex handler reaches the Ledger handler.
	out := emit(t, `
class Ledger
    on open self:
        say "You open the ledger."

class Rolodex extends Ledger
    on open self:
        say "You flip through the rolodex."
`)
	// Scope to the "open Rolodex" chain array only.
	chainKey := `"open Rolodex": [`
	chainStart := strings.Index(out, chainKey)
	if chainStart == -1 {
		t.Fatal(`"open Rolodex" handler chain missing from output`)
	}
	chainStart += len(chainKey)
	chainEnd := strings.Index(out[chainStart:], "],\n")
	if chainEnd == -1 {
		t.Fatal(`could not find end of "open Rolodex" chain`)
	}
	chain := out[chainStart : chainStart+chainEnd]

	rolodexIdx := strings.Index(chain, `"Rolodex"`)
	ledgerIdx  := strings.Index(chain, `"Ledger"`)
	if rolodexIdx == -1 {
		t.Error(`owner "Rolodex" missing from "open Rolodex" chain`)
	}
	if ledgerIdx == -1 {
		t.Error(`owner "Ledger" missing from "open Rolodex" chain — parent handler not inherited`)
	}
	if rolodexIdx != -1 && ledgerIdx != -1 && rolodexIdx > ledgerIdx {
		t.Error(`Rolodex handler should appear before Ledger handler in the "open Rolodex" chain`)
	}
}

func TestInheritanceChainGlobalHandlerReachableViaParent(t *testing.T) {
	// A global "examine Object" handler must appear in the "examine Chest" chain
	// so that _parent() from a Chest-specific handler reaches the library fallback.
	out := emit(t, `
class Chest
    on examine self:
        say "A sturdy chest."

on examine Object:thing:
    say "Nothing special about {thing}."
`)
	chainKey := `"examine Chest": [`
	chainStart := strings.Index(out, chainKey)
	if chainStart == -1 {
		t.Fatal(`"examine Chest" chain missing from output`)
	}
	chainStart += len(chainKey)
	chainEnd := strings.Index(out[chainStart:], "],\n")
	if chainEnd == -1 {
		t.Fatal(`could not find end of "examine Chest" chain`)
	}
	chain := out[chainStart : chainStart+chainEnd]

	// Global handlers are emitted with owner: null (empty owner string → null in JS).
	if !strings.Contains(chain, `owner: null`) {
		t.Error(`global handler (owner: null) missing from "examine Chest" chain — library fallback not inherited`)
	}
}

func TestGrammarSubclassParamBeforeAncestorParam(t *testing.T) {
	// Grammar trie must list a subclass param edge before its ancestor class
	// param edge so matchParam tries the most-specific type first.
	out := emit(t, `
class Chest extends Container
    on open self:
        say "Creak!"

on open Container:thing:
    say "You open it."
`)
	// Within the params array under "open", "Chest" edge must appear before "Container".
	openIdx := strings.Index(out, `"open"`)
	if openIdx == -1 {
		t.Fatal(`"open" keyword missing from grammar output`)
	}
	chestIdx     := strings.Index(out[openIdx:], `"Chest"`)
	containerIdx := strings.Index(out[openIdx:], `"Container"`)
	if chestIdx == -1 {
		t.Error(`"Chest" param edge missing from grammar trie`)
	}
	if containerIdx == -1 {
		t.Error(`"Container" param edge missing from grammar trie`)
	}
	if chestIdx != -1 && containerIdx != -1 && chestIdx > containerIdx {
		t.Error(`"Chest" param edge should appear before "Container" param edge in grammar trie`)
	}
}
