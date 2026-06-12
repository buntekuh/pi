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

// builtinClassHierarchy defines the built-in class tree. These stubs are
// injected before author-declared classes so that _instanceof can walk the
// full hierarchy at runtime, and the codegen can build correct inheritance
// chains for subclasses of built-in types.
// Emitted with isLibrary:true so the tree inspector hides them from the own-classes list.
var builtinClassHierarchy = []struct{ Name, Parent string }{
	{"Object", ""},
	{"Room", "Object"},
	{"Door", "Room"},
	{"Item", "Object"},
	{"Player", "Object"},
	{"Number", ""},
	{"Text", ""},
	{"Style", ""},
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
			ClassMap:      make(map[string]*Class),
			NodeMap:       make(map[string]*Node),
			Vocab:         make(map[string]string),
			StyleHTMLTags: make(map[string]string),
		},
		kindOf: make(map[string]string),
	}
	for val, kind := range builtinKindValues {
		b.kindOf[val] = kind
	}

	b.w.Root = &Node{Name: "world", ClassName: "World"}

	b.pass0Builtins()
	b.pass1Kinds(ownFiles)
	b.pass1Kinds(libFiles)
	b.pass2Classes(ownFiles, false)
	b.pass2Classes(libFiles, true)
	b.pass3TopLevel(ownFiles, false)
	b.pass3TopLevel(libFiles, true)
	b.pass4TopLevelDoorExits()
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
// Pass 0 — inject built-in class stubs
// =============================================================================

