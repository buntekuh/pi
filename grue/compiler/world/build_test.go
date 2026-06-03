package world_test

import (
	"gruc/ast"
	"gruc/lexer"
	"gruc/parser"
	"gruc/world"
	"strings"
	"testing"
)

// parseSource is a test helper that lexes and parses a .grue source string.
func parseSource(t *testing.T, src string) *ast.File {
	t.Helper()
	tokens, err := lexer.Tokenize(src)
	if err != nil {
		t.Fatalf("lex error: %v", err)
	}
	f, err := parser.Parse(tokens)
	if err != nil {
		t.Fatalf("parse error: %v", err)
	}
	return f
}

// ───────────────────────────────────────────────────────────────────────────
// Game metadata
// ───────────────────────────────────────────────────────────────────────────

func TestGameInfo(t *testing.T) {
	src := `"Passing the Brass Lantern" by Bernd Eickhoff version guttoral goat`
	f := parseSource(t, src)
	w := world.Build([]*ast.File{f}, nil)
	if w.Game.Title != "Passing the Brass Lantern" {
		t.Errorf("title = %q, want %q", w.Game.Title, "Passing the Brass Lantern")
	}
	if w.Game.Author != "Bernd Eickhoff" {
		t.Errorf("author = %q, want %q", w.Game.Author, "Bernd Eickhoff")
	}
	if w.Game.Version != "guttoral goat" {
		t.Errorf("version = %q, want %q", w.Game.Version, "guttoral goat")
	}
}

// ───────────────────────────────────────────────────────────────────────────
// Kinds
// ───────────────────────────────────────────────────────────────────────────

func TestKinds(t *testing.T) {
	src := `
kind lockable: *false, true
kind mood: happy, *neutral, sad
`
	f := parseSource(t, src)
	w := world.Build([]*ast.File{f}, nil)

	if len(w.Kinds) != 2 {
		t.Fatalf("len(Kinds) = %d, want 2", len(w.Kinds))
	}
	lockable := w.Kinds[0]
	if lockable.Name != "lockable" {
		t.Errorf("Kinds[0].Name = %q, want %q", lockable.Name, "lockable")
	}
	if lockable.DefaultIdx != 0 {
		t.Errorf("lockable.DefaultIdx = %d, want 0 (*false)", lockable.DefaultIdx)
	}
	mood := w.Kinds[1]
	if mood.DefaultIdx != 1 {
		t.Errorf("mood.DefaultIdx = %d, want 1 (*neutral)", mood.DefaultIdx)
	}
}

func TestTopLevelKindCreatesWorldProp(t *testing.T) {
	src := `kind mood: happy, *neutral, sad`
	f := parseSource(t, src)
	w := world.Build([]*ast.File{f}, nil)

	var found *world.Prop
	for _, p := range w.Root.Props {
		if p.Key == "mood" {
			found = p
		}
	}
	if found == nil {
		t.Fatal("world root missing 'mood' prop from top-level kind")
	}
	kv, ok := found.Value.(world.KindValue)
	if !ok {
		t.Fatalf("mood prop value type = %T, want KindValue", found.Value)
	}
	if kv.Name != "neutral" {
		t.Errorf("mood default = %q, want %q", kv.Name, "neutral")
	}
}

// ───────────────────────────────────────────────────────────────────────────
// Classes
// ───────────────────────────────────────────────────────────────────────────

func TestClassRegistration(t *testing.T) {
	src := `
class Ledger
    position: 0

class Rolodex extends Ledger
`
	f := parseSource(t, src)
	w := world.Build([]*ast.File{f}, nil)

	if len(w.Classes) != 2 {
		t.Fatalf("len(Classes) = %d, want 2", len(w.Classes))
	}
	ledger, ok := w.ClassMap["Ledger"]
	if !ok {
		t.Fatal("ClassMap missing Ledger")
	}
	if ledger.Parent != "" {
		t.Errorf("Ledger.Parent = %q, want empty", ledger.Parent)
	}
	rolodex := w.ClassMap["Rolodex"]
	if rolodex.Parent != "Ledger" {
		t.Errorf("Rolodex.Parent = %q, want Ledger", rolodex.Parent)
	}
}

