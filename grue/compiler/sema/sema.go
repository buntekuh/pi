// Package sema performs semantic analysis on a parsed Grue AST.
// It validates the world model and returns a list of diagnostics.
//
// Errors prevent code generation. Warnings are reported but do not stop
// compilation.
//
// # Two-pass design
//
// Grue allows forward references everywhere — a room can name an exit that is
// declared later in the file, and a handler can call an instance that appears
// after it. A single-pass validator would therefore have to defer or re-check
// almost every reference.  Instead, sema uses two explicit passes:
//
//   - Pass 1 (Collect): walks all files and builds the symbol tables (kinds,
//     classes, instances, handlers, fail/succeed tokens, when-arm labels).
//     No diagnostics are emitted — the goal is a complete view of the world.
//
//   - Pass 2 (Check): uses the complete symbol tables to validate every
//     reference.  Errors here are definitive.
//
// The driver is responsible for loading included and library files between the
// two passes.  It calls Collect on the initial file(s), inspects
// Symbols.Includes and Symbols.Libraries, parses those files, then calls
// Collect again on the full set before calling Check.
package sema

import (
	"fmt"
	"strings"

	"gruc/ast"
)

// Severity classifies a diagnostic.
type Severity string

const (
	Error   Severity = "error"
	Warning Severity = "warning"
)

// Diagnostic is a single semantic finding with a source location, a stable
// code for test assertions, and a human-readable message.
type Diagnostic struct {
	Severity Severity
	Code     string
	Line     int
	Message  string
}

// builtinClasses exist without being declared.
var builtinClasses = map[string]bool{
	"Object": true, "Room": true, "Door": true, "Array": true,
	"Player": true, "Item": true, "Container": true, "Supporter": true,
	"Scenery": true, "Person": true, "Man": true, "Woman": true,
	"Animal": true, "Font": true, "Box": true,
}

// builtinClassParents defines the inheritance hierarchy for built-in classes.
var builtinClassParents = map[string]string{
	"Array":     "Object",
	"Player":    "Object",
	"Room":      "Object",
	"Door":      "Room",
	"Item":      "Object",
	"Container": "Item",
	"Supporter": "Item",
	"Scenery":   "Object",
	"Person":    "Object",
	"Man":       "Person",
	"Woman":     "Person",
	"Animal":    "Object",
	"Font":      "Object",
	"Box":       "Font",
}

// builtinKinds are world-level kinds pre-declared by the runtime.
// Values are listed without true/false (boolean kinds are handled separately).
var builtinKinds = map[string][]string{
	"gender":     {"neuter", "male", "female"},
	"game_state": {"running", "won", "lost", "ended"},
}

// builtinBoolKinds are boolean (true/false) kinds pre-declared by the runtime.
var builtinBoolKinds = []string{}

// compassReverse maps each standard direction to its opposite.
// Unused at present — reserved for automatic reverse-exit generation if that
// feature is added. Kept here alongside the other world-model tables.
var compassReverse = map[string]string{
	"north": "south", "south": "north",
	"east": "west", "west": "east",
	"up": "down", "down": "up",
	"in": "out", "out": "in",
	"northeast": "southwest", "southwest": "northeast",
	"northwest": "southeast", "southeast": "northwest",
}

// reservedInstances are instance names the author cannot declare more than once.
var reservedInstances = map[string]bool{
	"player": true, "text": true,
}

// builtinParamTypes are valid parameter type keywords that are not class names.
var builtinParamTypes = map[string]bool{
	"self": true, "object": true, "number": true, "string": true,
}

// instanceInfo records the declared class and source line of an instance.
// className is the ClassName from the InstanceDecl — it reflects any
// class-change applied by `is ClassName` in the body.
type instanceInfo struct {
	className string
	line      int
}

// handlerInfo records a handler signature and its owning scope for argument
// type checking.  ownerClass is empty for top-level handlers; "self" in the
// signature resolves to this class name.
type handlerInfo struct {
	sig        []ast.SigPart
	ownerClass string // empty = top-level
	line       int
}

// analyser accumulates all symbol tables and diagnostics across both passes.
type analyser struct {
	diags        []Diagnostic
	kindNames    map[string]int    // kind name → declaration line
	kindValues   map[string]string // value name → kind name (first declarer)
	classNames   map[string]int    // class name → declaration line (builtins at 0)
	classParents map[string]string // class name → parent name
	// classOrder preserves declaration order for deterministic cycle detection.
	// Map iteration in Go is random, so a plain map would produce non-deterministic
	// error messages when reporting inheritance cycles.
	classOrder   []string
	instances    map[string]instanceInfo // instance name → effective class
	handlers     []handlerInfo           // all declared handlers, used for bare-call type checking
	// failTokens and whenLabels are collected in pass 1 alongside declarations
	// so that forward references work — a when arm can appear before the handler
	// that produces its token.  Cross-references are checked at the end of pass 2.
	failTokens   map[string]int // identifier token → first fail/succeed line
	whenLabels   map[string]int // unquoted when arm label → first line
}

