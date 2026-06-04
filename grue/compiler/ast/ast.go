// Package ast defines the Abstract Syntax Tree for Grue source files.
//
// The AST is produced by the parser and consumed by semantic analysis, world
// tree construction, grammar construction, and code generation. It mirrors the
// structure of a Grue source file closely — one node type per language construct.
//
// Node hierarchy:
//
//	Node
//	├── Decl  (top-level and body declarations)
//	├── Stmt  (statements inside handler bodies and test bodies)
//	└── Expr  (expressions — conditions, values, property access)
package ast

import "fmt"

// =============================================================================
// Position
// =============================================================================

// Pos records a source location for error messages and IDE integration.
// Line and Col are 1-based.
type Pos struct {
	Line int
	Col  int
}

func (p Pos) String() string {
	return fmt.Sprintf("%d:%d", p.Line, p.Col)
}

// =============================================================================
// Node interfaces
// =============================================================================

// Node is the root interface for all AST nodes.
type Node interface {
	Position() Pos
}

// Decl is a declaration — a top-level construct or a body-level item inside
// a class, room, object, or style.
type Decl interface {
	Node
	declNode()
}

// Stmt is a statement inside a handler body or test body.
type Stmt interface {
	Node
	stmtNode()
}

// Expr is an expression — a value, condition, or property access.
type Expr interface {
	Node
	exprNode()
}

// =============================================================================
// File
// =============================================================================

// File is the root node of a parsed Grue source file.
type File struct {
	Pos   Pos
	Decls []Decl
}

func (f *File) Position() Pos { return f.Pos }

// =============================================================================
// Declarations
// =============================================================================

// GameDecl is the title/author/version declaration at the top of a game file:
//
//	"Passing the Brass Lantern" by Bernd Eickhoff version guttoral goat
type GameDecl struct {
	Pos     Pos
	Title   string // quoted string
	Author  string // multi-word, no quotes
	Version string // optional multi-word codename
}

func (d *GameDecl) Position() Pos { return d.Pos }
func (d *GameDecl) declNode()     {}

// LibraryImport loads an external reusable library:
//
//	library "standard"
//	library "containers" as std
type LibraryImport struct {
	Pos   Pos
	Path  string // quoted path
	Alias string // optional alias after "as"
}

func (d *LibraryImport) Position() Pos { return d.Pos }
func (d *LibraryImport) declNode()     {}

// IncludeDecl merges another .grue file into this compilation unit:
//
//	include "chapter_2"
type IncludeDecl struct {
	Pos  Pos
	Path string
}

func (d *IncludeDecl) Position() Pos { return d.Pos }
func (d *IncludeDecl) declNode()     {}

// KindDecl declares a named ordered value type:
//
//	kind mood: happy, *neutral, sad
//	kind lockable: *false, true
//
// Values holds the declared values in order. DefaultIdx is the index of the
// value marked with *, or 0 if no * was present.
type KindDecl struct {
	Pos        Pos
	Name       string
	Values     []string
	DefaultIdx int
}

func (d *KindDecl) Position() Pos { return d.Pos }
func (d *KindDecl) declNode()     {}

// VarDecl declares a global numeric variable:
//
//	var score
//	var energy: 100
type VarDecl struct {
	Pos     Pos
	Name    string
	Initial Expr // nil if no initializer
}

func (d *VarDecl) Position() Pos { return d.Pos }
func (d *VarDecl) declNode()     {}

// ClassDecl declares a class with optional inheritance and a body:
//
//	class Ledger
//	class Rolodex extends Ledger
type ClassDecl struct {
	Pos    Pos
	Name   string
	Parent string // empty if no explicit parent (implicit Object)
	Body   []Decl
}

func (d *ClassDecl) Position() Pos { return d.Pos }
func (d *ClassDecl) declNode()     {}

// InstanceDecl is a Room, Door, Object, or any user-defined class instance:
//
//	Room kitchen "The smell of burnt coffee lingers."
//	Object brass lantern, lamp "A tarnished brass lantern."
//	Robot Benson "A stocky iron robot."
//
// ClassName is "Room", "Object", "Door", or any class name.
// Name is the instance name (may be multi-word).
// Aliases is the comma-separated list of alternate names.
// Desc is the optional description string.
type InstanceDecl struct {
	Pos       Pos
	ClassName string
	Name      string
	Aliases   []string
	Desc      string
	Body      []Decl
}

func (d *InstanceDecl) Position() Pos { return d.Pos }
func (d *InstanceDecl) declNode()     {}