func TestClassProps(t *testing.T) {
	src := `
class Ledger
    position: 0
    max_pages: 10
`
	f := parseSource(t, src)
	w := world.Build([]*ast.File{f}, nil)

	cls := w.ClassMap["Ledger"]
	if len(cls.Props) != 2 {
		t.Fatalf("Ledger has %d props, want 2", len(cls.Props))
	}
	if cls.Props[0].Key != "position" {
		t.Errorf("Props[0].Key = %q, want position", cls.Props[0].Key)
	}
	nv, ok := cls.Props[0].Value.(world.NumberValue)
	if !ok || nv.V != 0 {
		t.Errorf("Props[0].Value = %v, want NumberValue{0}", cls.Props[0].Value)
	}
}

func TestClassHandler_sigKeyResolvesself(t *testing.T) {
	src := `
class Ledger
    on examine self:
        say "A ledger."
`
	f := parseSource(t, src)
	w := world.Build([]*ast.File{f}, nil)

	cls := w.ClassMap["Ledger"]
	if len(cls.Handlers) != 1 {
		t.Fatalf("Ledger has %d handlers, want 1", len(cls.Handlers))
	}
	h := cls.Handlers[0]
	// "self" in a class body resolves to the class name in the sigKey.
	if h.SigKey != "examine Ledger" {
		t.Errorf("SigKey = %q, want %q", h.SigKey, "examine Ledger")
	}
}

func TestClassKindUse(t *testing.T) {
	src := `
kind lockable: *false, true
kind light: *extinguished, lit

class Lantern
    is lit
    is lockable
`
	f := parseSource(t, src)
	w := world.Build([]*ast.File{f}, nil)

	cls := w.ClassMap["Lantern"]
	propMap := propsByKey(cls.Props)

	if kv, ok := propMap["light"].(world.KindValue); !ok || kv.Name != "lit" {
		t.Errorf("Lantern.light = %v, want KindValue{lit}", propMap["light"])
	}
	if kv, ok := propMap["lockable"].(world.KindValue); !ok || kv.Name != "true" {
		t.Errorf("Lantern.lockable = %v, want KindValue{true}", propMap["lockable"])
	}
}

func TestClassKindUseNegate(t *testing.T) {
	src := `
kind lockable: *false, true

class SafeBox
    is not lockable
`
	f := parseSource(t, src)
	w := world.Build([]*ast.File{f}, nil)

	cls := w.ClassMap["SafeBox"]
	propMap := propsByKey(cls.Props)
	if kv, ok := propMap["lockable"].(world.KindValue); !ok || kv.Name != "false" {
		t.Errorf("SafeBox.lockable = %v, want KindValue{false}", propMap["lockable"])
	}
}

// ───────────────────────────────────────────────────────────────────────────
// Instances
// ───────────────────────────────────────────────────────────────────────────

func TestInstanceRegistration(t *testing.T) {
	src := `
Room kitchen "The kitchen."
Object brass lantern, lamp "A lantern."
`
	f := parseSource(t, src)
	w := world.Build([]*ast.File{f}, nil)

	kitchen, ok := w.NodeMap["kitchen"]
	if !ok {
		t.Fatal("NodeMap missing 'kitchen'")
	}
	if kitchen.ClassName != "Room" {
		t.Errorf("kitchen.ClassName = %q, want Room", kitchen.ClassName)
	}
	if kitchen.Desc != "The kitchen." {
		t.Errorf("kitchen.Desc = %q", kitchen.Desc)
	}

	lantern, ok := w.NodeMap["brass lantern"]
	if !ok {
		t.Fatal("NodeMap missing 'brass lantern'")
	}
	if len(lantern.Aliases) != 1 || lantern.Aliases[0] != "lamp" {
		t.Errorf("brass lantern aliases = %v, want [lamp]", lantern.Aliases)
	}
}

func TestInstanceIsChildOfRoot(t *testing.T) {
	src := `
Room kitchen "The kitchen."
Object table "A table."
`
	f := parseSource(t, src)
	w := world.Build([]*ast.File{f}, nil)

	childNames := make(map[string]bool)
	for _, c := range w.Root.Children {
		childNames[c.Name] = true
	}
	if !childNames["kitchen"] {
		t.Error("Root.Children missing 'kitchen'")
	}
	if !childNames["table"] {
		t.Error("Root.Children missing 'table'")
	}
}

