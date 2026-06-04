// Package world defines the Grue world tree intermediate representation (IR)
// and the builder that constructs it from a validated AST.
//
// The world tree is produced after semantic analysis and consumed by grammar
// construction and code generation. It captures the complete initial state of
// the game: all rooms, objects, classes, kinds, handlers, and the vocabulary
// used by the player-input parser.
//
// Structure overview:
//
//	World
//	├── Game       — title/author/version
//	├── Kinds      — all declared kind types
//	├── Classes    — class definitions (templates, not instances)
//	│   └── each Class: Parent, Props, Handlers, EveryTurn, TurnRanges
//	├── Root       — the singleton world node
//	│   ├── Props  — world-level vars and kind variables
//	│   ├── Handlers / EveryTurn / TurnRanges — global handlers
//	│   └── Children — all top-level instances (rooms, objects, doors, player…)
//	│       └── each Node: Props, Handlers, Children (nested instances)
//	├── NodeMap    — instance name → *Node for fast lookup
//	└── Vocab      — surface form (name/alias) → canonical instance name
package world

import (
	"gruc/ast"
)

// =============================================================================
// World — root structure
// =============================================================================

// World is the complete game IR produced by world tree construction.
// It is the input to grammar construction (Step 5) and code generation (Step 6).
type World struct {
	Game     GameInfo
	Kinds    []*Kind
	Classes  []*Class
	ClassMap map[string]*Class // class name → *Class
	Root     *Node             // singleton world root; children are top-level instances
	NodeMap  map[string]*Node  // instance name → *Node (all instances, including children)
	Vocab    map[string]string // surface form (name or alias) → canonical instance name
	Tests    []*Test           // all test blocks in declaration order
}

// =============================================================================
// Tests
// =============================================================================

// Test is a compiled test block — a named sequence of test steps.
// Room is non-empty when the test was declared inside an instance body; the
// test runner teleports the player to that location before running the steps.
type Test struct {
	Name  string
	Room  string
	Steps []TestStep
}

// TestStep is one command line inside a test body.
type TestStep struct {
	Cmd     string   // player command words joined by spaces; empty for expr or tick
	Expr    ast.Expr // non-nil for {expr} steps — compiled to a JS closure by codegen
	SubTest string   // non-empty for "test "name"." delegation lines
	Assert  string   // expected substring in turn output; empty means no assertion
	Negate  bool     // true for the "not" assertion form
}

// =============================================================================
// GameInfo
// =============================================================================

// GameInfo holds the game's metadata from the title declaration.
type GameInfo struct {
	Title   string
	Author  string
	Version string
}

// =============================================================================
// Kind
// =============================================================================

// Kind is a declared kind type — a named ordered set of values.
// The DefaultIdx is the index into Values of the default value (the one marked
// with * in source, or 0 if no * was given).
type Kind struct {
	Name       string
	Values     []string
	DefaultIdx int
}

// =============================================================================
// Class
// =============================================================================

// Class is a class definition. Classes are not world tree nodes — they are
// templates that instances inherit properties and handlers from.
//
// Handlers on a class apply when an instance of that class (or a subclass
// instance) is the argument in a player command.
type Class struct {
	Name       string
	Parent     string // empty → implicit Object parent
	Props      []*Prop
	Handlers   []*Handler
	Interfaces []*InterfaceHandler
	EveryTurn  []*EveryTurnHandler
	TurnRanges []*TurnRangeHandler
	Children   []*Node // instances declared inside the class body (rare)
	IsLibrary  bool
}

// =============================================================================
// Node
// =============================================================================

// Node is a world tree node — a declared instance of a class.
//
// The tree mirrors source-code containment: an object declared inside a room
// body is a Child of that room's node. Top-level declarations are Children
// of Root.
//
// Handlers declared directly on a node apply only when that specific instance
// is the argument — they take priority over class-level handlers.
type Node struct {
	Name       string
	ClassName  string
	Desc       string   // optional description string
	Aliases    []string // alternate names for vocabulary lookup
	Props      []*Prop
	Handlers   []*Handler
	Interfaces []*InterfaceHandler
	EveryTurn  []*EveryTurnHandler
	TurnRanges []*TurnRangeHandler
	Children   []*Node
	Parent     *Node // nil for direct children of Root
	IsLibrary  bool
}