// PropertyDecl is a key-value property on a node body:
//
//	north: hallway
//	max_occupants: 4
//	top of ladder: Mare Tranquillitatis
//	0: unset
//
// Key may be multi-word but must not contain reserved keywords as standalone
// words. The compiler validates this during semantic analysis.
// Body is non-nil when the value is an inline instance declaration with a block:
//
//	east: Door brass door
//	    leads to: kitchen
type PropertyDecl struct {
	Pos   Pos
	Key   string
	Value Expr   // UnsetExpr, NumberLit, StringLit, NameExpr, or ListLit
	Body  []Decl // non-nil for inline instance body
}

func (d *PropertyDecl) Position() Pos { return d.Pos }
func (d *PropertyDecl) declNode()     {}

// KindUseDecl applies a kind value to an instance in its body:
//
//	is lockable
//	is not lockable
//	is sad
type KindUseDecl struct {
	Pos    Pos
	Value  string // the kind value name
	Negate bool   // true for "is not lockable"
}

func (d *KindUseDecl) Position() Pos { return d.Pos }
func (d *KindUseDecl) declNode()     {}


// InterfaceHandlerDecl declares a handler that calls an external capability:
//
//	interface Object:response Object:request:
//	    call: js
//	    function: "processData"
//	    filename: "handlers.js"
//
// The response Object comes first; input parameters follow. The body contains
// only property declarations. The call: property identifies the target
// capability (currently only "js" is defined). Interface handlers are always
// internal — never reachable by player input.
type InterfaceHandlerDecl struct {
	Pos       Pos
	Signature []SigPart // type:name parameters; response first, inputs follow
	Body      []Decl    // PropertyDecls: call, function, filename, etc.
}

func (d *InterfaceHandlerDecl) Position() Pos { return d.Pos }
func (d *InterfaceHandlerDecl) declNode()     {}

// HandlerDecl is a public or internal handler:
//
//	on open Ledger:ledger at number:page:
//	internal has object:thing:
//	on every turn:
//
// Internal marks internal handlers. Signature is nil for "on every turn:".
type HandlerDecl struct {
	Pos        Pos
	Internal   bool
	EveryTurn  bool // true for "on every turn:"
	Signature  []SigPart
	Body       []Stmt
}

func (d *HandlerDecl) Position() Pos { return d.Pos }
func (d *HandlerDecl) declNode()     {}

// TurnHandlerDecl fires on a specific turn or turn range:
//
//	on turn 1:       From=1,  To=1   (exact)
//	on turn 5-6:     From=5,  To=6   (inclusive range)
//	on turn 7-:      From=7,  To=-1  (7 and beyond)
//	on turn -8:      From=0,  To=8   (up to and including 8)
//
// To=-1 means no upper bound.
type TurnHandlerDecl struct {
	Pos  Pos
	From int
	To   int
	Body []Stmt
}

func (d *TurnHandlerDecl) Position() Pos { return d.Pos }
func (d *TurnHandlerDecl) declNode()     {}

// TestDecl is a named or default test block:
//
//	test
//	test "open rolodex"
type TestDecl struct {
	Pos  Pos
	Name string // empty for the default test
	Body []Stmt
}

func (d *TestDecl) Position() Pos { return d.Pos }
func (d *TestDecl) declNode()     {}

// =============================================================================
// Handler signatures
// =============================================================================

// SigPart is one element of a handler signature — either a keyword or a
// typed parameter.
type SigPart interface {
	sigPartNode()
}

// SigKeyword is a bare word in a handler signature:
//
//	on open ... at ... :   →  "open" and "at" are SigKeywords
type SigKeyword struct {
	Word string
}

func (s SigKeyword) sigPartNode() {}

// SigParam is a typed parameter in a handler signature:
//
//	Ledger:ledger   number:page   object:item   string:text
//
// Type is the type name (Object, number, string, or a class name).
// Name is the parameter variable name, or "self" for the self parameter.
type SigParam struct {
	Type string
	Name string
}

func (s SigParam) sigPartNode() {}

// =============================================================================
// Statements
// =============================================================================

// SayStmt outputs text, optionally with a block style:
//
//	say "The lamp flickers."
//	say mono "SECTOR 7 status report."
type SayStmt struct {
	Pos   Pos
	Style string // empty for unstyled say
	Text  Expr   // StringLit (may contain {interpolation} and [directives])
	Guard *Guard
}

func (s *SayStmt) Position() Pos { return s.Pos }
func (s *SayStmt) stmtNode()     {}