// newAnalyser returns an analyser pre-populated with all built-in classes,
// inheritance relationships, and kinds so that validation code does not need
// to special-case them.  Builtins are recorded at line 0 (no source location).
func newAnalyser() *analyser {
	a := &analyser{
		kindNames:    make(map[string]int),
		kindValues:   make(map[string]string),
		classNames:   make(map[string]int),
		classParents: make(map[string]string),
		instances:    make(map[string]instanceInfo),
		failTokens:   make(map[string]int),
		whenLabels:   make(map[string]int),
	}
	for name := range builtinClasses {
		a.classNames[name] = 0
	}
	for child, parent := range builtinClassParents {
		a.classParents[child] = parent
	}
	for kindName, values := range builtinKinds {
		a.kindNames[kindName] = 0
		for _, v := range values {
			a.kindValues[v] = kindName
		}
	}
	for _, kindName := range builtinBoolKinds {
		a.kindNames[kindName] = 0
	}
	return a
}

func (a *analyser) errorf(code string, line int, format string, args ...any) {
	a.diags = append(a.diags, Diagnostic{Error, code, line, fmt.Sprintf(format, args...)})
}

func (a *analyser) warnf(code string, line int, format string, args ...any) {
	a.diags = append(a.diags, Diagnostic{Warning, code, line, fmt.Sprintf(format, args...)})
}

// Symbols holds the declaration tables produced by Pass 1.
// Pass it to Check to run validation.
type Symbols struct {
	a         *analyser
	Includes  []string // paths from include directives, in declaration order
	Libraries []string // paths from library directives, in declaration order
}

// Collect runs Pass 1 on the given files and returns the populated symbol
// tables. No diagnostics are emitted; this is a pure collection pass.
//
// Typical driver sequence:
//
//	syms := sema.Collect(mainFile)
//	// load and parse syms.Includes and syms.Libraries
//	syms = sema.Collect(append(ownFiles, libFiles...)...)
//	diags := syms.Check(append(ownFiles, libFiles...)...)
func Collect(files ...*ast.File) *Symbols {
	a := newAnalyser()
	s := &Symbols{a: a}
	for _, f := range files {
		a.collectDecls(f.Decls, "")
		a.collectTokens(f.Decls)
		for _, d := range f.Decls {
			switch d := d.(type) {
			case *ast.IncludeDecl:
				s.Includes = append(s.Includes, d.Path)
			case *ast.LibraryImport:
				s.Libraries = append(s.Libraries, d.Path)
			}
		}
	}
	return s
}

// Check runs Pass 2 using the pre-collected symbol tables and returns all
// diagnostics.  files must be the complete set — the same slice that was
// passed to the final Collect call, including included and library files.
//
// mergeDoorDecls runs first because it validates the "leads to" cross-references
// that checkPropertyValueRefs would otherwise flag as unknown instance refs.
func (s *Symbols) Check(files ...*ast.File) []Diagnostic {
	return s.CheckFiles(files, nil)
}

// CheckFiles runs Pass 2 treating ownFiles and libFiles as separate namespaces
// for handler-signature duplicate detection.  A game-file handler with the same
// signature as a library handler is not an error — it is an intentional override.
// Duplicates within own files or within library files are still errors.
func (s *Symbols) CheckFiles(ownFiles, libFiles []*ast.File) []Diagnostic {
	var allDecls []ast.Decl
	for _, f := range append(ownFiles, libFiles...) {
		allDecls = append(allDecls, f.Decls...)
	}
	var ownDecls []ast.Decl
	for _, f := range ownFiles {
		ownDecls = append(ownDecls, f.Decls...)
	}
	var libDecls []ast.Decl
	for _, f := range libFiles {
		libDecls = append(libDecls, f.Decls...)
	}
	s.a.mergeDoorDecls(allDecls)
	s.a.checkKinds(allDecls)
	s.a.checkInheritance()
	s.a.checkHandlerSigs(ownDecls)
	s.a.checkHandlerSigs(libDecls)
	s.a.checkClassRefs(allDecls, false)
	s.a.checkKindUseRefs(allDecls)
	s.a.checkPropertyValueRefs(allDecls)
	s.a.checkCallArgs(allDecls)
	s.a.checkTokenCrossRefs()
	s.a.checkSingletons(allDecls)
	return s.a.diags
}

// Analyse runs both passes on the same set of files and returns all diagnostics.
// Equivalent to Collect(files...).Check(files...).
func Analyse(files ...*ast.File) []Diagnostic {
	return Collect(files...).Check(files...)
}