func TestNestedInstance(t *testing.T) {
	src := `
Room kitchen "The kitchen."
    Object table "A table."
        Object cup "A cup."
`
	f := parseSource(t, src)
	w := world.Build([]*ast.File{f}, nil)

	kitchen := w.NodeMap["kitchen"]
	if len(kitchen.Children) != 1 || kitchen.Children[0].Name != "table" {
		t.Errorf("kitchen.Children = %v, want [table]", kitchen.Children)
	}

	table := w.NodeMap["table"]
	if table.Parent != kitchen {
		t.Error("table.Parent is not kitchen")
	}
	if len(table.Children) != 1 || table.Children[0].Name != "cup" {
		t.Errorf("table.Children = %v, want [cup]", table.Children)
	}

	cup := w.NodeMap["cup"]
	if cup.Parent != table {
		t.Error("cup.Parent is not table")
	}
}

func TestInstanceProps(t *testing.T) {
	src := `
Room kitchen "The kitchen."
    north: hallway
    max_occupants: 4

Room hallway "The hallway."
`
	f := parseSource(t, src)
	w := world.Build([]*ast.File{f}, nil)

	kitchen := w.NodeMap["kitchen"]
	propMap := propsByKey(kitchen.Props)

	ref, ok := propMap["north"].(world.RefValue)
	if !ok || ref.Name != "hallway" {
		t.Errorf("kitchen.north = %v, want RefValue{hallway}", propMap["north"])
	}
	nv, ok := propMap["max_occupants"].(world.NumberValue)
	if !ok || nv.V != 4 {
		t.Errorf("kitchen.max_occupants = %v, want NumberValue{4}", propMap["max_occupants"])
	}
}

func TestInstanceKindUse(t *testing.T) {
	src := `
kind light: *extinguished, lit
kind lockable: *false, true

Object brass lantern "A lantern."
    is lit
    is lockable
`
	f := parseSource(t, src)
	w := world.Build([]*ast.File{f}, nil)

	lantern := w.NodeMap["brass lantern"]
	propMap := propsByKey(lantern.Props)

	if kv, ok := propMap["light"].(world.KindValue); !ok || kv.Name != "lit" {
		t.Errorf("lantern.light = %v, want KindValue{lit}", propMap["light"])
	}
	if kv, ok := propMap["lockable"].(world.KindValue); !ok || kv.Name != "true" {
		t.Errorf("lantern.lockable = %v, want KindValue{true}", propMap["lockable"])
	}
}

func TestInstanceHandler_sigKeyResolvesself(t *testing.T) {
	src := `
Object yoke "A yoke."
    on examine self:
        say "A wooden yoke."
`
	f := parseSource(t, src)
	w := world.Build([]*ast.File{f}, nil)

	yoke := w.NodeMap["yoke"]
	if len(yoke.Handlers) != 1 {
		t.Fatalf("yoke has %d handlers, want 1", len(yoke.Handlers))
	}
	h := yoke.Handlers[0]
	if h.SigKey != "examine Object" {
		t.Errorf("SigKey = %q, want %q", h.SigKey, "examine Object")
	}
}

// ───────────────────────────────────────────────────────────────────────────
// Global handlers
// ───────────────────────────────────────────────────────────────────────────

func TestGlobalHandler(t *testing.T) {
	src := `
on traverse passage in the dark:
    say "You stumble through."
`
	f := parseSource(t, src)
	w := world.Build([]*ast.File{f}, nil)

	if len(w.Root.Handlers) != 1 {
		t.Fatalf("Root has %d handlers, want 1", len(w.Root.Handlers))
	}
	h := w.Root.Handlers[0]
	if h.SigKey != "traverse passage in the dark" {
		t.Errorf("SigKey = %q, want %q", h.SigKey, "traverse passage in the dark")
	}
	if h.Internal {
		t.Error("global handler should not be internal")
	}
}

