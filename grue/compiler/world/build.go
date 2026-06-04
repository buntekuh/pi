package world

import (
	"gruc/ast"
	"strings"
)

// builtinKindValues maps kind values pre-declared by the runtime to their
// kind name. These kinds appear in the runtime without source declarations.
var builtinKindValues = map[string]string{
	"neuter": "gender", "male": "gender", "female": "gender",
	"running": "game_state", "won": "game_state", "lost": "game_state", "ended": "game_state",
}

// Build constructs the world tree IR from validated AST files.
//
// ownFiles are the game's own source files (main file plus any includes).
// libFiles are the library files loaded via library "..." directives.
// Both slices must have passed sema.Analyse without errors before calling Build.
//
// Processing order within each group mirrors source order so that declaration
// position determines child order in the world tree.
func Build(ownFiles, libFiles []*ast.File) *World {
	b := &builder{
		w: &World{
			ClassMap: make(map[string]*Class),
			NodeMap:  make(map[string]*Node),
			Vocab:    make(map[string]string),
		},
		kindOf: make(map[string]string),
	}
	for val, kind := range builtinKindValues {
		b.kindOf[val] = kind
	}

	b.w.Root = &Node{Name: "world", ClassName: "World"}

	b.pass1Kinds(ownFiles)
	b.pass1Kinds(libFiles)
	b.pass2Classes(ownFiles, false)
	b.pass2Classes(libFiles, true)
	b.pass3TopLevel(ownFiles, false)
	b.pass3TopLevel(libFiles, true)
	b.buildVocab()
	return b.w
}

// =============================================================================
// builder — internal state
// =============================================================================

type builder struct {
	w      *World
	kindOf map[string]string // kind value name → kind name; "true"/"false" excluded
}

// =============================================================================
// Pass 1 — collect kinds into b.kindOf
// =============================================================================

// pass1Kinds populates b.kindOf and b.w.Kinds from all kind declarations.
// This must run before pass2Classes and pass3TopLevel because both of those
// call buildKindUse, which needs b.kindOf to map a kind value ("sad", "lit")
// back to its kind name ("mood", "light") in order to set the right prop key.
func (b *builder) pass1Kinds(files []*ast.File) {
	for _, f := range files {
		b.collectKindsFromDecls(f.Decls)
	}
}

// collectKindsFromDecls walks decls recursively to reach kinds declared inside
// class and instance bodies (e.g. `kind opened: *closed, open` inside a class).
// true/false are excluded from b.kindOf because they are valid values in ANY
// boolean kind, not tied to a single kind name.
func (b *builder) collectKindsFromDecls(decls []ast.Decl) {
	for _, d := range decls {
		switch d := d.(type) {
		case *ast.KindDecl:
			kind := &Kind{
				Name:       d.Name,
				Values:     d.Values,
				DefaultIdx: d.DefaultIdx,
			}
			b.w.Kinds = append(b.w.Kinds, kind)
			for _, v := range d.Values {
				if v != "true" && v != "false" {
					b.kindOf[v] = d.Name
				}
			}
		case *ast.ClassDecl:
			b.collectKindsFromDecls(d.Body)
		case *ast.InstanceDecl:
			b.collectKindsFromDecls(d.Body)
		}
	}
}

// =============================================================================
// Pass 2 — build class definitions
// =============================================================================

// pass2Classes builds Class definitions from all ClassDecl nodes.
// Classes must be built before instances (pass 3) because instance handlers
// use ownerClass = d.ClassName to resolve "self" in sigKey — but that class
// name only matters for sigKey computation, not for class lookup.  The more
// important reason is that class Children (objects declared inside a class
// body) are registered in NodeMap here so pass 3 can reference them.
func (b *builder) pass2Classes(files []*ast.File, isLibrary bool) {
	for _, f := range files {
		for _, d := range f.Decls {
			if cd, ok := d.(*ast.ClassDecl); ok {
				cls := b.buildClass(cd, isLibrary)
				b.w.Classes = append(b.w.Classes, cls)
				b.w.ClassMap[cls.Name] = cls
			}
		}
	}
}