// =============================================================================
// Singleton and reserved-name checks
// =============================================================================

// checkSingletons enforces name reservation rules.
//
// "world" is different from "player" and "text": world is the implicit runtime
// root and can NEVER be declared (even once), while player and text are valid
// as a single declaration but not twice.  The distinction gives authors a
// clear error message for each case.
func (a *analyser) checkSingletons(decls []ast.Decl) {
	counts := make(map[string]int)
	for _, d := range decls {
		switch d := d.(type) {
		case *ast.InstanceDecl:
			if d.Name == "world" {
				a.errorf("reserved_name", d.Pos.Line,
					"'world' is the runtime root and cannot be declared")
			}
			if reservedInstances[d.Name] {
				counts[d.Name]++
				if counts[d.Name] > 1 {
					a.errorf("duplicate_singleton", d.Pos.Line,
						"'%s' may only be declared once", d.Name)
				}
			}
		case *ast.ClassDecl:
			if d.Name == "World" {
				a.errorf("reserved_name", d.Pos.Line,
					"'World' is reserved and cannot be declared as a class")
			}
		}
	}
}

// =============================================================================
// Pass 1 — collect declarations
// =============================================================================

// collectDecls walks decls and populates the class, kind, instance, and
// handler registries.  currentClass is the owning class name (empty at top
// level) and is forwarded to handlerInfo so that "self" parameter types can
// be resolved during argument type checking in pass 2.
//
// Only declaration-level constructs are registered; handler bodies (statements)
// are not walked because statements do not introduce new names into the symbol
// tables.  Duplicate instance detection happens here rather than in pass 2
// because the world builder needs a clean NodeMap — early detection prevents
// pass 3 from receiving conflicting data.
func (a *analyser) collectDecls(decls []ast.Decl, currentClass string) {
	for _, d := range decls {
		switch d := d.(type) {
		case *ast.KindDecl:
			a.kindNames[d.Name] = d.Pos.Line

		case *ast.ClassDecl:
			if _, exists := a.classNames[d.Name]; !exists {
				a.classNames[d.Name] = d.Pos.Line
				a.classOrder = append(a.classOrder, d.Name)
			}
			if d.Parent != "" {
				a.classParents[d.Name] = d.Parent
			}
			a.collectDecls(d.Body, d.Name)

		case *ast.InstanceDecl:
			if existing, exists := a.instances[d.Name]; exists && existing.line != 0 {
				a.errorf("duplicate_instance", d.Pos.Line,
					"instance %q already declared at line %d", d.Name, existing.line)
			} else {
				a.instances[d.Name] = instanceInfo{className: d.ClassName, line: d.Pos.Line}
			}
			a.collectDecls(d.Body, d.ClassName)

		case *ast.HandlerDecl:
			if !d.EveryTurn {
				a.handlers = append(a.handlers, handlerInfo{
					sig:        d.Signature,
					ownerClass: currentClass,
					line:       d.Pos.Line,
				})
			}
		}
	}
}

// =============================================================================
// Kind checks
// =============================================================================

// checkKinds enforces two rules:
//   - A kind name may only be declared once (kind_redeclared).
//   - No two kinds may share a value name (kind_value_conflict).
//
// Value uniqueness is what makes `if peter is sad` unambiguous — the compiler
// can look up "sad" in a global table and find "mood" without the author
// having to write `peter.mood is sad`.  true/false are exempt because they
// are intentionally shared by all boolean kinds.
func (a *analyser) checkKinds(decls []ast.Decl) {
	seen := make(map[string]int)
	for _, d := range decls {
		kd, ok := d.(*ast.KindDecl)
		if !ok {
			continue
		}
		if _, exists := seen[kd.Name]; exists {
			a.errorf("kind_redeclared", kd.Pos.Line, "kind %q already declared", kd.Name)
		} else {
			seen[kd.Name] = kd.Pos.Line
		}
		for _, v := range kd.Values {
			// true/false are boolean kind values shared by all boolean kinds — exempt.
			if v == "true" || v == "false" {
				continue
			}
			if existingKind, exists := a.kindValues[v]; exists {
				if existingKind != kd.Name {
					a.errorf("kind_value_conflict", kd.Pos.Line,
						"kind value %q already declared in kind %q", v, existingKind)
					break
				}
			} else {
				a.kindValues[v] = kd.Name
			}
		}
	}
}

// =============================================================================
// Inheritance checks
// =============================================================================