func TestGlobalInternalHandler(t *testing.T) {
	src := `
internal has object:thing:
    succeed if player has thing
    fail
`
	f := parseSource(t, src)
	w := world.Build([]*ast.File{f}, nil)

	if len(w.Root.Handlers) != 1 {
		t.Fatalf("Root has %d handlers, want 1", len(w.Root.Handlers))
	}
	h := w.Root.Handlers[0]
	if !h.Internal {
		t.Error("handler should be internal")
	}
	// "has" is the keyword; "object" is the type of the parameter.
	if h.SigKey != "has object" {
		t.Errorf("SigKey = %q, want %q", h.SigKey, "has object")
	}
}

func TestGlobalEveryTurnHandler(t *testing.T) {
	src := `
on every turn:
    say "Time passes."
`
	f := parseSource(t, src)
	w := world.Build([]*ast.File{f}, nil)

	if len(w.Root.EveryTurn) != 1 {
		t.Fatalf("Root has %d every-turn handlers, want 1", len(w.Root.EveryTurn))
	}
}

func TestTurnRangeHandlers(t *testing.T) {
	src := `
on turn 1:
    say "First turn."

on turn 3-5:
    say "Middle turns."

on turn 10-:
    say "Late game."
`
	f := parseSource(t, src)
	w := world.Build([]*ast.File{f}, nil)

	if len(w.Root.TurnRanges) != 3 {
		t.Fatalf("Root has %d turn-range handlers, want 3", len(w.Root.TurnRanges))
	}
	tr := w.Root.TurnRanges
	if tr[0].From != 1 || tr[0].To != 1 {
		t.Errorf("turn-range[0]: {%d,%d}, want {1,1}", tr[0].From, tr[0].To)
	}
	if tr[1].From != 3 || tr[1].To != 5 {
		t.Errorf("turn-range[1]: {%d,%d}, want {3,5}", tr[1].From, tr[1].To)
	}
	if tr[2].From != 10 || tr[2].To != -1 {
		t.Errorf("turn-range[2]: {%d,%d}, want {10,-1}", tr[2].From, tr[2].To)
	}
}

// ───────────────────────────────────────────────────────────────────────────
// Vocabulary
// ───────────────────────────────────────────────────────────────────────────

func TestVocab(t *testing.T) {
	src := `
Object brass lantern, lamp "A lantern."
Room kitchen "The kitchen."
    Object table "A table."
`
	f := parseSource(t, src)
	w := world.Build([]*ast.File{f}, nil)

	cases := []struct{ form, want string }{
		{"brass lantern", "brass lantern"},
		{"lamp", "brass lantern"}, // alias
		{"kitchen", "kitchen"},
		{"table", "table"},
	}
	for _, c := range cases {
		got, ok := w.Vocab[c.form]
		if !ok {
			t.Errorf("Vocab[%q] missing", c.form)
			continue
		}
		if got != c.want {
			t.Errorf("Vocab[%q] = %q, want %q", c.form, got, c.want)
		}
	}
}

// ───────────────────────────────────────────────────────────────────────────
// Class-level kind → default prop
// ───────────────────────────────────────────────────────────────────────────

func TestClassKindCreatesDefaultProp(t *testing.T) {
	src := `
class Ledger
    kind opened: *closed, open
`
	f := parseSource(t, src)
	w := world.Build([]*ast.File{f}, nil)

	cls := w.ClassMap["Ledger"]
	propMap := propsByKey(cls.Props)
	kv, ok := propMap["opened"].(world.KindValue)
	if !ok {
		t.Fatalf("Ledger missing 'opened' prop; got props: %v", propMap)
	}
	if kv.Name != "closed" {
		t.Errorf("opened default = %q, want %q", kv.Name, "closed")
	}
}

// ───────────────────────────────────────────────────────────────────────────
// Inline doors
// ───────────────────────────────────────────────────────────────────────────