// FailStmt exits the handler with failure:
//
//	fail
//	fail out_of_bounds
//	fail "out of bounds"
//	fail out_of_bounds if page >= 10
type FailStmt struct {
	Pos   Pos
	Token Expr  // nil for anonymous fail; StringLit or NameExpr for token
	Guard *Guard
}

func (s *FailStmt) Position() Pos { return s.Pos }
func (s *FailStmt) stmtNode()     {}

// SucceedStmt exits the handler with success:
//
//	succeed
//	succeed stored
//	succeed "stored"
//	succeed if player has self
type SucceedStmt struct {
	Pos   Pos
	Token Expr  // nil for anonymous succeed
	Guard *Guard
}

func (s *SucceedStmt) Position() Pos { return s.Pos }
func (s *SucceedStmt) stmtNode()     {}

// ParentStmt calls the next handler in the chain:
//
//	parent
type ParentStmt struct {
	Pos Pos
}

func (s *ParentStmt) Position() Pos { return s.Pos }
func (s *ParentStmt) stmtNode()     {}

// AssignStmt assigns a value to a property or variable:
//
//	score = score * 2
//	score += 10
//	score -= 1
//	lamp.light = lit
//	log.{position} = "Jason"
type AssignStmt struct {
	Pos      Pos
	Target   Expr   // NameExpr or PropertyAccess
	Operator string // "=", "+=", "-="
	Value    Expr
	Guard    *Guard
}

func (s *AssignStmt) Position() Pos { return s.Pos }
func (s *AssignStmt) stmtNode()     {}

// MutateStmt is the shorthand score + 10 / score - 1 mutation form.
// Equivalent to score += 10 / score -= 1 but reads as an intent to modify.
type MutateStmt struct {
	Pos      Pos
	Target   Expr
	Operator string // "+" or "-"
	Value    Expr
	Guard    *Guard
}

func (s *MutateStmt) Position() Pos { return s.Pos }
func (s *MutateStmt) stmtNode()     {}

// IfStmt is a block or postfix conditional:
//
//	if x > 5:
//	    say "Big."
//	else if x == 5:
//	    say "Five."
//	else:
//	    say "Small."
type IfStmt struct {
	Pos    Pos
	Unless bool // true for "unless"
	Cond   Expr
	Body   []Stmt
	ElseIf []*IfStmt
	Else   []Stmt
}

func (s *IfStmt) Position() Pos { return s.Pos }
func (s *IfStmt) stmtNode()     {}

// ForInStmt iterates over the children of a collection:
//
//	for item in player.filter(Object):
//	for key, value in kitchen:
type ForInStmt struct {
	Pos        Pos
	Key        string // variable for key (or only variable in single-value form)
	Value      string // variable for value; empty in single-value form
	Collection Expr
	Body       []Stmt
}

func (s *ForInStmt) Position() Pos { return s.Pos }
func (s *ForInStmt) stmtNode()     {}

// ForFromStmt iterates over a numeric range with an index variable:
//
//	for i from 0 to max_slots:
type ForFromStmt struct {
	Pos  Pos
	Var  string
	From Expr
	To   Expr
	Body []Stmt
}

func (s *ForFromStmt) Position() Pos { return s.Pos }
func (s *ForFromStmt) stmtNode()     {}

// RepeatStmt repeats a block a fixed number of times with no loop variable:
//
//	from 0 to 3:
//	    say "Your wish is granted."
type RepeatStmt struct {
	Pos  Pos
	From Expr
	To   Expr
	Body []Stmt
}

func (s *RepeatStmt) Position() Pos { return s.Pos }
func (s *RepeatStmt) stmtNode()     {}

// WhenStmt dispatches on the token result of a handler call, or on any string:
//
//	when {traverse passage in the dark}:
//	    eaten_by_grue: ...
//	    fail:          ...
//	    succeed:       ...
//	    default:       ...
//
//	when location.name:
//	    "kitchen": ...
//	    default:   ...
type WhenStmt struct {
	Pos  Pos
	Expr Expr // the handler call or string expression to dispatch on
	Arms []WhenArm
}

func (s *WhenStmt) Position() Pos { return s.Pos }
func (s *WhenStmt) stmtNode()     {}

// WhenArm is one arm of a when statement.
// Label is the token string, "fail", "succeed", or "default".
// Quoted is true when the label was a quoted string — quoted labels are not
// cross-referenced against fail/succeed tokens.
type WhenArm struct {
	Pos    Pos
	Label  string
	Quoted bool
	Body   []Stmt
}