// checkInheritance validates that all parent class names exist and that there
// are no inheritance cycles.
//
// Cycle detection walks classOrder (not classParents directly) to maintain
// deterministic error reporting — Go map iteration is random, so using the
// map directly would produce different error lines on different runs.  For each
// class we walk the ancestor chain, keeping a path slice and a pathSet.  The
// pathSet detects when we re-enter a class we are already visiting (a cycle);
// the path slice lets us mark every class in the cycle via inCycle, so they
// are each reported exactly once rather than once per traversal start point.
func (a *analyser) checkInheritance() {
	for className, parentName := range a.classParents {
		if parentName == "World" {
			a.errorf("reserved_name", a.classNames[className],
				"class %q cannot extend World", className)
			continue
		}
		if _, exists := a.classNames[parentName]; !exists {
			a.errorf("unknown_class", a.classNames[className],
				"class %q extends unknown class %q", className, parentName)
		}
	}

	inCycle := make(map[string]bool)
	for _, className := range a.classOrder {
		if inCycle[className] {
			continue
		}
		path := []string{}
		pathSet := make(map[string]bool)
		current := className
		for {
			if pathSet[current] {
				a.errorf("inheritance_cycle", a.classNames[current],
					"class %q is part of an inheritance cycle", current)
				marking := false
				for _, n := range path {
					if n == current {
						marking = true
					}
					if marking {
						inCycle[n] = true
					}
				}
				inCycle[current] = true
				break
			}
			pathSet[current] = true
			path = append(path, current)
			parent, ok := a.classParents[current]
			if !ok {
				break
			}
			current = parent
		}
	}
}

// =============================================================================
// Property value reference checks
// =============================================================================

// checkPropertyValueRefs verifies that every NameExpr used as a property value
// refers to a declared instance.  This enforces that `north: hallway` requires
// hallway to exist somewhere in the source.
//
// Inline instance bodies (non-nil Body on a PropertyDecl, used for inline doors)
// are not checked here — their "leads to" destinations were already validated by
// mergeDoorDecls, which runs first in Check.
func (a *analyser) checkPropertyValueRefs(decls []ast.Decl) {
	for _, d := range decls {
		switch d := d.(type) {
		case *ast.InstanceDecl:
			a.checkPropertyValueRefsInBody(d.Body)
		case *ast.ClassDecl:
			a.checkPropertyValueRefsInBody(d.Body)
		}
	}
}

func (a *analyser) checkPropertyValueRefsInBody(decls []ast.Decl) {
	for _, d := range decls {
		prop, ok := d.(*ast.PropertyDecl)
		if !ok {
			continue
		}
		if len(prop.Body) > 0 {
			// Inline instance declaration — the value is a class+name spec
			// handled by door merging. Recurse to check nested properties.
			a.checkPropertyValueRefsInBody(prop.Body)
			continue
		}
		name, ok := prop.Value.(*ast.NameExpr)
		if !ok {
			continue
		}
		if _, exists := a.instances[name.Name]; !exists {
			a.errorf("unknown_instance_ref", prop.Pos.Line,
				"property %q refers to unknown instance %q", prop.Key, name.Name)
		}
	}
}

// =============================================================================
// Kind use reference checks
// =============================================================================

// checkKindUseRefs verifies that every `is X` / `is not X` declaration names a
// known kind value or kind name.
//
// Capitalised values get a specific deprecation error rather than "unknown kind
// value" because they were historically used for class-changing (`is Robot`),
// which is not supported.  The error message tells the author what to do instead.
func (a *analyser) checkKindUseRefs(decls []ast.Decl) {
	for _, d := range decls {
		switch d := d.(type) {
		case *ast.InstanceDecl:
			for _, bodyDecl := range d.Body {
				if ku, ok := bodyDecl.(*ast.KindUseDecl); ok {
					a.checkKindUseValue(ku)
				}
			}
			a.checkKindUseRefs(d.Body)
		case *ast.ClassDecl:
			for _, bodyDecl := range d.Body {
				if ku, ok := bodyDecl.(*ast.KindUseDecl); ok {
					a.checkKindUseValue(ku)
				}
			}
			a.checkKindUseRefs(d.Body)
		}
	}
}

func (a *analyser) checkKindUseValue(ku *ast.KindUseDecl) {
	if isCapitalized(ku.Value) {
		a.errorf("class_change_deprecated", ku.Pos.Line,
			"'is %s': changing an instance's class is not supported; declare the instance as %s directly",
			ku.Value, ku.Value)
		return
	}
	_, isValue := a.kindValues[ku.Value]
	_, isName := a.kindNames[ku.Value]
	if !isValue && !isName {
		a.errorf("unknown_kind_value", ku.Pos.Line,
			"'%s' is not a declared kind value or kind name", ku.Value)
	}
}

// =============================================================================
// Handler signature duplicate checks
// =============================================================================