func (b *builder) buildClass(cd *ast.ClassDecl, isLibrary bool) *Class {
	cls := &Class{
		Name:      cd.Name,
		Parent:    cd.Parent,
		IsLibrary: isLibrary,
	}
	for _, bodyDecl := range cd.Body {
		b.addToClass(cls, bodyDecl, cd.Name, isLibrary)
	}
	return cls
}

// addToClass dispatches a single declaration from a class body into the
// appropriate Class field.  ownerClass is the declaring class's name; it is
// passed to buildHandler so that "self" in handler signatures can be resolved
// to the concrete class name for sigKey computation.
func (b *builder) addToClass(cls *Class, d ast.Decl, ownerClass string, isLibrary bool) {
	switch d := d.(type) {
	case *ast.PropertyDecl:
		cls.Props = append(cls.Props, b.buildProp(d, ownerClass, isLibrary))
	case *ast.KindDecl:
		// Collected in pass 1 for the global kind tables.
		// Also register the kind's default as a class-level prop so every
		// instance of this class starts with the correct initial value.
		defaultVal := d.Values[d.DefaultIdx]
		cls.Props = append(cls.Props, &Prop{Key: d.Name, Value: KindValue{Name: defaultVal}})
	case *ast.KindUseDecl:
		cls.Props = append(cls.Props, b.buildKindUse(d))
	case *ast.VarDecl:
		cls.Props = append(cls.Props, b.buildVar(d))
	case *ast.HandlerDecl:
		if d.EveryTurn {
			cls.EveryTurn = append(cls.EveryTurn, &EveryTurnHandler{Body: d.Body, IsLibrary: isLibrary})
		} else {
			cls.Handlers = append(cls.Handlers, b.buildHandler(d, ownerClass, isLibrary))
		}
	case *ast.TurnHandlerDecl:
		cls.TurnRanges = append(cls.TurnRanges, b.buildTurnRange(d, isLibrary))
	case *ast.InterfaceHandlerDecl:
		cls.Interfaces = append(cls.Interfaces, b.buildInterface(d, ownerClass, isLibrary))
	case *ast.InstanceDecl:
		child := b.buildNode(d, isLibrary)
		cls.Children = append(cls.Children, child)
		b.registerNode(child)
	}
}

// =============================================================================
// Pass 3 — build top-level declarations into Root
// =============================================================================

// pass3TopLevel processes every top-level declaration in declaration order,
// attaching instances to Root and collecting global handlers and properties.
// ClassDecl and IncludeDecl/LibraryImport are silently skipped here — classes
// were handled in pass 2, and include/library resolution is the driver's job.
func (b *builder) pass3TopLevel(files []*ast.File, isLibrary bool) {
	for _, f := range files {
		for _, d := range f.Decls {
			b.addToRoot(d, isLibrary)
		}
	}
}

// buildTest converts a TestDecl AST node into a Test IR value.
// room is the name of the enclosing instance when the test is scoped
// (declared inside a room or object body), or "" for top-level tests.
func (b *builder) buildTest(d *ast.TestDecl, room string) *Test {
	t := &Test{Name: d.Name, Room: room}
	for _, stmt := range d.Body {
		cmd, ok := stmt.(*ast.TestCmdStmt)
		if !ok {
			continue
		}
		step := TestStep{
			Cmd:     strings.Join(cmd.Command, " "),
			SubTest: cmd.SubTest,
			Negate:  cmd.NotAssertion,
		}
		if cmd.Assertion != nil {
			step.Assert = *cmd.Assertion
		}
		t.Steps = append(t.Steps, step)
	}
	return t
}