// =============================================================================
// Prop and Value
// =============================================================================

// Prop is a key-value property on a node or class.
type Prop struct {
	Key   string
	Value Value
}

// Value is a tagged property value. Every concrete value type implements this
// interface.
type Value interface{ valueNode() }

// NumberValue is an integer literal property value.
type NumberValue struct{ V int }

// StringValue is a quoted string property value.
type StringValue struct{ V string }

// RefValue is a property value that refers to another instance by name.
// The code generator resolves this to a runtime object reference.
type RefValue struct{ Name string }

// KindValue is a kind value name (e.g. "lit", "sad", "true", "false").
// The code generator uses this to initialise the kind variable.
type KindValue struct{ Name string }

// UnsetValue is Grue's null — an explicitly absent property value.
type UnsetValue struct{}

// ListValue is a comma-separated list of values in a property declaration
// (e.g. context: mood, location). Used for multi-value properties.
type ListValue struct{ Items []Value }

// ArrayValue is an Array literal (e.g. primes: [2, 3, 5, 7, 11]).
// The code generator emits an inline Array object with integer keys 0..N-1.
type ArrayValue struct{ Items []Value }

func (NumberValue) valueNode() {}
func (StringValue) valueNode() {}
func (RefValue) valueNode()    {}
func (KindValue) valueNode()   {}
func (UnsetValue) valueNode()  {}
func (ListValue) valueNode()   {}
func (ArrayValue) valueNode()  {}

// =============================================================================
// Handler types
// =============================================================================

// Handler is a regular or internal on-handler declared on a node, class, or
// at global (world) scope.
//
// SigKey is the canonical dispatch key — keywords interleaved with resolved
// type names. "self" in a class or instance body is resolved to the owner's
// class name so that keys are stable for chain lookup.
//
// ResolvedSig mirrors Signature with every "self" type replaced by the
// declaring class name. Grammar construction uses ResolvedSig to determine
// the concrete parameter types for each slot without needing the ownerClass.
//
// Example: `on open self at number:page:` in class Ledger → SigKey = "open Ledger number"
// Example: `on open Ledger:ledger at number:page:` globally → SigKey = "open Ledger number"
type Handler struct {
	Internal    bool
	Signature   []ast.SigPart // raw AST signature (may contain "self" type)
	ResolvedSig []ast.SigPart // signature with "self" replaced by ownerClass
	SigKey      string        // keywords + resolved type names joined by spaces
	Body        []ast.Stmt    // raw AST body; the code generator compiles this
	IsLibrary   bool
}

// InterfaceHandler declares a handler that calls an external capability.
// It is always internal — never reachable by player input.
// Props holds the interface body (call:, function:, filename:, etc.).
type InterfaceHandler struct {
	Signature []ast.SigPart
	SigKey    string
	Props     []*Prop
	IsLibrary bool
}

// EveryTurnHandler fires unconditionally on every turn.
// Multiple EveryTurnHandlers at the same level fire in declaration order.
type EveryTurnHandler struct {
	Body      []ast.Stmt
	IsLibrary bool
}

// TurnRangeHandler fires on a specific turn or turn range.
// Multiple TurnRangeHandlers with the same range fire in declaration order.
//
// From and To are inclusive. To == -1 means no upper bound (fires from From
// onward). The special case From == 0, To == -1 is never produced — use
// EveryTurnHandler for unconditional turn firing.
type TurnRangeHandler struct {
	From      int // inclusive lower bound
	To        int // inclusive upper bound; -1 = no upper bound
	Body      []ast.Stmt
	IsLibrary bool
}