// sigKey produces the canonical duplicate-detection key for a handler signature.
// Parameter names are dropped; only keywords and type names are kept.
// Two handlers with the same keywords/types but different parameter names are
// still duplicates — the player command pattern is identical.
//
// Note: this is a simpler version than world.sigKey.  It does NOT resolve "self"
// because duplicate detection only needs to compare signatures within one scope,
// and "self" means the same class in all handlers of the same class body.
func sigKey(sig []ast.SigPart) string {
	parts := make([]string, 0, len(sig))
	for _, p := range sig {
		switch p := p.(type) {
		case ast.SigKeyword:
			parts = append(parts, p.Word)
		case ast.SigParam:
			parts = append(parts, p.Type)
		}
	}
	return strings.Join(parts, " ")
}

// checkHandlerSigs detects duplicate handler signatures within each scope
// (global, per-class, per-instance).  Every-turn handlers are exempt because
// multiple `on every turn:` declarations at the same level are intentional —
// each fires independently in declaration order.
func (a *analyser) checkHandlerSigs(decls []ast.Decl) {
	seen := make(map[string]int)
	for _, d := range decls {
		switch d := d.(type) {
		case *ast.HandlerDecl:
			if d.EveryTurn {
				continue
			}
			key := sigKey(d.Signature)
			if _, exists := seen[key]; exists {
				a.errorf("duplicate_handler", d.Pos.Line,
					"handler %q already declared in this scope", key)
			} else {
				seen[key] = d.Pos.Line
			}
		case *ast.ClassDecl:
			a.checkHandlerSigs(d.Body)
		case *ast.InstanceDecl:
			a.checkHandlerSigs(d.Body)
		}
	}
}

// =============================================================================
// Class name reference checks
// =============================================================================

func isCapitalized(s string) bool {
	return len(s) > 0 && s[0] >= 'A' && s[0] <= 'Z'
}

// checkClassRef validates a single class-name reference.
// Built-in parameter type keywords (self, object, number, string) and
// lower-case names (kind values, instance names) are exempt — only capitalised
// identifiers that are not builtinParamTypes are expected to be class names.
func (a *analyser) checkClassRef(name string, line int) {
	if builtinParamTypes[name] || !isCapitalized(name) {
		return
	}
	if _, exists := a.classNames[name]; !exists {
		a.errorf("unknown_class", line, "unknown class %q", name)
	}
}

// checkClassRefs validates class-name references in handler signatures,
// is/isnt expressions, and filter() calls.  It descends into handler bodies
// because is/filter can appear anywhere in code.  inClass is true when
// descending into a class or instance body — needed to detect "self" at
// global scope, where it has no owning class to resolve to.
func (a *analyser) checkClassRefs(decls []ast.Decl, inClass bool) {
	for _, d := range decls {
		switch d := d.(type) {
		case *ast.HandlerDecl:
			for _, part := range d.Signature {
				if p, ok := part.(ast.SigParam); ok {
					if p.Type == "self" && !inClass {
						a.errorf("self_outside_class", d.Pos.Line,
							`"self" parameter type is only valid inside a class or instance body`)
					}
					a.checkClassRef(p.Type, d.Pos.Line)
				}
			}
			a.checkClassRefsInStmts(d.Body)
		case *ast.InterfaceHandlerDecl:
			for _, part := range d.Signature {
				if p, ok := part.(ast.SigParam); ok {
					a.checkClassRef(p.Type, d.Pos.Line)
				}
			}
		case *ast.ClassDecl:
			a.checkClassRefs(d.Body, true)
		case *ast.InstanceDecl:
			a.checkClassRefs(d.Body, true)
		}
	}
}

func (a *analyser) checkClassRefsInStmts(stmts []ast.Stmt) {
	for _, s := range stmts {
		a.checkClassRefsInStmt(s)
	}
}