// pass0Builtins pre-populates ClassMap and Classes with stub entries for the
// built-in class hierarchy. The stubs carry no handlers or props — they exist
// solely so that _instanceof can walk the full parent chain at runtime, and
// so the codegen can resolve parent sigKeys across built-in class boundaries.
func (b *builder) pass0Builtins() {
	for _, bc := range builtinClassHierarchy {
		cls := &Class{Name: bc.Name, Parent: bc.Parent, IsLibrary: true}
		b.w.Classes = append(b.w.Classes, cls)
		b.w.ClassMap[bc.Name] = cls
	}
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
				if v != "true" && v != "false" && v != "unset" {
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
	parent := cd.Parent
	if parent == "" {
		parent = "Object" // implicit default parent for all user-declared classes
	}
	cls := &Class{
		Name:      cd.Name,
		Parent:    parent,
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
	case *ast.InterfaceHandlerDecl:
		cls.Interfaces = append(cls.Interfaces, b.buildInterface(d, ownerClass, isLibrary))
	case *ast.InstanceDecl:
		// "Object log" inside a class body declares a per-instance sub-object.
		// Store as SubObjectValue; codegen creates a named sub-node per instance.
		cls.Props = append(cls.Props, &Prop{
			Key:   d.Name,
			Value: SubObjectValue{ClassName: d.ClassName},
		})
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
			// Assignment or other statement — carry as a setup step so codegen
			// can emit it as a JS closure the test runner executes directly.
			t.Steps = append(t.Steps, TestStep{SetupStmt: stmt})
			continue
		}
		step := TestStep{
			Cmd:     strings.Join(cmd.Command, " "),
			Expr:    cmd.Expr,
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
		// Kind declaration only registers the kind values — it does not set any
		// world property. Use `is <value>` at the world level to initialise the
		// world's instance of this kind.

	case *ast.KindUseDecl:
		p := b.buildKindUse(d)
		for i, existing := range root.Props {
			if existing.Key == p.Key {
				root.Props[i] = p
				return
			}
		}
		root.Props = append(root.Props, p)

	case *ast.VarDecl:
		root.Props = append(root.Props, b.buildVar(d))

	case *ast.InstanceDecl:
		node := b.buildNode(d, isLibrary)
		root.Children = append(root.Children, node)
		b.registerNode(node)
		if b.isStyleClass(d.ClassName) {
			b.extractStyleTag(d)
		}

	case *ast.HandlerDecl:
		if d.EveryTurn {
			root.EveryTurn = append(root.EveryTurn, &EveryTurnHandler{Body: d.Body, IsLibrary: isLibrary})
		} else {
			// ownerClass is empty at global scope — "self" is invalid there.
			root.Handlers = append(root.Handlers, b.buildHandler(d, "", isLibrary))
		}

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
// Style helpers
// =============================================================================

// isStyleClass reports whether className is "Style" or a subclass of it.
func (b *builder) isStyleClass(className string) bool {
	for cls := className; cls != ""; {
		if cls == "Style" {
			return true
		}
		c, ok := b.w.ClassMap[cls]
		if !ok {
			return false
		}
		cls = c.Parent
	}
	return false
}

// extractStyleTag reads a "tag:" body property from a Style instance declaration
// and stores the HTML element name in StyleHTMLTags.
func (b *builder) extractStyleTag(d *ast.InstanceDecl) {
	for _, bodyDecl := range d.Body {
		prop, ok := bodyDecl.(*ast.PropertyDecl)
		if !ok || prop.Key != "tag" {
			continue
		}
		if lit, ok := prop.Value.(*ast.StringLit); ok && lit.Value != "" {
			b.w.StyleHTMLTags[d.Name] = lit.Value
		}
		return
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
	case *ast.UnaryExpr:
		if v.Op == "-" {
			if n, ok := v.Expr.(*ast.NumberLit); ok {
				return NumberValue{V: -n.Value}
			}
		}
		return UnsetValue{}
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
// Pass 4 — wire top-level door exits into connected rooms
// =============================================================================

// compassOpposite maps each compass direction to its reverse.
var compassOpposite = map[string]string{
	"north": "south", "south": "north",
	"east": "west", "west": "east",
	"up": "down", "down": "up",
	"in": "out", "out": "in",
	"northeast": "southwest", "southwest": "northeast",
	"northwest": "southeast", "southeast": "northwest",
}

// pass4TopLevelDoorExits processes top-level Door nodes that declare their
// connections via compass-direction props (e.g. east: landing, west: bedroom).
//
// For each fully-bidirectional door (exactly two compass direction props), it:
//   - Adds a reverse exit to each connected room pointing at the door, so the
//     room's exits table includes the door and players can traverse it.
//   - Adds "leads to" props to the door node so the runtime's connects[] array
//     is populated correctly for through-traversal.
//
// One-sided top-level doors (single compass prop) are skipped — they are
// scenic or decorative and do not create automatic room connections.
func (b *builder) pass4TopLevelDoorExits() {
	for _, node := range b.w.Root.Children {
		if node.ClassName != "Door" {
			continue
		}
		// Collect only compass-direction props.
		type dirEntry struct{ dir, dest string }
		var dirs []dirEntry
		for _, prop := range node.Props {
			if _, ok := compassOpposite[prop.Key]; !ok {
				continue
			}
			ref, ok := prop.Value.(RefValue)
			if !ok {
				continue
			}
			dirs = append(dirs, dirEntry{prop.Key, ref.Name})
		}
		// Only wire bidirectional doors.
		if len(dirs) != 2 {
			continue
		}
		for _, d := range dirs {
			target := b.w.NodeMap[d.dest]
			if target == nil {
				continue
			}
			rev := compassOpposite[d.dir]
			// Add reverse exit to the room unless it already has one.
			already := false
			for _, ep := range target.Props {
				if ep.Key == rev {
					already = true
					break
				}
			}
			if !already {
				target.Props = append(target.Props, &Prop{
					Key:   rev,
					Value: RefValue{Name: node.Name},
				})
			}
			// Add "leads to" prop to the door so connects[] is populated.
			node.Props = append(node.Props, &Prop{
				Key:   "leads to",
				Value: RefValue{Name: d.dest},
			})
		}
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