// ChooseStmt presents labeled options to the player:
//
//	choose "What do you want to talk about?":
//	    "Tell me about Jason.":
//	        ...
type ChooseStmt struct {
	Pos    Pos
	Prompt string // optional prompt string
	Arms   []ChooseArm
}

func (s *ChooseStmt) Position() Pos { return s.Pos }
func (s *ChooseStmt) stmtNode()     {}

// ChooseArm is one labeled option in a choose statement.
type ChooseArm struct {
	Pos   Pos
	Label string
	Body  []Stmt
}

// CallStmt calls a handler as a standalone statement:
//
//	{beep self}
//	{move item to room}
type CallStmt struct {
	Pos  Pos
	Call *HandlerCallExpr
	Guard *Guard
}

func (s *CallStmt) Position() Pos { return s.Pos }
func (s *CallStmt) stmtNode()     {}

// TestCmdStmt is a command line inside a test body:
//
//	open rolodex at 3. "Opened rolodex at position 3."
//	open rolodex at 10. not "Opened"
//	test "other test".
//	{3 + 4}. "7"
//
// Command is the player command (sequence of words/numbers/strings).
// Expr is non-nil when the command is a {expression} — the expression is
// evaluated and its string result is checked against the assertion.
// Assertion is nil for a bare command. NotAssertion inverts the check.
type TestCmdStmt struct {
	Pos          Pos
	Command      []string // words of the command; empty when Expr is set
	Expr         Expr     // non-nil for {expr} assertion form
	Assertion    *string  // expected output substring; nil = no assertion
	NotAssertion bool     // true for "not" form
	SubTest      string   // non-empty if this is "test "name"."
}

func (s *TestCmdStmt) Position() Pos { return s.Pos }
func (s *TestCmdStmt) stmtNode()     {}

// BareCallStmt is a handler call written without { } braces and without an
// inline body — a plain statement call:
//
//	operate car
//	fix machine with spanner
type BareCallStmt struct {
	Pos  Pos
	Expr Expr
}

func (s *BareCallStmt) Position() Pos { return s.Pos }
func (s *BareCallStmt) stmtNode()     {}

// BareCallWithBodyStmt is a handler call written without { } braces, followed
// by an inline object body. The final argument is a new inline instance whose
// properties are given in the indented block. The class name is required:
//
//	play Sound:sound:
//	    file: "pling.wav"
//	    volume: 80
//
// Expr captures the call expression. Body contains property declarations for
// the inline object.
type BareCallWithBodyStmt struct {
	Pos  Pos
	Expr Expr
	Body []Decl
}

func (s *BareCallWithBodyStmt) Position() Pos { return s.Pos }
func (s *BareCallWithBodyStmt) stmtNode()     {}

// VarStmt is a local variable declaration inside a handler body:
//
//	var n
//	var d: absolute(score - target)
//
// It mirrors VarDecl but implements Stmt instead of Decl.
type VarStmt struct {
	Pos     Pos
	Name    string
	Initial Expr // nil if no initializer
}

func (s *VarStmt) Position() Pos { return s.Pos }
func (s *VarStmt) stmtNode()     {}

// StopStmt is the stop built-in that disables all further player input.
// Unlike end/quit/save/load (which are library handlers), stop is a runtime
// primitive — it cannot be overridden.
type StopStmt struct{ Pos Pos }

func (s *StopStmt) Position() Pos { return s.Pos }
func (s *StopStmt) stmtNode()     {}


// =============================================================================
// Guard (postfix if / unless)
// =============================================================================

// Guard is an optional postfix condition attached to a statement:
//
//	fail out_of_bounds if page >= 10
//	say "The torch dims." unless energy > 0
//
// Unless=true means "unless"; Unless=false means "if".
type Guard struct {
	Unless bool
	Cond   Expr
}

// =============================================================================
// Expressions
// =============================================================================

// ListLit is a comma-separated list of values in a property declaration:
//
//	context: mood, location
type ListLit struct {
	Pos   Pos
	Items []Expr
}

func (e *ListLit) Position() Pos { return e.Pos }
func (e *ListLit) exprNode()     {}

// ArrayLit is an Array literal: [expr, expr, ...].
// Creates an Array instance with auto-assigned integer keys starting at 0.
// Only unkeyed expressions are permitted — named properties inside [...]
// are a compile error enforced by the semantic analyser.
type ArrayLit struct {
	Pos   Pos
	Items []Expr
}

func (e *ArrayLit) Position() Pos { return e.Pos }
func (e *ArrayLit) exprNode()     {}