func (a *analyser) checkClassRefsInStmt(s ast.Stmt) {
	if s == nil {
		return
	}
	switch s := s.(type) {
	case *ast.SayStmt:
		if s.Guard != nil {
			a.checkClassRefsInExpr(s.Guard.Cond)
		}
	case *ast.FailStmt:
		if s.Guard != nil {
			a.checkClassRefsInExpr(s.Guard.Cond)
		}
	case *ast.SucceedStmt:
		if s.Guard != nil {
			a.checkClassRefsInExpr(s.Guard.Cond)
		}
	case *ast.IfStmt:
		a.checkClassRefsInExpr(s.Cond)
		a.checkClassRefsInStmts(s.Body)
		for _, elif := range s.ElseIf {
			a.checkClassRefsInStmt(elif)
		}
		a.checkClassRefsInStmts(s.Else)
	case *ast.AssignStmt:
		a.checkClassRefsInExpr(s.Target)
		a.checkClassRefsInExpr(s.Value)
		if s.Guard != nil {
			a.checkClassRefsInExpr(s.Guard.Cond)
		}
	case *ast.MutateStmt:
		a.checkClassRefsInExpr(s.Target)
		a.checkClassRefsInExpr(s.Value)
		if s.Guard != nil {
			a.checkClassRefsInExpr(s.Guard.Cond)
		}
	case *ast.ForInStmt:
		a.checkClassRefsInExpr(s.Collection)
		a.checkClassRefsInStmts(s.Body)
	case *ast.ForFromStmt:
		a.checkClassRefsInExpr(s.From)
		a.checkClassRefsInExpr(s.To)
		a.checkClassRefsInStmts(s.Body)
	case *ast.RepeatStmt:
		a.checkClassRefsInExpr(s.From)
		a.checkClassRefsInExpr(s.To)
		a.checkClassRefsInStmts(s.Body)
	case *ast.WhenStmt:
		a.checkClassRefsInExpr(s.Expr)
		for _, arm := range s.Arms {
			a.checkClassRefsInStmts(arm.Body)
		}
	case *ast.ChooseStmt:
		for _, arm := range s.Arms {
			a.checkClassRefsInStmts(arm.Body)
		}
	case *ast.CallStmt:
		a.checkClassRefsInExpr(s.Call)
		if s.Guard != nil {
			a.checkClassRefsInExpr(s.Guard.Cond)
		}
	case *ast.BareCallStmt:
		a.checkClassRefsInExpr(s.Expr)
	case *ast.BareCallWithBodyStmt:
		a.checkClassRefsInExpr(s.Expr)
	}
}

func (a *analyser) checkClassRefsInExpr(e ast.Expr) {
	if e == nil {
		return
	}
	switch e := e.(type) {
	case *ast.BinaryExpr:
		if e.Op == "is" || e.Op == "isnt" {
			if name, ok := e.Right.(*ast.NameExpr); ok {
				a.checkClassRef(name.Name, e.Pos.Line)
			}
		}
		a.checkClassRefsInExpr(e.Left)
		a.checkClassRefsInExpr(e.Right)
	case *ast.UnaryExpr:
		a.checkClassRefsInExpr(e.Expr)
	case *ast.PropertyAccess:
		a.checkClassRefsInExpr(e.Object)
		a.checkClassRefsInExpr(e.KeyExpr)
	case *ast.FilterExpr:
		a.checkClassRefsInExpr(e.Collection)
		a.checkClassRef(e.ClassName, e.Pos.Line)
	case *ast.HandlerCallExpr:
		for _, part := range e.Parts {
			if arg, ok := part.(ast.HandlerCallArg); ok {
				a.checkClassRefsInExpr(arg.Expr)
			}
		}
	case *ast.FuncCallExpr:
		for _, arg := range e.Args {
			a.checkClassRefsInExpr(arg)
		}
	case *ast.IsSetExpr:
		a.checkClassRefsInExpr(e.Expr)
	}
}

// =============================================================================
// Argument type checks (bare calls)
// =============================================================================

// isSubclassOf reports whether class equals ancestor or is a descendant of it.
func (a *analyser) isSubclassOf(class, ancestor string) bool {
	current := class
	seen := make(map[string]bool)
	for {
		if current == ancestor {
			return true
		}
		if seen[current] {
			return false
		}
		seen[current] = true
		parent, ok := a.classParents[current]
		if !ok {
			return false
		}
		current = parent
	}
}

// resolveParamType converts "self" to the handler's ownerClass.
func resolveParamType(paramType, ownerClass string) string {
	if paramType == "self" {
		return ownerClass
	}
	return paramType
}

// matchCallToHandler tries to match a flat word slice against one handler
// signature. Returns a map of argument word → declared parameter type on
// success, or nil on no match.
//
// This is used only for bare-call argument type checking, not for grammar
// construction.  A nil return means "no match" — not an error by itself,
// because the call might match a different handler not yet checked.
func matchCallToHandler(words []string, sig []ast.SigPart) map[string]string {
	result := make(map[string]string)
	wi := 0
	for _, part := range sig {
		switch p := part.(type) {
		case ast.SigKeyword:
			if wi >= len(words) || words[wi] != p.Word {
				return nil
			}
			wi++
		case ast.SigParam:
			if wi >= len(words) {
				return nil
			}
			result[words[wi]] = p.Type
			wi++
		}
	}
	if wi != len(words) {
		return nil
	}
	return result
}

// checkCallArgs walks handler bodies looking for BareCallStmt nodes and
// validates their argument types.  Only bare calls (no braces) are checked
// here; braced handler calls ({...}) appear as expressions and are validated
// by the code generator which has richer context.
func (a *analyser) checkCallArgs(decls []ast.Decl) {
	for _, d := range decls {
		switch d := d.(type) {
		case *ast.HandlerDecl:
			a.checkCallArgsInStmts(d.Body)
		case *ast.ClassDecl:
			a.checkCallArgs(d.Body)
		case *ast.InstanceDecl:
			a.checkCallArgs(d.Body)
		}
	}
}