func TestInlineDoor(t *testing.T) {
	src := `
Room vestibule "An entrance."
    east: Door brass door
        leads to: kitchen

Room kitchen "The kitchen."
    west: Door brass door
        leads to: vestibule
`
	f := parseSource(t, src)
	w := world.Build([]*ast.File{f}, nil)

	// Shared inline door should create exactly one node.
	door, ok := w.NodeMap["brass door"]
	if !ok {
		t.Fatal("NodeMap missing 'brass door'")
	}
	if door.ClassName != "Door" {
		t.Errorf("brass door.ClassName = %q, want Door", door.ClassName)
	}

	// Both rooms should reference the door by name.
	vestibule := w.NodeMap["vestibule"]
	propMap := propsByKey(vestibule.Props)
	ref, ok := propMap["east"].(world.RefValue)
	if !ok || ref.Name != "brass door" {
		t.Errorf("vestibule.east = %v, want RefValue{brass door}", propMap["east"])
	}
}

func TestSharedInlineDoorMergesProperties(t *testing.T) {
	src := `
kind lockable: *false, true

Room vestibule "Entrance."
    east: Door brass door
        leads to: kitchen

Room kitchen "The kitchen."
    west: Door brass door
        leads to: vestibule
        is lockable
`
	f := parseSource(t, src)
	w := world.Build([]*ast.File{f}, nil)

	door := w.NodeMap["brass door"]
	propMap := propsByKey(door.Props)

	// First side contributes "leads to"
	if _, ok := propMap["leads to"]; !ok {
		t.Error("brass door missing 'leads to' from first side")
	}
	// Second side contributes "is lockable"
	if kv, ok := propMap["lockable"].(world.KindValue); !ok || kv.Name != "true" {
		t.Errorf("brass door.lockable = %v, want KindValue{true} from second side", propMap["lockable"])
	}
}

// ───────────────────────────────────────────────────────────────────────────
// Variable declarations
// ───────────────────────────────────────────────────────────────────────────

func TestVarDecl(t *testing.T) {
	src := `
var score
var energy: 100
`
	f := parseSource(t, src)
	w := world.Build([]*ast.File{f}, nil)

	propMap := propsByKey(w.Root.Props)

	if nv, ok := propMap["score"].(world.NumberValue); !ok || nv.V != 0 {
		t.Errorf("world.score = %v, want NumberValue{0}", propMap["score"])
	}
	if nv, ok := propMap["energy"].(world.NumberValue); !ok || nv.V != 100 {
		t.Errorf("world.energy = %v, want NumberValue{100}", propMap["energy"])
	}
}

// ───────────────────────────────────────────────────────────────────────────
// Array literals
// ───────────────────────────────────────────────────────────────────────────

func TestArrayLiteralProp(t *testing.T) {
	src := `
Object game
    primes: [2, 3, 5, 7, 11]
`
	f := parseSource(t, src)
	w := world.Build([]*ast.File{f}, nil)

	game := w.NodeMap["game"]
	if len(game.Props) != 1 {
		t.Fatalf("game has %d props, want 1", len(game.Props))
	}
	av, ok := game.Props[0].Value.(world.ArrayValue)
	if !ok {
		t.Fatalf("primes value type = %T, want ArrayValue", game.Props[0].Value)
	}
	if len(av.Items) != 5 {
		t.Errorf("primes has %d items, want 5", len(av.Items))
	}
	first, ok := av.Items[0].(world.NumberValue)
	if !ok || first.V != 2 {
		t.Errorf("primes[0] = %v, want NumberValue{2}", av.Items[0])
	}
}

// ───────────────────────────────────────────────────────────────────────────
// Library vs own
// ───────────────────────────────────────────────────────────────────────────

func TestLibraryIsMarked(t *testing.T) {
	ownSrc := `
"Test" by Test

Room kitchen "The kitchen."
`
	libSrc := `
on enter Room:room:
`
	own := parseSource(t, ownSrc)
	lib := parseSource(t, libSrc)
	w := world.Build([]*ast.File{own}, []*ast.File{lib})

	kitchen := w.NodeMap["kitchen"]
	if kitchen.IsLibrary {
		t.Error("kitchen should not be marked as library")
	}

	if len(w.Root.Handlers) != 1 {
		t.Fatalf("Root has %d handlers, want 1", len(w.Root.Handlers))
	}
	if !w.Root.Handlers[0].IsLibrary {
		t.Error("library handler should be marked IsLibrary")
	}
}