func (b *builder) addToRoot(d ast.Decl, isLibrary bool) {
	root := b.w.Root
	switch d := d.(type) {
	case *ast.GameDecl:
		if !isLibrary {
			b.w.Game = GameInfo{Title: d.Title, Author: d.Author, Version: d.Version}
		}

	case *ast.KindDecl:
		// Top-level kind declaration also creates a world-level kind variable
		// initialised to its default value.
		if !isLibrary {
			defaultVal := d.Values[d.DefaultIdx]
			root.Props = append(root.Props, &Prop{
				Key:   d.Name,
				Value: KindValue{Name: defaultVal},
			})
		}

	case *ast.VarDecl:
		root.Props = append(root.Props, b.buildVar(d))

	case *ast.InstanceDecl:
		node := b.buildNode(d, isLibrary)
		root.Children = append(root.Children, node)
		b.registerNode(node)

	case *ast.HandlerDecl:
		if d.EveryTurn {
			root.EveryTurn = append(root.EveryTurn, &EveryTurnHandler{Body: d.Body, IsLibrary: isLibrary})
		} else {
			// ownerClass is empty at global scope — "self" is invalid there.
			root.Handlers = append(root.Handlers, b.buildHandler(d, "", isLibrary))
		}

	case *ast.TurnHandlerDecl:
		root.TurnRanges = append(root.TurnRanges, b.buildTurnRange(d, isLibrary))

	case *ast.InterfaceHandlerDecl:
		root.Interfaces = append(root.Interfaces, b.buildInterface(d, "", isLibrary))

	case *ast.TestDecl:
		if !isLibrary {
			b.w.Tests = append(b.w.Tests, b.buildTest(d, ""))
		}

	// ClassDecl handled in pass 2; IncludeDecl/LibraryImport handled by driver.
	}
}

// =============================================================================
// Node building
// =============================================================================

func (b *builder) buildNode(d *ast.InstanceDecl, isLibrary bool) *Node {
	node := &Node{
		Name:      d.Name,
		ClassName: d.ClassName,
		Desc:      d.Desc,
		Aliases:   d.Aliases,
		IsLibrary: isLibrary,
	}
	for _, bodyDecl := range d.Body {
		b.addToNode(node, bodyDecl, d.ClassName, isLibrary)
	}
	return node
}

// addToNode dispatches a single declaration from an instance body into the
// appropriate Node field.  ownerClass is the instance's declared class name;
// it is forwarded to buildHandler for "self" resolution in sigKey.
func (b *builder) addToNode(node *Node, d ast.Decl, ownerClass string, isLibrary bool) {
	switch d := d.(type) {
	case *ast.PropertyDecl:
		node.Props = append(node.Props, b.buildProp(d, ownerClass, isLibrary))
	case *ast.KindDecl:
		// Collected in pass 1. Also add the default as an instance-level prop.
		defaultVal := d.Values[d.DefaultIdx]
		node.Props = append(node.Props, &Prop{Key: d.Name, Value: KindValue{Name: defaultVal}})
	case *ast.KindUseDecl:
		node.Props = append(node.Props, b.buildKindUse(d))
	case *ast.VarDecl:
		node.Props = append(node.Props, b.buildVar(d))
	case *ast.HandlerDecl:
		if d.EveryTurn {
			node.EveryTurn = append(node.EveryTurn, &EveryTurnHandler{Body: d.Body, IsLibrary: isLibrary})
		} else {
			node.Handlers = append(node.Handlers, b.buildHandler(d, ownerClass, isLibrary))
		}
	case *ast.TurnHandlerDecl:
		node.TurnRanges = append(node.TurnRanges, b.buildTurnRange(d, isLibrary))
	case *ast.InterfaceHandlerDecl:
		node.Interfaces = append(node.Interfaces, b.buildInterface(d, ownerClass, isLibrary))
	case *ast.InstanceDecl:
		child := b.buildNode(d, isLibrary)
		child.Parent = node
		node.Children = append(node.Children, child)
		b.registerNode(child)

	case *ast.TestDecl:
		if !isLibrary {
			b.w.Tests = append(b.w.Tests, b.buildTest(d, node.Name))
		}
	}
}

// registerNode adds node and all its descendants to the NodeMap.
func (b *builder) registerNode(node *Node) {
	b.w.NodeMap[node.Name] = node
	for _, child := range node.Children {
		b.registerNode(child)
	}
}

// =============================================================================
// Property building
// =============================================================================