func (a *analyser) checkCallArgsInStmts(stmts []ast.Stmt) {
	for _, s := range stmts {
		a.checkCallArgsInStmt(s)
	}
}

func (a *analyser) checkCallArgsInStmt(s ast.Stmt) {
	if s == nil {
		return
	}
	switch s := s.(type) {
	case *ast.BareCallStmt:
		a.checkBareCallExpr(s.Expr, s.Pos)
	case *ast.IfStmt:
		a.checkCallArgsInStmts(s.Body)
		for _, elif := range s.ElseIf {
			a.checkCallArgsInStmt(elif)
		}
		a.checkCallArgsInStmts(s.Else)
	case *ast.ForInStmt:
		a.checkCallArgsInStmts(s.Body)
	case *ast.ForFromStmt:
		a.checkCallArgsInStmts(s.Body)
	case *ast.RepeatStmt:
		a.checkCallArgsInStmts(s.Body)
	case *ast.WhenStmt:
		for _, arm := range s.Arms {
			a.checkCallArgsInStmts(arm.Body)
		}
	case *ast.ChooseStmt:
		for _, arm := range s.Arms {
			a.checkCallArgsInStmts(arm.Body)
		}
	}
}

// checkBareCallExpr splits the call expression into words, tries to match
// against known handler signatures, and checks that instance arguments are
// compatible with the expected parameter types.
func (a *analyser) checkBareCallExpr(expr ast.Expr, pos ast.Pos) {
	name, ok := expr.(*ast.NameExpr)
	if !ok {
		return
	}
	words := strings.Fields(name.Name)
	if len(words) < 2 {
		return // single word, nothing to check
	}
	for _, h := range a.handlers {
		argMap := matchCallToHandler(words, h.sig)
		if argMap == nil {
			continue
		}
		for argWord, paramType := range argMap {
			expected := resolveParamType(paramType, h.ownerClass)
			if expected == "" || expected == "object" || expected == "number" || expected == "string" {
				continue // untyped or primitive — no class check
			}
			inst, exists := a.instances[argWord]
			if !exists {
				continue // not a known named instance
			}
			if !a.isSubclassOf(inst.className, expected) {
				a.errorf("argument_type_mismatch", pos.Line,
					"argument %q is of class %q, expected %q or a subclass",
					argWord, inst.className, expected)
			}
		}
		break // matched a handler — stop searching
	}
}

// =============================================================================
// Token cross-reference checks
// =============================================================================

// collectTokens records every identifier fail/succeed token and every unquoted
// when-arm label into the analyser tables.  Called in pass 1 so that forward
// references work — a when arm can appear in a caller before the handler that
// produces the token.  Only identifier tokens (NameExpr) are collected;
// quoted string tokens ("stored", "out of bounds") are author-validated and
// not cross-referenced by the compiler.
func (a *analyser) collectTokens(decls []ast.Decl) {
	for _, d := range decls {
		switch d := d.(type) {
		case *ast.HandlerDecl:
			a.collectTokensInStmts(d.Body)
		case *ast.ClassDecl:
			a.collectTokens(d.Body)
		case *ast.InstanceDecl:
			a.collectTokens(d.Body)
		}
	}
}

func (a *analyser) collectTokensInStmts(stmts []ast.Stmt) {
	for _, s := range stmts {
		a.collectTokensInStmt(s)
	}
}

func (a *analyser) collectTokensInStmt(s ast.Stmt) {
	if s == nil {
		return
	}
	switch s := s.(type) {
	case *ast.FailStmt:
		if s.Token != nil {
			if name, ok := s.Token.(*ast.NameExpr); ok {
				if _, exists := a.failTokens[name.Name]; !exists {
					a.failTokens[name.Name] = s.Pos.Line
				}
			}
		}
	case *ast.SucceedStmt:
		if s.Token != nil {
			if name, ok := s.Token.(*ast.NameExpr); ok {
				if _, exists := a.failTokens[name.Name]; !exists {
					a.failTokens[name.Name] = s.Pos.Line
				}
			}
		}
	case *ast.WhenStmt:
		for _, arm := range s.Arms {
			switch arm.Label {
			case "fail", "succeed", "default":
				// special labels — not cross-referenced
			default:
				if !arm.Quoted {
					if _, exists := a.whenLabels[arm.Label]; !exists {
						a.whenLabels[arm.Label] = arm.Pos.Line
					}
				}
			}
			a.collectTokensInStmts(arm.Body)
		}
	case *ast.IfStmt:
		a.collectTokensInStmts(s.Body)
		for _, elif := range s.ElseIf {
			a.collectTokensInStmt(elif)
		}
		a.collectTokensInStmts(s.Else)
	case *ast.ForInStmt:
		a.collectTokensInStmts(s.Body)
	case *ast.ForFromStmt:
		a.collectTokensInStmts(s.Body)
	case *ast.RepeatStmt:
		a.collectTokensInStmts(s.Body)
	case *ast.ChooseStmt:
		for _, arm := range s.Arms {
			a.collectTokensInStmts(arm.Body)
		}
	}
}