// NumberLit is an integer literal: 0, 10, 42.
type NumberLit struct {
	Pos   Pos
	Value int
}

func (e *NumberLit) Position() Pos { return e.Pos }
func (e *NumberLit) exprNode()     {}

// StringLit is a double-quoted string. Value holds the content after
// multi-line whitespace collapsing. {interpolation} and [directives] are
// preserved verbatim for the code generator to expand.
type StringLit struct {
	Pos   Pos
	Value string
}

func (e *StringLit) Position() Pos { return e.Pos }
func (e *StringLit) exprNode()     {}

// NameExpr is a reference to a variable, object, kind value, or class name.
// The name may be multi-word ("brass lantern", "great hall").
// The semantic analysis stage resolves what it refers to.
type NameExpr struct {
	Pos  Pos
	Name string
}

func (e *NameExpr) Position() Pos { return e.Pos }
func (e *NameExpr) exprNode()     {}

// UnsetExpr is the literal `unset` — Grue's null value.
type UnsetExpr struct {
	Pos Pos
}

func (e *UnsetExpr) Position() Pos { return e.Pos }
func (e *UnsetExpr) exprNode()     {}

// PropertyAccess is a property lookup: lamp.light, log.{position}, world.styles.mono.
// Dynamic is true when the key is computed ({expr}); Static is the literal key name.
type PropertyAccess struct {
	Pos     Pos
	Object  Expr
	Key     string // non-empty for static: lamp.light
	KeyExpr Expr   // non-nil for dynamic: log.{position}
}

func (e *PropertyAccess) Position() Pos { return e.Pos }
func (e *PropertyAccess) exprNode()     {}

// BinaryExpr is a binary operation:
//
//	a + b     a == b     a is b     a and b     a modulo b
//
// Op is the operator string: "+", "-", "*", "/", "==", "<", ">", "<=", ">=",
// "is", "isnt", "and", "or", "modulo".
type BinaryExpr struct {
	Pos   Pos
	Left  Expr
	Op    string
	Right Expr
}

func (e *BinaryExpr) Position() Pos { return e.Pos }
func (e *BinaryExpr) exprNode()     {}

// UnaryExpr is a unary operation: not a.
type UnaryExpr struct {
	Pos  Pos
	Op   string // "not"
	Expr Expr
}

func (e *UnaryExpr) Position() Pos { return e.Pos }
func (e *UnaryExpr) exprNode()     {}

// IsSetExpr is the is set / is unset check:
//
//	log.{position} is set
//	log.{position} is unset
type IsSetExpr struct {
	Pos  Pos
	Expr Expr
	Set  bool // true for "is set", false for "is unset"
}

func (e *IsSetExpr) Position() Pos { return e.Pos }
func (e *IsSetExpr) exprNode()     {}

// FuncCallExpr is a built-in math function call:
//
//	floor(score / 2)
//	absolute(score - target)
//	biggest(score, 0)
//	random(1, 6)
//
// Name is one of: floor, ceiling, round, absolute, biggest, smallest, random, seed.
type FuncCallExpr struct {
	Pos  Pos
	Name string
	Args []Expr
}

func (e *FuncCallExpr) Position() Pos { return e.Pos }
func (e *FuncCallExpr) exprNode()     {}

// FilterExpr is collection.filter(ClassName):
//
//	player.filter(Object)
//	location.filter(Room)
type FilterExpr struct {
	Pos        Pos
	Collection Expr
	ClassName  string
}

func (e *FilterExpr) Position() Pos { return e.Pos }
func (e *FilterExpr) exprNode()     {}

// HandlerCallExpr is an inline handler call: {handler args silently?}
//
//	{has ledger silently}
//	{traverse passage in the dark}
//	{open ledger at page}
//
// Parts holds the words and expressions of the call.
// Silently is true if the call ends with "silently".
type HandlerCallExpr struct {
	Pos      Pos
	Parts    []HandlerCallPart
	Silently bool
}

func (e *HandlerCallExpr) Position() Pos { return e.Pos }
func (e *HandlerCallExpr) exprNode()     {}

// HandlerCallPart is one element of an inline handler call — either a keyword
// word or an argument expression.
type HandlerCallPart interface {
	handlerCallPartNode()
}

type HandlerCallWord struct{ Word string }
type HandlerCallArg  struct{ Expr Expr }

func (HandlerCallWord) handlerCallPartNode() {}
func (HandlerCallArg) handlerCallPartNode()  {}