func (b *builder) buildProp(d *ast.PropertyDecl, ownerClass string, isLibrary bool) *Prop {
	if len(d.Body) > 0 {
		return b.buildInlineProp(d, isLibrary)
	}
	return &Prop{Key: d.Key, Value: b.buildExpr(d.Value)}
}

// buildInlineProp handles a PropertyDecl whose value is an inline instance
// declaration (e.g. an inline door: `east: Door brass door`).
// The instance is registered in the world and the property becomes a RefValue.
// If the same instance name was already registered (shared two-sided door),
// the existing node is reused and only the new side's properties are skipped
// (sema has already validated cross-references).
func (b *builder) buildInlineProp(d *ast.PropertyDecl, isLibrary bool) *Prop {
	nameExpr, ok := d.Value.(*ast.NameExpr)
	if !ok {
		return &Prop{Key: d.Key, Value: UnsetValue{}}
	}
	// Value contains "ClassName instanceName" e.g. "Door brass door".
	parts := strings.SplitN(nameExpr.Name, " ", 2)
	if len(parts) < 2 {
		return &Prop{Key: d.Key, Value: UnsetValue{}}
	}
	className, instanceName := parts[0], parts[1]

	if existing, exists := b.w.NodeMap[instanceName]; !exists {
		node := &Node{
			Name:      instanceName,
			ClassName: className,
			IsLibrary: isLibrary,
		}
		for _, bd := range d.Body {
			b.addToNode(node, bd, className, isLibrary)
		}
		// Inline doors and rooms are always top-level in the world tree.
		b.w.Root.Children = append(b.w.Root.Children, node)
		b.registerNode(node)
	} else {
		// Second side of a shared door — merge this side's properties into
		// the existing node so both sides contribute to the shared state.
		for _, bd := range d.Body {
			b.addToNode(existing, bd, className, isLibrary)
		}
	}

	return &Prop{Key: d.Key, Value: RefValue{Name: instanceName}}
}

func (b *builder) buildKindUse(d *ast.KindUseDecl) *Prop {
	val := d.Value
	if kindName, isValue := b.kindOf[val]; isValue {
		// val is a concrete kind value (e.g. "sad", "lit", "damp").
		// The property key is the kind name; the value is the kind value.
		// Negate doesn't invert named-list kind values — sema would have caught misuse.
		return &Prop{Key: kindName, Value: KindValue{Name: val}}
	}
	// val is a boolean kind name (e.g. "lockable"). "is lockable" → true, "is not lockable" → false.
	if d.Negate {
		return &Prop{Key: val, Value: KindValue{Name: "false"}}
	}
	return &Prop{Key: val, Value: KindValue{Name: "true"}}
}

// buildVar converts a VarDecl to a Prop.  A var without an initialiser
// defaults to 0 (not unset) because var is always numeric in Grue.
func (b *builder) buildVar(d *ast.VarDecl) *Prop {
	var val Value = NumberValue{V: 0}
	if d.Initial != nil {
		val = b.buildExpr(d.Initial)
	}
	return &Prop{Key: d.Name, Value: val}
}

// =============================================================================
// Handler building
// =============================================================================

// buildHandler converts a HandlerDecl to a Handler, computing the stable SigKey
// and the ResolvedSig (signature with "self" replaced by ownerClass).
// The raw AST body is kept as-is; the code generator compiles it to JavaScript.
func (b *builder) buildHandler(d *ast.HandlerDecl, ownerClass string, isLibrary bool) *Handler {
	return &Handler{
		Internal:    d.Internal,
		Signature:   d.Signature,
		ResolvedSig: resolveSignature(d.Signature, ownerClass),
		SigKey:      sigKey(d.Signature, ownerClass),
		Body:        d.Body,
		IsLibrary:   isLibrary,
	}
}

// resolveSignature returns a copy of sig with every SigParam whose Type is
// "self" replaced by ownerClass.  All other parts are left unchanged.
func resolveSignature(sig []ast.SigPart, ownerClass string) []ast.SigPart {
	resolved := make([]ast.SigPart, len(sig))
	for i, p := range sig {
		if param, ok := p.(ast.SigParam); ok && param.Type == "self" {
			resolved[i] = ast.SigParam{Type: ownerClass, Name: param.Name}
		} else {
			resolved[i] = p
		}
	}
	return resolved
}

