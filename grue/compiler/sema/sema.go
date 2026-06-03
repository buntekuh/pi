// Package sema performs semantic analysis on a parsed Grue AST.
// It validates the world model and returns a list of diagnostics.
//
// Errors prevent code generation. Warnings are reported but do not stop
// compilation.
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
var builtinBoolKinds = []string{"bidirectional"}

// compassReverse maps each standard direction to its opposite.
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

type instanceInfo struct {
	className string
	line      int
}

type handlerInfo struct {
	sig        []ast.SigPart
	ownerClass string // empty = top-level
	line       int
}

// analyser accumulates diagnostics across multiple passes over the AST.
type analyser struct {
	diags        []Diagnostic
	kindNames    map[string]int    // kind name → declaration line
	kindValues   map[string]string // value name → kind name (first declarer)
	classNames   map[string]int    // class name → declaration line (builtins at 0)
	classParents map[string]string // class name → parent name
	classOrder   []string          // class names in declaration order
	instances    map[string]instanceInfo // instance name → effective class
	handlers     []handlerInfo           // all declared handlers, for type checking
	failTokens   map[string]int    // identifier token → first fail/succeed line
	whenLabels   map[string]int    // unquoted when arm label → line
}

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

// Analyse runs all semantic checks on file and returns the diagnostics found.
func Analyse(file *ast.File) []Diagnostic {
	a := newAnalyser()
	a.collectDecls(file.Decls, "")
	a.inferDoorExits(file.Decls) // mutates AST before other passes see it
	a.checkKinds(file.Decls)
	a.checkInheritance()
	a.checkHandlerSigs(file.Decls)
	a.checkClassRefs(file.Decls)
	a.checkCallArgs(file.Decls)
	a.collectTokens(file.Decls)
	a.checkTokenCrossRefs()
	a.checkSingletons(file.Decls)
	return a.diags
}

// =============================================================================
// Singleton and reserved-name checks
// =============================================================================

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
// handler registries. currentClass is the owning class name (empty at top
// level) and is used to resolve "self" parameter types.
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
			// Effective class starts as the declaration class name.
			// "is ClassName" in the body overrides it — this is how an author
			// sets the runtime class of a generic Object instance.
			effectiveClass := d.ClassName
			for _, bodyDecl := range d.Body {
				if ku, ok := bodyDecl.(*ast.KindUseDecl); ok {
					if isCapitalized(ku.Value) && !ku.Negate {
						effectiveClass = ku.Value
					}
				}
			}
			a.instances[d.Name] = instanceInfo{className: effectiveClass, line: d.Pos.Line}
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
// Handler signature duplicate checks
// =============================================================================

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

func (a *analyser) checkClassRef(name string, line int) {
	if builtinParamTypes[name] || !isCapitalized(name) {
		return
	}
	if _, exists := a.classNames[name]; !exists {
		a.errorf("unknown_class", line, "unknown class %q", name)
	}
}

func (a *analyser) checkClassRefs(decls []ast.Decl) {
	for _, d := range decls {
		switch d := d.(type) {
		case *ast.HandlerDecl:
			for _, part := range d.Signature {
				if p, ok := part.(ast.SigParam); ok {
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
			a.checkClassRefs(d.Body)
		case *ast.InstanceDecl:
			a.checkClassRefs(d.Body)
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

// matchCallToHandler tries to match call words against a handler signature.
// Returns a map of argument word → parameter type, or nil if no match.
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
// Inline door reverse-exit inference
// =============================================================================

// inferDoorExits walks all Room instances looking for inline door property
// declarations (e.g. east: Door brass door / leads to: kitchen). For each
// bidirectional inline door it adds a synthetic reverse-exit PropertyDecl to
// the destination room so that both directions work without the author having
// to declare them twice.
func (a *analyser) inferDoorExits(decls []ast.Decl) {
	// Index rooms by name for fast lookup.
	rooms := make(map[string]*ast.InstanceDecl)
	for _, d := range decls {
		inst, ok := d.(*ast.InstanceDecl)
		if !ok {
			continue
		}
		if a.isSubclassOf(inst.ClassName, "Room") {
			rooms[inst.Name] = inst
		}
	}

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

			// Value must be a NameExpr starting with a capitalized class name.
			nameExpr, ok := prop.Value.(*ast.NameExpr)
			if !ok {
				continue
			}
			valueParts := strings.SplitN(nameExpr.Name, " ", 2)
			if len(valueParts) < 2 || !isCapitalized(valueParts[0]) {
				continue
			}
			className := valueParts[0]
			instanceName := valueParts[1]

			if !a.isSubclassOf(className, "Door") {
				continue
			}

			// Scan the door's inline body for leads to: and is not bidirectional.
			destination := ""
			bidirectional := true
			for _, item := range prop.Body {
				if p, ok := item.(*ast.PropertyDecl); ok && p.Key == "leads to" {
					if n, ok := p.Value.(*ast.NameExpr); ok {
						destination = n.Name
					}
				}
				if ku, ok := item.(*ast.KindUseDecl); ok &&
					ku.Value == "bidirectional" && ku.Negate {
					bidirectional = false
				}
			}

			if destination == "" {
				a.errorf("door_no_destination", prop.Pos.Line,
					"inline door %q requires a 'leads to:' property", instanceName)
				continue
			}
			if !bidirectional {
				continue
			}

			reverseDir, known := compassReverse[prop.Key]
			if !known {
				continue // custom direction — author must declare reverse manually
			}

			destRoom, exists := rooms[destination]
			if !exists {
				a.errorf("unknown_room", prop.Pos.Line,
					"door %q leads to unknown room %q", instanceName, destination)
				continue
			}

			// Add a synthetic reverse exit: reverseDir: instanceName
			destRoom.Body = append(destRoom.Body, &ast.PropertyDecl{
				Pos:   prop.Pos,
				Key:   reverseDir,
				Value: &ast.NameExpr{Pos: prop.Pos, Name: instanceName},
			})
		}
	}
}

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