// =============================================================================
// Inline door merging
// =============================================================================

// mergeDoorDecls validates inline door declarations.
//
// An inline door is a PropertyDecl whose value contains a Door class name and
// an instance name, e.g. `east: Door brass door`.  The same door name can
// appear in at most two rooms:
//
//   - One room: one-way door; `leads to:` must name a known room.
//   - Two rooms: shared bidirectional door; both `leads to:` values must
//     cross-reference each other (A→B and B→A).  The compiler merges them
//     into a single shared object in the world tree.
//   - Three or more rooms: error.
//
// mergeDoorDecls runs before checkPropertyValueRefs because the door's inline
// `leads to:` value is a NameExpr that would otherwise fail as an unknown
// instance reference.  By validating it here first, checkPropertyValueRefs
// can safely skip inline bodies (PropertyDecl.Body != nil).
func (a *analyser) mergeDoorDecls(decls []ast.Decl) {
	rooms := make(map[string]*ast.InstanceDecl)
	for _, d := range decls {
		inst, ok := d.(*ast.InstanceDecl)
		if !ok || !a.isSubclassOf(inst.ClassName, "Room") {
			continue
		}
		rooms[inst.Name] = inst
	}

	type doorSide struct {
		room        string
		destination string
		line        int
	}
	sides := make(map[string][]doorSide)

	for _, d := range decls {
		inst, ok := d.(*ast.InstanceDecl)
		if !ok || !a.isSubclassOf(inst.ClassName, "Room") {
			continue
		}
		for _, bodyDecl := range inst.Body {
			prop, ok := bodyDecl.(*ast.PropertyDecl)
			if !ok || len(prop.Body) == 0 {
				continue
			}
			nameExpr, ok := prop.Value.(*ast.NameExpr)
			if !ok {
				continue
			}
			valueParts := strings.SplitN(nameExpr.Name, " ", 2)
			if len(valueParts) < 2 || !isCapitalized(valueParts[0]) {
				continue
			}
			if !a.isSubclassOf(valueParts[0], "Door") {
				continue
			}
			instanceName := valueParts[1]

			destination := ""
			for _, item := range prop.Body {
				if p, ok := item.(*ast.PropertyDecl); ok && p.Key == "leads to" {
					if n, ok := p.Value.(*ast.NameExpr); ok {
						destination = n.Name
					}
				}
			}
			if destination == "" {
				a.errorf("door_no_destination", prop.Pos.Line,
					"inline door %q requires a 'leads to:' property", instanceName)
				continue
			}
			sides[instanceName] = append(sides[instanceName], doorSide{
				room:        inst.Name,
				destination: destination,
				line:        prop.Pos.Line,
			})
		}
	}

	for name, ss := range sides {
		if len(ss) > 2 {
			a.errorf("door_too_many_sides", ss[2].line,
				"door %q declared in more than two rooms", name)
			continue
		}
		if len(ss) == 1 {
			if _, exists := rooms[ss[0].destination]; !exists {
				a.errorf("unknown_room", ss[0].line,
					"door %q leads to unknown room %q", name, ss[0].destination)
			}
			continue
		}
		sA, sB := ss[0], ss[1]
		if sA.destination != sB.room || sB.destination != sA.room {
			a.errorf("door_cross_ref_mismatch", sA.line,
				"door %q: sides do not cross-reference (room %q leads to %q, room %q leads to %q)",
				name, sA.room, sA.destination, sB.room, sB.destination)
		}
	}
}

// checkTokenCrossRefs emits warnings when fail/succeed identifier tokens and
// when-arm labels don't pair up.  Both directions are checked:
//
//   - A token produced by fail/succeed that no when arm catches suggests a
//     caller can never distinguish that outcome — likely a missing arm.
//   - A when arm that no fail/succeed produces suggests a dead branch or a
//     typo in the token name.
//
// These are warnings, not errors, because a handler may be designed to be
// called silently (the token is intentionally ignored by all callers).
func (a *analyser) checkTokenCrossRefs() {
	for token, line := range a.failTokens {
		if _, exists := a.whenLabels[token]; !exists {
			a.warnf("token_mismatch", line,
				"token %q produced by fail/succeed is never matched by a when arm", token)
		}
	}
	for label, line := range a.whenLabels {
		if _, exists := a.failTokens[label]; !exists {
			a.warnf("unhandled_token", line,
				"when arm %q is never produced by any fail or succeed", label)
		}
	}
}