func (b *builder) buildTurnRange(d *ast.TurnHandlerDecl, isLibrary bool) *TurnRangeHandler {
	return &TurnRangeHandler{
		From:      d.From,
		To:        d.To,
		Body:      d.Body,
		IsLibrary: isLibrary,
	}
}

func (b *builder) buildInterface(d *ast.InterfaceHandlerDecl, ownerClass string, isLibrary bool) *InterfaceHandler {
	iface := &InterfaceHandler{
		Signature: d.Signature,
		SigKey:    sigKey(d.Signature, ownerClass),
		IsLibrary: isLibrary,
	}
	for _, bd := range d.Body {
		if pd, ok := bd.(*ast.PropertyDecl); ok {
			iface.Props = append(iface.Props, &Prop{Key: pd.Key, Value: b.buildExpr(pd.Value)})
		}
	}
	return iface
}

// =============================================================================
// Expression building
// =============================================================================

// buildExpr converts an AST expression that appears as a property VALUE into a
// world Value.  This covers only static, declaration-time expressions — the
// runtime expressions inside handler bodies (arithmetic, conditions, handler
// calls) are not property values and are compiled directly by the code generator.
// An unrecognised expression type falls back to UnsetValue rather than panicking,
// because sema has already validated that property values are legal.
func (b *builder) buildExpr(e ast.Expr) Value {
	if e == nil {
		return UnsetValue{}
	}
	switch v := e.(type) {
	case *ast.NumberLit:
		return NumberValue{V: v.Value}
	case *ast.StringLit:
		return StringValue{V: v.Value}
	case *ast.UnsetExpr:
		return UnsetValue{}
	case *ast.NameExpr:
		// Could be a kind value, instance reference, or other name.
		// Represented as RefValue; the code generator resolves the referent.
		return RefValue{Name: v.Name}
	case *ast.ListLit:
		items := make([]Value, len(v.Items))
		for i, item := range v.Items {
			items[i] = b.buildExpr(item)
		}
		return ListValue{Items: items}
	case *ast.ArrayLit:
		items := make([]Value, len(v.Items))
		for i, item := range v.Items {
			items[i] = b.buildExpr(item)
		}
		return ArrayValue{Items: items}
	}
	return UnsetValue{}
}

// =============================================================================
// Vocabulary
// =============================================================================

// buildVocab populates Vocab by walking the instance tree rooted at Root.
// Class children (objects inside class bodies) are intentionally excluded:
// they are templates, not addressable world instances.
func (b *builder) buildVocab() {
	b.addNodeVocab(b.w.Root)
}

func (b *builder) addNodeVocab(node *Node) {
	if node.Name != "world" {
		b.w.Vocab[node.Name] = node.Name
		for _, alias := range node.Aliases {
			b.w.Vocab[alias] = node.Name
		}
	}
	for _, child := range node.Children {
		b.addNodeVocab(child)
	}
}

// =============================================================================
// sigKey — canonical handler dispatch key
// =============================================================================

// sigKey computes the canonical dispatch key for a handler signature.
// Keywords are kept as-is; parameter types are used (names are dropped).
// "self" is resolved to ownerClass, which is the class name when the handler
// is declared inside a class or instance body, or "" at global scope.
//
//	on open self at number:page:   in Ledger → "open Ledger number"
//	on open Ledger:l at number:p:  globally  → "open Ledger number"
//	on traverse passage in the dark:          → "traverse passage in the dark"
func sigKey(sig []ast.SigPart, ownerClass string) string {
	parts := make([]string, 0, len(sig))
	for _, p := range sig {
		switch p := p.(type) {
		case ast.SigKeyword:
			parts = append(parts, p.Word)
		case ast.SigParam:
			typ := p.Type
			if typ == "self" {
				typ = ownerClass
			}
			parts = append(parts, typ)
		}
	}
	return strings.Join(parts, " ")
}