// ───────────────────────────────────────────────────────────────────────────
// Integration: classes.grue
// ───────────────────────────────────────────────────────────────────────────

func TestClassesIntegration(t *testing.T) {
	src := `
"Classes" by Test

class Ledger
    Object log
    position: 0
    kind opened: *closed, open

    on open self at number:page:
        position = page
        opened = open
        say "Opened {self} at position {page}."
        succeed opened

    on record string:entry in self:
        log.{position} = entry
        say "Recorded."
        succeed stored

class Rolodex extends Ledger
    on open self at number:page:
        say "Clack. Clack. Clack."
        parent

Rolodex rolodex "A clackity index card rolodex."
`
	f := parseSource(t, src)
	w := world.Build([]*ast.File{f}, nil)

	// Classes
	ledger := w.ClassMap["Ledger"]
	if ledger == nil {
		t.Fatal("ClassMap missing Ledger")
	}
	if len(ledger.Handlers) != 2 {
		t.Errorf("Ledger has %d handlers, want 2", len(ledger.Handlers))
	}
	// First handler: "on open self at number:page:" → "open Ledger at number"
	openKey := ledger.Handlers[0].SigKey
	if openKey != "open Ledger at number" {
		t.Errorf("Ledger handler[0].SigKey = %q, want %q", openKey, "open Ledger at number")
	}
	// Second handler: "on record string:entry in self:" → "record string in Ledger"
	recordKey := ledger.Handlers[1].SigKey
	if recordKey != "record string in Ledger" {
		t.Errorf("Ledger handler[1].SigKey = %q, want %q", recordKey, "record string in Ledger")
	}

	rolodex := w.ClassMap["Rolodex"]
	if rolodex.Parent != "Ledger" {
		t.Errorf("Rolodex.Parent = %q, want Ledger", rolodex.Parent)
	}
	if len(rolodex.Handlers) != 1 {
		t.Errorf("Rolodex has %d handlers, want 1", len(rolodex.Handlers))
	}
	// Rolodex's "on open self at number:page:" → "open Rolodex at number"
	if rolodex.Handlers[0].SigKey != "open Rolodex at number" {
		t.Errorf("Rolodex handler.SigKey = %q, want %q", rolodex.Handlers[0].SigKey, "open Rolodex at number")
	}

	// Instance
	inst := w.NodeMap["rolodex"]
	if inst == nil {
		t.Fatal("NodeMap missing 'rolodex'")
	}
	if inst.ClassName != "Rolodex" {
		t.Errorf("rolodex.ClassName = %q, want Rolodex", inst.ClassName)
	}
}

// ───────────────────────────────────────────────────────────────────────────
// sigKey helper tests
// ───────────────────────────────────────────────────────────────────────────

func TestSigKeyNoSelf(t *testing.T) {
	// on give Object:item to Object:npc:  → "give Object to Object"
	src := `
on give Object:item to Object:npc:
    say "Given."
`
	f := parseSource(t, src)
	w := world.Build([]*ast.File{f}, nil)

	if len(w.Root.Handlers) != 1 {
		t.Fatalf("want 1 handler, got %d", len(w.Root.Handlers))
	}
	h := w.Root.Handlers[0]
	if h.SigKey != "give Object to Object" {
		t.Errorf("SigKey = %q, want %q", h.SigKey, "give Object to Object")
	}
}

func TestSigKeyBareKeywords(t *testing.T) {
	// on traverse passage in the dark: (no params) → "traverse passage in the dark"
	src := `
on traverse passage in the dark:
    say "You stumble."
`
	f := parseSource(t, src)
	w := world.Build([]*ast.File{f}, nil)
	h := w.Root.Handlers[0]
	want := "traverse passage in the dark"
	if h.SigKey != want {
		t.Errorf("SigKey = %q, want %q", h.SigKey, want)
	}
}

// ───────────────────────────────────────────────────────────────────────────
// helpers
// ───────────────────────────────────────────────────────────────────────────

func propsByKey(props []*world.Prop) map[string]world.Value {
	m := make(map[string]world.Value)
	for _, p := range props {
		m[p.Key] = p.Value
	}
	return m
}

func containsStr(s, sub string) bool {
	return strings.Contains(s, sub)
}
