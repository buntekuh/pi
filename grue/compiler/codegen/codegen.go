// Package codegen emits JavaScript from the compiled world tree and grammar.
//
// The output is a GrueRuntime.init({...}) call that hands the compiled game
// descriptor to the runtime. The descriptor shape grows with each milestone:
//
//	M1: meta, nodes, start
//	M2: + handlers, grammar, vocab
//	M3: + containment
//	...
//
// HTML assembles a complete self-contained page by inlining the runtime
// (embedded from runtime.js) and the game script.
package codegen

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"html"
	"sort"
	"strconv"
	"strings"

	"gruc/ast"
	"gruc/grammar"
	"gruc/parser"
	"gruc/world"
)

//go:embed runtime.js
var RuntimeJS string

// cg is the code generation context shared across all handler-compilation
// functions. It is built once per Emit call and threaded through as a receiver.
type cg struct {
	w   *world.World
	kof map[string]string // kind value name → kind name (excludes true/false)
	nod map[string]bool   // all known instance names
}

func newCG(w *world.World) *cg {
	c := &cg{
		w:   w,
		kof: make(map[string]string),
		nod: make(map[string]bool, len(w.NodeMap)),
	}
	for _, k := range w.Kinds {
		for _, v := range k.Values {
			if v != "true" && v != "false" {
				c.kof[v] = k.Name
			}
		}
	}
	for name := range w.NodeMap {
		c.nod[name] = true
	}
	return c
}

// scope tracks which names are local JS variables in the current handler frame
// (handler parameters, loop variables, local var declarations) and which names
// are class-level properties accessible on self without qualification.
type scope struct {
	vars     map[string]bool   // local JS variables — compiled as bare identifiers
	varTypes map[string]string // parameter type name for each variable (e.g. "Object", "Room", "number")
	clsProps map[string]bool   // class property names — compiled as _prop(self, key)
	selfName string            // name of the self parameter, or "" if none
}

func newScope(h *world.Handler, ownerClass string, w *world.World) *scope {
	sc := &scope{
		vars:     make(map[string]bool),
		varTypes: make(map[string]string),
		clsProps: make(map[string]bool),
	}
	for _, part := range h.ResolvedSig {
		if p, ok := part.(ast.SigParam); ok {
			sc.vars[p.Name] = true
			typ := p.Type
			if typ == "self" {
				typ = ownerClass
			}
			sc.varTypes[p.Name] = typ
			if p.Type == ownerClass || p.Name == "self" {
				sc.selfName = p.Name
			}
		}
	}
	// Collect all property names reachable on self through the class hierarchy.
	if ownerClass != "" {
		cls := ownerClass
		for cls != "" {
			if cd, ok := w.ClassMap[cls]; ok {
				for _, prop := range cd.Props {
					sc.clsProps[prop.Key] = true
				}
				cls = cd.Parent
			} else {
				break
			}
		}
	}
	return sc
}

func (sc *scope) extend(name string) *scope {
	return sc.extendTyped(name, "")
}

func (sc *scope) extendTyped(name, typ string) *scope {
	next := &scope{
		vars:     make(map[string]bool, len(sc.vars)+1),
		varTypes: make(map[string]string, len(sc.varTypes)+1),
		clsProps: sc.clsProps,
		selfName: sc.selfName,
	}
	for k := range sc.vars {
		next.vars[k] = true
	}
	for k, v := range sc.varTypes {
		next.varTypes[k] = v
	}
	next.vars[name] = true
	next.varTypes[name] = typ
	return next
}

// rt is the runtime prefix prepended to every IIFE-private helper call in
// compiled handler bodies and exprFn closures.  Handler functions are defined
// in the game script's outer scope and cannot see the IIFE's local bindings,
// so every call to say/prop/get/random/… is routed through the R parameter
// of the wrapping function(R){...} that receives GrueRuntime as its argument.
const rt = "R."

// Emit generates the game-script JS for the given world and grammar.
// The output wraps the GrueRuntime.init({...}) descriptor in a function that
// receives the runtime as R, giving handler and exprFn closures access to all
// runtime helpers without requiring them to be global.
func Emit(w *world.World, g *grammar.Grammar) string {
	c := newCG(w)
	var b strings.Builder
	b.WriteString("GrueRuntime.init((function(R) { return {\n")
	writeMeta(&b, w.Game)
	writeKinds(&b, w)
	writeClasses(&b, w)
	writeNodes(&b, w)
	writeStart(&b, w)
	c.writeHandlers(&b)
	writeGrammar(&b, g)
	writeVocab(&b, w)
	c.writeTests(&b)
	b.WriteString("}; })(GrueRuntime));\n")
	return b.String()
}

// HTML returns a complete self-contained HTML page with the runtime and
// game script inlined. No external resources are referenced.
func HTML(w *world.World, g *grammar.Grammar) string {
	title := w.Game.Title
	if title == "" {
		title = "Grue"
	}
	return fmt.Sprintf(`<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>%s</title>
  <!-- TEST CSS — move to wrapper once host container exists; see wrapper.md -->
  <style>
    body       { max-width: 680px; margin: 40px auto; font: 1.05em/1.7 Georgia, serif; color: #222; background: #f7f6f2; }
    p.text     { background: #eeede6; padding: 6px 10px; border-radius: 3px; margin: 4px 0; }
    p.headline { font-size: 1.25em; font-weight: bold; margin: 1.2em 0 0.2em; color: #333; letter-spacing: 0.02em; }
    #input-area { margin-top: 12px; }
    #cmd        { width: 420px; font-size: 1em; }
  </style>
</head>
<body>
<div id="output"></div>
<div id="tree" style="display:none"></div>
<div id="input-area">
  <input id="cmd" type="text" autofocus>
  <button id="go">Go</button>
  <button id="tree-btn">Tree</button>
  <button id="tests-btn">Tests</button>
</div>
<script>
%s</script>
<script>
%s</script>
</body>
</html>
`, html.EscapeString(title), RuntimeJS, Emit(w, g))
}

// ── meta ───────────────────────────────────────────────────────────────────

func writeMeta(b *strings.Builder, game world.GameInfo) {
	b.WriteString("  meta: {\n")
	fmt.Fprintf(b, "    title:   %s,\n", jsStr(game.Title))
	fmt.Fprintf(b, "    author:  %s,\n", jsStr(game.Author))
	fmt.Fprintf(b, "    version: %s\n", jsStr(game.Version))
	b.WriteString("  },\n")
}

// ── kinds ──────────────────────────────────────────────────────────────────

func writeKinds(b *strings.Builder, w *world.World) {
	if len(w.Kinds) == 0 {
		b.WriteString("  kinds: [],\n")
		return
	}
	b.WriteString("  kinds: [\n")
	for _, k := range w.Kinds {
		vals := make([]string, len(k.Values))
		for i, v := range k.Values {
			vals[i] = jsStr(v)
		}
		fmt.Fprintf(b, "    { name: %s, values: [%s], defaultIdx: %d },\n",
			jsStr(k.Name), strings.Join(vals, ", "), k.DefaultIdx)
	}
	b.WriteString("  ],\n")
}

// ── classes ────────────────────────────────────────────────────────────────

func writeClasses(b *strings.Builder, w *world.World) {
	if len(w.Classes) == 0 {
		b.WriteString("  classes: {},\n")
		return
	}
	b.WriteString("  classes: {\n")
	for _, cls := range w.Classes {
		fmt.Fprintf(b, "    %s: {\n", jsStr(cls.Name))
		fmt.Fprintf(b, "      parent: %s,\n", jsStr(cls.Parent))
		fmt.Fprintf(b, "      isLibrary: %v,\n", cls.IsLibrary)
		b.WriteString("      props: ")
		writePropsObject(b, cls.Props)
		b.WriteString(",\n")
		// handler sigkeys
		var sigs []string
		for _, h := range cls.Handlers {
			sigs = append(sigs, jsStr(h.SigKey))
		}
		if len(cls.EveryTurn) > 0 {
			sigs = append(sigs, jsStr("(every turn)"))
		}
		fmt.Fprintf(b, "      handlers: [%s]\n", strings.Join(sigs, ", "))
		b.WriteString("    },\n")
	}
	b.WriteString("  },\n")
}

// ── nodes ──────────────────────────────────────────────────────────────────

func writeNodes(b *strings.Builder, w *world.World) {
	nodes := worldNodes(w)
	// Emit a synthetic "world" node when the root has declared properties
	// (var declarations at global scope). _get() already falls back to this node.
	hasRootProps := len(w.Root.Props) > 0
	if len(nodes) == 0 && !hasRootProps {
		b.WriteString("  nodes: {},\n")
		return
	}
	b.WriteString("  nodes: {\n")
	if hasRootProps {
		b.WriteString(`    "world": { class: "World", props: `)
		writePropsObject(b, w.Root.Props)
		b.WriteString(" },\n")
	}
	for _, node := range nodes {
		fmt.Fprintf(b, "    %s: { class: %s", jsStr(node.Name), jsStr(node.ClassName))
		if node.Desc != "" {
			fmt.Fprintf(b, ", desc: %s", jsStr(node.Desc))
		}
		if loc := locationOf(node); loc != "" {
			fmt.Fprintf(b, ", location: %s", jsStr(loc))
		}
		if len(node.Aliases) > 0 {
			parts := make([]string, len(node.Aliases))
			for i, a := range node.Aliases {
				parts[i] = jsStr(a)
			}
			fmt.Fprintf(b, ", aliases: [%s]", strings.Join(parts, ", "))
		}
		writeExits(b, node)
		writeConnects(b, node)
		// Collect SubObjectValue props from the class hierarchy and add refs
		// to per-instance sub-nodes (e.g. "rolodex.log").
		subObjs := collectSubObjectProps(node.ClassName, w)
		effectiveProps := node.Props
		if len(subObjs) > 0 {
			effectiveProps = make([]*world.Prop, len(node.Props), len(node.Props)+len(subObjs))
			copy(effectiveProps, node.Props)
			for _, sop := range subObjs {
				effectiveProps = append(effectiveProps, &world.Prop{
					Key:   sop.key,
					Value: world.RefValue{Name: node.Name + "." + sop.key},
				})
			}
		}
		b.WriteString(", props: ")
		writePropsObject(b, effectiveProps)
		b.WriteString(" },\n")
		// Emit the per-instance sub-nodes.
		for _, sop := range subObjs {
			fmt.Fprintf(b, "    %s: { class: %s, props: {} },\n",
				jsStr(node.Name+"."+sop.key), jsStr(sop.className))
		}
	}
	b.WriteString("  },\n")
}

type subObjProp struct{ key, className string }

// collectSubObjectProps walks the class hierarchy of className and returns all
// SubObjectValue properties reachable from it.
func collectSubObjectProps(className string, w *world.World) []subObjProp {
	var result []subObjProp
	seen := make(map[string]bool)
	for cls := className; cls != ""; {
		cd, ok := w.ClassMap[cls]
		if !ok {
			break
		}
		for _, prop := range cd.Props {
			if sov, ok := prop.Value.(world.SubObjectValue); ok && !seen[prop.Key] {
				seen[prop.Key] = true
				result = append(result, subObjProp{key: prop.Key, className: sov.ClassName})
			}
		}
		cls = cd.Parent
	}
	return result
}

// writePropsObject emits a JS object literal for a slice of Props.
// If the same key appears more than once (e.g. "leads to" on both sides of a
// door), the values are collected into an array.
func writePropsObject(b *strings.Builder, props []*world.Prop) {
	// Group values by key, preserving first-occurrence order.
	keys := []string{}
	groups := map[string][]string{}
	for _, p := range props {
		v := propValJS(p.Value)
		if v == "" {
			continue
		}
		if _, seen := groups[p.Key]; !seen {
			keys = append(keys, p.Key)
		}
		groups[p.Key] = append(groups[p.Key], v)
	}
	if len(keys) == 0 {
		b.WriteString("{}")
		return
	}
	b.WriteString("{")
	for i, k := range keys {
		vals := groups[k]
		if i > 0 {
			b.WriteString(", ")
		}
		if len(vals) == 1 {
			fmt.Fprintf(b, "%s: %s", jsStr(k), vals[0])
		} else {
			fmt.Fprintf(b, "%s: [%s]", jsStr(k), strings.Join(vals, ", "))
		}
	}
	b.WriteString("}")
}

// propValJS converts a world.Value to its JS literal representation.
// Complex values (Array, List) are omitted for now — emitted in M5.
func propValJS(v world.Value) string {
	switch val := v.(type) {
	case world.NumberValue:
		return strconv.Itoa(val.V)
	case world.StringValue:
		return jsStr(val.V)
	case world.RefValue:
		return jsStr(val.Name)
	case world.KindValue:
		return jsStr(val.Name)
	case world.UnsetValue:
		return "null"
	}
	return ""
}

// ── start ──────────────────────────────────────────────────────────────────

func writeStart(b *strings.Builder, w *world.World) {
	fmt.Fprintf(b, "  start: %s,\n", jsStr(findStart(w)))
}

// ── handlers ───────────────────────────────────────────────────────────────

// handlerEntry pairs an owner label with a compiled handler.
// For normal handlers, handler is non-nil. For every-turn handlers compiled
// into the "every turn" chain, everyTurnBody is non-nil and handler is nil.
type handlerEntry struct {
	owner         string
	handler       *world.Handler
	ownerClass    string     // class name when owner is a class, else ""
	everyTurnBody []ast.Stmt // non-nil for EveryTurn entries; handler is nil
}

// writeHandlers emits the handlers map: sigKey → ordered list of {owner, fn}.
// Chain order: instance → class → global own → global library.
// Every-turn handlers are compiled into the "every turn" chain with
// compileEveryTurnFn rather than compileHandler.
func (c *cg) writeHandlers(b *strings.Builder) {
	chains := c.buildHandlerChains()
	if len(chains) == 0 {
		b.WriteString("  handlers: {},\n")
		return
	}
	sigKeys := sortedKeys(chains)
	b.WriteString("  handlers: {\n")
	for _, sigKey := range sigKeys {
		entries := chains[sigKey]
		fmt.Fprintf(b, "    %s: [\n", jsStr(sigKey))
		for _, e := range entries {
			owner := "null"
			if e.owner != "" {
				owner = jsStr(e.owner)
			}
			var fn string
			if e.everyTurnBody != nil {
				fn = c.compileEveryTurnFn(e.everyTurnBody, e.owner, e.ownerClass)
			} else {
				fn = c.compileHandler(e.handler, e.ownerClass)
			}
			fmt.Fprintf(b, "      { owner: %s, fn: %s },\n", owner, fn)
		}
		b.WriteString("    ],\n")
	}
	b.WriteString("  },\n")
}

func (c *cg) buildHandlerChains() map[string][]handlerEntry {
	chains := make(map[string][]handlerEntry)
	add := func(sigKey, owner, ownerClass string, h *world.Handler) {
		chains[sigKey] = append(chains[sigKey], handlerEntry{
			owner: owner, handler: h, ownerClass: ownerClass,
		})
	}
	addET := func(owner, ownerClass string, eth *world.EveryTurnHandler) {
		chains["every turn"] = append(chains["every turn"], handlerEntry{
			owner: owner, ownerClass: ownerClass, everyTurnBody: eth.Body,
		})
	}
	// Internal handlers ARE included in the handlers map so _call() can find
	// them from within other handler bodies. The grammar builder separately
	// excludes them from the player-input trie.
	for _, node := range worldNodes(c.w) {
		for _, h := range node.Handlers {
			add(h.SigKey, node.Name, node.ClassName, h)
		}
		for _, eth := range node.EveryTurn {
			addET(node.Name, node.ClassName, eth)
		}
	}
	for _, cls := range c.w.Classes {
		for _, h := range cls.Handlers {
			add(h.SigKey, cls.Name, cls.Name, h)
		}
		for _, eth := range cls.EveryTurn {
			addET(cls.Name, cls.Name, eth)
		}
	}
	for _, h := range c.w.Root.Handlers {
		if !h.IsLibrary {
			add(h.SigKey, "", "", h)
		}
	}
	for _, eth := range c.w.Root.EveryTurn {
		if !eth.IsLibrary {
			addET("", "", eth)
		}
	}
	for _, h := range c.w.Root.Handlers {
		if h.IsLibrary {
			add(h.SigKey, "", "", h)
		}
	}
	for _, eth := range c.w.Root.EveryTurn {
		if eth.IsLibrary {
			addET("", "", eth)
		}
	}

	// Inheritance: for each class handler, walk the parent hierarchy and append
	// ancestor handlers to the subclass sigKey chain. This lets _parent() work
	// across class boundaries without needing a separate runtime lookup.
	//
	// Parent sigKey is computed by replacing the child class name with the
	// ancestor class name (word-by-word, so only whole-word occurrences match).
	for _, cls := range c.w.Classes {
		if len(cls.Handlers) == 0 {
			continue
		}
		for _, h := range cls.Handlers {
			c.appendAncestorHandlers(chains, h.SigKey, cls.Name, cls.Parent, add)
		}
	}

	// Same inheritance for global (root) handlers: a handler like "greet Item"
	// needs the "greet Object" handler appended so that `parent` can cross the
	// class boundary.
	for _, h := range c.w.Root.Handlers {
		for _, part := range h.ResolvedSig {
			if p, ok := part.(ast.SigParam); ok {
				if cls, ok := c.w.ClassMap[p.Type]; ok && cls.Parent != "" {
					c.appendAncestorHandlers(chains, h.SigKey, p.Type, cls.Parent, add)
				}
			}
		}
	}

	return chains
}

// compileEveryTurnFn compiles an every-turn handler body into a JS function.
// Both class-scoped and node-scoped handlers receive `self` — the runtime
// passes the current instance name in both cases. clsProps is populated from
// the class hierarchy so bare property names resolve via _prop(self, key).
// Instance props are also added for node-scoped handlers.
func (c *cg) compileEveryTurnFn(body []ast.Stmt, ownerName, ownerClass string) string {
	sc := &scope{
		vars:     make(map[string]bool),
		varTypes: make(map[string]string),
		clsProps: make(map[string]bool),
	}
	paramStr := ""
	if ownerName != "" || ownerClass != "" {
		sc.selfName = "self"
		sc.vars["self"] = true
		sc.varTypes["self"] = ownerClass
		// Collect class hierarchy props.
		cls := ownerClass
		for cls != "" {
			if cd, ok := c.w.ClassMap[cls]; ok {
				for _, prop := range cd.Props {
					sc.clsProps[prop.Key] = true
				}
				cls = cd.Parent
			} else {
				break
			}
		}
		// Also include instance props (e.g. fuse: 5 on a specific node).
		if node, ok := c.w.NodeMap[ownerName]; ok {
			for _, prop := range node.Props {
				sc.clsProps[prop.Key] = true
			}
		}
		paramStr = "self"
	}
	compiled := c.compileStmts(body, sc, "        ")
	if compiled == "" {
		return fmt.Sprintf("function(%s) {}", paramStr)
	}
	return fmt.Sprintf("function(%s) {\n%s      }", paramStr, compiled)
}

// appendAncestorHandlers walks up the class hierarchy from parentName and
// appends ancestor handlers for the given subclass sigKey to chains.
// childClass is the class whose sigKey is being extended; as we walk up,
// we replace childClass with each successive ancestor name to derive the
// ancestor's version of the sigKey.
func (c *cg) appendAncestorHandlers(chains map[string][]handlerEntry, sigKey, childClass, parentName string, add func(string, string, string, *world.Handler)) {
	// curSigKey is the rolling ancestor translation of sigKey.
	// Each level substitutes the current class name with the parent class name
	// in the running sigKey, so a 3-level chain like:
	//   examine Rolodex → examine Ledger → examine Object
	// is derived one step at a time rather than always substituting into the
	// original sigKey (which would fail to find "Ledger" in "examine Rolodex").
	curSigKey := sigKey
	for parentName != "" {
		pSigKey := replaceClassInSigKey(curSigKey, childClass, parentName)
		if pSigKey == curSigKey {
			break // class name not present in sigKey, nothing to substitute
		}
		// Add parent class handlers that match this ancestor sigKey.
		if parentCls, ok := c.w.ClassMap[parentName]; ok {
			for _, ph := range parentCls.Handlers {
				if ph.SigKey == pSigKey {
					add(sigKey, parentName, parentName, ph)
				}
			}
		}
		// Add global (root) handlers that match the ancestor sigKey — these are
		// the library fallbacks (e.g., "examine Object" fires for any class's
		// examine chain).
		for _, gh := range c.w.Root.Handlers {
			if gh.SigKey == pSigKey {
				add(sigKey, "", "", gh)
			}
		}
		// Advance: the next level will substitute parentName with grandParentName
		// in the current ancestor sigKey.
		grandParentName := ""
		if parentCls, ok := c.w.ClassMap[parentName]; ok {
			grandParentName = parentCls.Parent
		}
		curSigKey = pSigKey
		childClass = parentName
		parentName = grandParentName
	}
}

// replaceClassInSigKey returns sigKey with every whole-word occurrence of
// oldClass replaced by newClass. SigKeys are space-separated, so a word
// boundary check is not needed beyond splitting on spaces.
func replaceClassInSigKey(sigKey, oldClass, newClass string) string {
	words := strings.Split(sigKey, " ")
	for i, w := range words {
		if w == oldClass {
			words[i] = newClass
		}
	}
	return strings.Join(words, " ")
}

// ── handler compilation ────────────────────────────────────────────────────

// hasNodeVars reports whether any node-var declaration (var Class name) appears
// anywhere in stmts, including nested blocks. Used to decide whether to emit
// the _nf cleanup infrastructure in compileHandler.
func hasNodeVars(stmts []ast.Stmt) bool {
	for _, s := range stmts {
		if hasNodeVarsStmt(s) {
			return true
		}
	}
	return false
}

func hasNodeVarsStmt(s ast.Stmt) bool {
	switch s := s.(type) {
	case *ast.VarStmt:
		return s.IsNodeVar
	case *ast.IfStmt:
		if hasNodeVars(s.Body) || hasNodeVars(s.Else) {
			return true
		}
		for _, elif := range s.ElseIf {
			if hasNodeVarsStmt(elif) {
				return true
			}
		}
	case *ast.ForInStmt:
		return hasNodeVars(s.Body)
	case *ast.ForFromStmt:
		return hasNodeVars(s.Body)
	case *ast.RepeatStmt:
		return hasNodeVars(s.Body)
	case *ast.WhenStmt:
		for _, arm := range s.Arms {
			if hasNodeVars(arm.Body) {
				return true
			}
		}
	case *ast.ChooseStmt:
		for _, arm := range s.Arms {
			if hasNodeVars(arm.Body) {
				return true
			}
		}
	}
	return false
}

func (c *cg) compileHandler(h *world.Handler, ownerClass string) string {
	var params []string
	for _, part := range h.ResolvedSig {
		if p, ok := part.(ast.SigParam); ok {
			params = append(params, p.Name)
		}
	}
	sc := newScope(h, ownerClass, c.w)
	body := c.compileStmts(h.Body, sc, "        ")

	if body == "" {
		return fmt.Sprintf("function(%s) {}", strings.Join(params, ", "))
	}
	// No node vars: emit a plain function, no cleanup overhead.
	if !hasNodeVars(h.Body) {
		return fmt.Sprintf("function(%s) {\n%s      }", strings.Join(params, ", "), body)
	}
	// Node vars present: _nf collects every allocated node name; _freeNode
	// checks references before deleting so stored nodes survive cleanup.
	return fmt.Sprintf(
		"function(%s) {\n        const _nf = [];\n        try {\n%s        } finally {\n            for (const _n of _nf) %s_freeNode(_n);\n        }\n      }",
		strings.Join(params, ", "), body, rt)
}

func (c *cg) compileStmts(stmts []ast.Stmt, sc *scope, indent string) string {
	var b strings.Builder
	for _, stmt := range stmts {
		// VarStmt extends the scope for all subsequent statements in the same
		// block, so that {d} in a following say compiles to the local var, not
		// to R._get("d").
		if vs, ok := stmt.(*ast.VarStmt); ok {
			sc = sc.extendTyped(vs.Name, vs.TypeName)
		}
		b.WriteString(c.compileStmt(stmt, sc, indent))
	}
	return b.String()
}

func (c *cg) compileStmt(stmt ast.Stmt, sc *scope, indent string) string {
	if stmt == nil {
		return ""
	}
	switch s := stmt.(type) {

	case *ast.SayStmt:
		lit, ok := s.Text.(*ast.StringLit)
		if !ok {
			return ""
		}
		text := c.compileSayString(lit.Value, sc)
		var line string
		if s.Style != "" {
			line = fmt.Sprintf("%s%ssay(%s, %s);", indent, rt, text, jsStr(s.Style))
		} else {
			line = fmt.Sprintf("%s%ssay(%s);", indent, rt, text)
		}
		return c.withGuard(line, s.Guard, sc, indent) + "\n"

	case *ast.DirectionsStmt:
		lit, ok := s.Text.(*ast.StringLit)
		if !ok {
			return ""
		}
		text := c.compileString(lit.Value, sc)
		line := fmt.Sprintf("%s%sdirections(%s);", indent, rt, text)
		return c.withGuard(line, s.Guard, sc, indent) + "\n"

	case *ast.FailStmt:
		var line string
		if s.Token == nil {
			line = fmt.Sprintf("%s%s_fail();", indent, rt)
		} else {
			line = fmt.Sprintf("%s%s_fail(%s);", indent, rt, c.compileSignalToken(s.Token, sc))
		}
		return c.withGuard(line, s.Guard, sc, indent) + "\n"

	case *ast.SucceedStmt:
		var line string
		if s.Token == nil {
			line = fmt.Sprintf("%s%s_succeed();", indent, rt)
		} else {
			line = fmt.Sprintf("%s%s_succeed(%s);", indent, rt, c.compileSignalToken(s.Token, sc))
		}
		return c.withGuard(line, s.Guard, sc, indent) + "\n"

	case *ast.ParentStmt:
		if s.Silently {
			return fmt.Sprintf("%s%s_parentS();\n", indent, rt)
		}
		return fmt.Sprintf("%s%s_parent();\n", indent, rt)

	case *ast.StopStmt:
		return fmt.Sprintf("%s%s_stop();\n", indent, rt)

	case *ast.KindUseDecl:
		// `is release` / `is lit` as a runtime statement — same semantics as
		// the declaration form but executed at handler call time.
		var key, val string
		if kindName, isValue := c.kof[s.Value]; isValue {
			key, val = kindName, s.Value
		} else {
			// boolean kind: `is lit` → lit=true, `is not lit` → lit=false
			key = s.Value
			if s.Negate {
				val = "false"
			} else {
				val = "true"
			}
		}
		if sc.clsProps[key] && sc.selfName != "" {
			return fmt.Sprintf("%s%s_setProp(%s, %s, %s);\n", indent, rt, sc.selfName, jsStr(key), jsStr(val))
		}
		return fmt.Sprintf("%s%s_set(%s, %s);\n", indent, rt, jsStr(key), jsStr(val))

	case *ast.AssignStmt:
		rhs := c.compileExpr(s.Value, sc)
		line := c.compileAssign(s.Target, s.Operator, rhs, sc, indent)
		return c.withGuard(line, s.Guard, sc, indent) + "\n"

	case *ast.MutateStmt:
		rhs := c.compileExpr(s.Value, sc)
		op := "+="
		if s.Operator == "-" {
			op = "-="
		}
		line := c.compileAssign(s.Target, op, rhs, sc, indent)
		return c.withGuard(line, s.Guard, sc, indent) + "\n"

	case *ast.VarStmt:
		if s.IsNodeVar {
			// Allocate inline, register for GC-style cleanup. _freeNode skips
			// nodes still referenced by a persistent property.
			return fmt.Sprintf("%slet %s = %s_newNode(%q); _nf.push(%s);\n",
				indent, s.Name, rt, s.TypeName, s.Name)
		}
		if s.Initial != nil {
			init := c.compileExpr(s.Initial, sc)
			return fmt.Sprintf("%slet %s = %s;\n", indent, s.Name, init)
		}
		return fmt.Sprintf("%slet %s = 0;\n", indent, s.Name)

	case *ast.IfStmt:
		return c.compileIf(s, sc, indent)

	case *ast.ForFromStmt:
		inner := sc.extendTyped(s.Var, "number")
		from := c.compileExpr(s.From, sc)
		to := c.compileExpr(s.To, sc)
		body := c.compileStmts(s.Body, inner, indent+"    ")
		return fmt.Sprintf("%sfor (let %s = %s; %s < %s; %s++) {\n%s%s}\n",
			indent, s.Var, from, s.Var, to, s.Var, body, indent)

	case *ast.RepeatStmt:
		from := c.compileExpr(s.From, sc)
		to := c.compileExpr(s.To, sc)
		body := c.compileStmts(s.Body, sc, indent+"    ")
		return fmt.Sprintf("%sfor (let _i = %s; _i < %s; _i++) {\n%s%s}\n",
			indent, from, to, body, indent)

	case *ast.ForInStmt:
		return c.compileForIn(s, sc, indent)

	case *ast.WhenStmt:
		return c.compileWhen(s, sc, indent)

	case *ast.ChooseStmt:
		return c.compileChoose(s, sc, indent)

	case *ast.CallStmt:
		expr := c.compileExpr(s.Call, sc)
		line := fmt.Sprintf("%s%s;", indent, expr)
		return c.withGuard(line, s.Guard, sc, indent) + "\n"

	case *ast.BareCallStmt:
		if nameExpr, ok := s.Expr.(*ast.NameExpr); ok {
			if words := strings.Fields(nameExpr.Name); len(words) == 1 {
				return fmt.Sprintf("%s%s_call(%s);\n", indent, rt, jsStr(nameExpr.Name))
			}
		}
		expr := c.compileExpr(s.Expr, sc)
		return fmt.Sprintf("%s%s;\n", indent, expr)

	case *ast.BareCallWithBodyStmt:
		expr := c.compileExpr(s.Expr, sc)
		return fmt.Sprintf("%s%s;\n", indent, expr)
	}
	return ""
}

// compileBoolCond wraps an expression for use as a boolean condition.
// Comparisons and explicit boolean ops already produce JS booleans; everything
// else (names, property reads, handler calls) goes through _truthy() so that
// only null/unset and the string "false" are falsy — 0 is truthy in Grue.
func (c *cg) compileBoolCond(e ast.Expr, sc *scope) string {
	switch t := e.(type) {
	case *ast.BinaryExpr, *ast.IsSetExpr:
		return c.compileExpr(e, sc)
	case *ast.UnaryExpr:
		if t.Op == "not" {
			return c.compileExpr(e, sc)
		}
	}
	return fmt.Sprintf("%s_truthy(%s)", rt, c.compileExpr(e, sc))
}

func (c *cg) compileIf(s *ast.IfStmt, sc *scope, indent string) string {
	cond := c.compileBoolCond(s.Cond, sc)
	if s.Unless {
		cond = "!(" + cond + ")"
	}
	body := c.compileStmts(s.Body, sc, indent+"    ")
	var b strings.Builder
	fmt.Fprintf(&b, "%sif (%s) {\n%s%s}", indent, cond, body, indent)
	for _, elif := range s.ElseIf {
		elifCond := c.compileBoolCond(elif.Cond, sc)
		if elif.Unless {
			elifCond = "!(" + elifCond + ")"
		}
		elifBody := c.compileStmts(elif.Body, sc, indent+"    ")
		fmt.Fprintf(&b, " else if (%s) {\n%s%s}", elifCond, elifBody, indent)
	}
	if len(s.Else) > 0 {
		elseBody := c.compileStmts(s.Else, sc, indent+"    ")
		fmt.Fprintf(&b, " else {\n%s%s}", elseBody, indent)
	}
	b.WriteString("\n")
	return b.String()
}

func (c *cg) compileForIn(s *ast.ForInStmt, sc *scope, indent string) string {
	_, isFilter := s.Collection.(*ast.FilterExpr)
	coll := c.compileExpr(s.Collection, sc)
	if s.Value == "" {
		inner := sc.extend(s.Key)
		body := c.compileStmts(s.Body, inner, indent+"    ")
		if isFilter {
			return fmt.Sprintf("%sfor (const %s of %s) {\n%s%s}\n",
				indent, s.Key, coll, body, indent)
		}
		return fmt.Sprintf("%sfor (const %s of %s_iter(%s)) {\n%s%s}\n",
			indent, s.Key, rt, coll, body, indent)
	}
	inner := sc.extend(s.Key).extend(s.Value)
	body := c.compileStmts(s.Body, inner, indent+"    ")
	return fmt.Sprintf("%sfor (const [%s, %s] of %s_entries(%s)) {\n%s%s}\n",
		indent, s.Key, s.Value, rt, coll, body, indent)
}

func (c *cg) compileWhen(s *ast.WhenStmt, sc *scope, indent string) string {
	var expr string
	switch e := s.Expr.(type) {
	case *ast.HandlerCallExpr:
		expr = c.compileHandlerCall(e, sc, true)
	case *ast.NameExpr:
		words := strings.Fields(e.Name)
		if len(words) > 1 && !c.nod[e.Name] {
			expr = c.compileBareCall(words, sc, true)
		} else {
			expr = c.compileExpr(s.Expr, sc)
		}
	default:
		expr = c.compileExpr(s.Expr, sc)
	}
	var b strings.Builder
	fmt.Fprintf(&b, "%sswitch (%s) {\n", indent, expr)
	for _, arm := range s.Arms {
		if arm.Label == "default" {
			fmt.Fprintf(&b, "%s  default: {\n", indent)
		} else if arm.Quoted {
			fmt.Fprintf(&b, "%s  case %s: {\n", indent, jsStr(arm.Label))
		} else {
			fmt.Fprintf(&b, "%s  case %s: {\n", indent, jsStr(arm.Label))
		}
		b.WriteString(c.compileStmts(arm.Body, sc, indent+"      "))
		fmt.Fprintf(&b, "%s    break;\n%s  }\n", indent, indent)
	}
	fmt.Fprintf(&b, "%s}\n", indent)
	return b.String()
}

func (c *cg) compileChoose(s *ast.ChooseStmt, sc *scope, indent string) string {
	var b strings.Builder
	fmt.Fprintf(&b, "%s%s_choose(%s, [\n", indent, rt, jsStr(s.Prompt))
	for _, arm := range s.Arms {
		body := c.compileStmts(arm.Body, sc, indent+"        ")
		fmt.Fprintf(&b, "%s    { label: %s, fn: function() {\n%s%s    }},\n",
			indent, jsStr(arm.Label), body, indent)
	}
	fmt.Fprintf(&b, "%s]);\n", indent)
	return b.String()
}

// compileAssign emits the JS for an assignment or compound-assignment to a
// target expression. op is "=", "+=", "-=", or "is" (kind assignment).
func (c *cg) compileAssign(target ast.Expr, op, rhs string, sc *scope, indent string) string {
	switch t := target.(type) {
	case *ast.NameExpr:
		name := t.Name
		if sc.vars[name] {
			jsOp := op
			if op == "is" {
				jsOp = "="
			}
			return fmt.Sprintf("%s%s %s %s;", indent, name, jsOp, rhs)
		}
		if sc.clsProps[name] && sc.selfName != "" {
			switch op {
			case "=", "is":
				return fmt.Sprintf("%s%s_setProp(%s, %s, %s);", indent, rt, sc.selfName, jsStr(name), rhs)
			case "+=":
				return fmt.Sprintf("%s%s_setProp(%s, %s, %s_prop(%s, %s) + %s);", indent, rt, sc.selfName, jsStr(name), rt, sc.selfName, jsStr(name), rhs)
			case "-=":
				return fmt.Sprintf("%s%s_setProp(%s, %s, %s_prop(%s, %s) - %s);", indent, rt, sc.selfName, jsStr(name), rt, sc.selfName, jsStr(name), rhs)
			}
		}
		switch op {
		case "=", "is":
			return fmt.Sprintf("%s%s_set(%s, %s);", indent, rt, jsStr(name), rhs)
		case "+=":
			return fmt.Sprintf("%s%s_set(%s, %s_get(%s) + %s);", indent, rt, jsStr(name), rt, jsStr(name), rhs)
		case "-=":
			return fmt.Sprintf("%s%s_set(%s, %s_get(%s) - %s);", indent, rt, jsStr(name), rt, jsStr(name), rhs)
		}
	case *ast.PropertyAccess:
		obj := c.compileExpr(t.Object, sc)
		var key string
		if t.KeyExpr != nil {
			key = c.compileExpr(t.KeyExpr, sc)
		} else {
			key = jsStr(t.Key)
		}
		switch op {
		case "=", "is":
			return fmt.Sprintf("%s%s_setProp(%s, %s, %s);", indent, rt, obj, key, rhs)
		case "+=":
			return fmt.Sprintf("%s%s_setProp(%s, %s, %s_prop(%s, %s) + %s);", indent, rt, obj, key, rt, obj, key, rhs)
		case "-=":
			return fmt.Sprintf("%s%s_setProp(%s, %s, %s_prop(%s, %s) - %s);", indent, rt, obj, key, rt, obj, key, rhs)
		}
	}
	return fmt.Sprintf("%s/* unhandled assign */;", indent)
}

// withGuard wraps a single-line JS statement with a postfix if/unless guard.
// The statement already contains indent; the guard condition is inlined.
func (c *cg) withGuard(line string, g *ast.Guard, sc *scope, indent string) string {
	if g == nil {
		return line
	}
	cond := c.compileBoolCond(g.Cond, sc)
	if g.Unless {
		return fmt.Sprintf("%sif (!(%s)) { %s }", indent, cond, strings.TrimLeft(line, " \t"))
	}
	return fmt.Sprintf("%sif (%s) { %s }", indent, cond, strings.TrimLeft(line, " \t"))
}

// ── Expression compilation ─────────────────────────────────────────────────

func (c *cg) compileExpr(e ast.Expr, sc *scope) string {
	switch e := e.(type) {
	case *ast.NumberLit:
		return strconv.Itoa(e.Value)
	case *ast.StringLit:
		return c.compileString(e.Value, sc)
	case *ast.UnsetExpr:
		return "null"
	case *ast.NameExpr:
		return c.compileName(e.Name, sc)
	case *ast.BinaryExpr:
		return c.compileBinary(e, sc)
	case *ast.UnaryExpr:
		inner := c.compileExpr(e.Expr, sc)
		if e.Op == "not" {
			return "!(" + inner + ")"
		}
		return "-(" + inner + ")"
	case *ast.PropertyAccess:
		return c.compilePropAccess(e, sc)
	case *ast.FuncCallExpr:
		return c.compileFuncCallExpr(e, sc)
	case *ast.FilterExpr:
		return fmt.Sprintf("%s_filter(%s, %s)", rt, c.compileExpr(e.Collection, sc), jsStr(e.ClassName))
	case *ast.IsSetExpr:
		inner := c.compileExpr(e.Expr, sc)
		if e.Set {
			return fmt.Sprintf("%s_isset(%s)", rt, inner)
		}
		return fmt.Sprintf("(!%s_isset(%s))", rt, inner)
	case *ast.ImplicitIsExpr:
		kindName := c.kof[e.Value]
		if kindName == "" {
			kindName = e.Value // fallback; sema should catch unknown values
		}
		var cmp string
		if sc.clsProps[kindName] && sc.selfName != "" {
			cmp = fmt.Sprintf("(%s_prop(%s, %s) === %s)", rt, sc.selfName, jsStr(kindName), jsStr(e.Value))
		} else {
			cmp = fmt.Sprintf("(%s_get(%s) === %s)", rt, jsStr(kindName), jsStr(e.Value))
		}
		if e.Negate {
			return "!(" + cmp + ")"
		}
		return cmp
	case *ast.HandlerCallExpr:
		return c.compileHandlerCallExpr(e, sc)
	}
	return "undefined"
}

// compileName resolves a bare name to its JS representation.
//
//   - Handler params and loop vars → bare JS identifier
//   - Class properties (when self is in scope) → _prop(self, key)
//   - Known kind values → quoted string (kind values stored by name at runtime)
//   - Known instance names → quoted string (node key in the world tree)
//   - Multi-word names → bare handler call (_call / _callS for "silently" suffix)
//   - Anything else → _get(key) (world-level property lookup)
func (c *cg) compileName(name string, sc *scope) string {
	if sc.vars[name] {
		return name
	}
	if sc.clsProps[name] && sc.selfName != "" {
		return fmt.Sprintf("%s_prop(%s, %s)", rt, sc.selfName, jsStr(name))
	}
	if name == "true" || name == "false" {
		return jsStr(name) // boolean kind values stored as strings at runtime
	}
	if _, isKind := c.kof[name]; isKind {
		return jsStr(name)
	}
	if c.nod[name] {
		return jsStr(name)
	}
	words := strings.Fields(name)
	if len(words) > 1 {
		return c.compileBareCall(words, sc, false)
	}
	return rt + "_get(" + jsStr(name) + ")"
}

// compileBareCall compiles a multi-word bare handler call (no braces).
// Words that are scope variables become args (with their declared type in the
// sigKey); all other words become sigKey keywords. A trailing "silently" suffix
// switches _call to _callS. tokenCtx=true uses _callT (for when expressions).
func (c *cg) compileBareCall(words []string, sc *scope, tokenCtx bool) string {
	silently := len(words) > 0 && words[len(words)-1] == "silently"
	if silently {
		words = words[:len(words)-1]
	}
	var sigParts []string
	var argExprs []string
	i := 0
	for i < len(words) {
		// Scope variable (always single word) — becomes a typed arg.
		if sc.vars[words[i]] {
			typ := sc.varTypes[words[i]]
			if typ == "" {
				typ = "_"
			}
			sigParts = append(sigParts, typ)
			argExprs = append(argExprs, words[i])
			i++
			continue
		}
		// Try longest-first span of words as a known node instance.
		// Skip a single-word node match when the immediately following word is a
		// scope variable — "beep self" should resolve to verb "beep" + Robot arg,
		// not Command arg + Robot arg, even though "beep" is also a node name.
		matched := false
		for end := len(words); end > i; end-- {
			span := strings.Join(words[i:end], " ")
			if n, ok := c.w.NodeMap[span]; ok {
				if end-i == 1 && end < len(words) && sc.vars[words[end]] {
					break // single-word node followed by scope var → treat as keyword
				}
				cls := n.ClassName
				if cls == "" {
					cls = "_"
				}
				sigParts = append(sigParts, cls)
				argExprs = append(argExprs, jsStr(span))
				i = end
				matched = true
				break
			}
		}
		if !matched {
			// World-level var: type unknown at compile time; runtime resolves via _class().
			if c.isWorldVar(words[i]) {
				sigParts = append(sigParts, "_")
				argExprs = append(argExprs, rt+"_get("+jsStr(words[i])+")")
				i++
				continue
			}
			sigParts = append(sigParts, words[i])
			i++
		}
	}
	sigKey := strings.Join(sigParts, " ")
	var fn string
	switch {
	case tokenCtx:
		fn = rt + "_callT"
	case silently:
		fn = rt + "_callS"
	default:
		fn = rt + "_call"
	}
	if len(argExprs) > 0 {
		return fmt.Sprintf("%s(%s, %s)", fn, jsStr(sigKey), strings.Join(argExprs, ", "))
	}
	return fmt.Sprintf("%s(%s)", fn, jsStr(sigKey))
}

func (c *cg) compileBinary(e *ast.BinaryExpr, sc *scope) string {
	switch e.Op {
	case "is":
		return c.compileIs(e, sc)
	case "isnt":
		return "!(" + c.compileIs(&ast.BinaryExpr{Pos: e.Pos, Left: e.Left, Op: "is", Right: e.Right}, sc) + ")"
	case "and":
		return "(" + c.compileExpr(e.Left, sc) + " && " + c.compileExpr(e.Right, sc) + ")"
	case "or":
		return "(" + c.compileExpr(e.Left, sc) + " || " + c.compileExpr(e.Right, sc) + ")"
	case "modulo":
		return "((" + c.compileExpr(e.Left, sc) + ") % (" + c.compileExpr(e.Right, sc) + "))"
	case "<", ">", "<=", ">=":
		left := c.compileExpr(e.Left, sc)
		right := c.compileExpr(e.Right, sc)
		if c.isKindExpr(e.Left) || c.isKindExpr(e.Right) {
			return fmt.Sprintf("(%s_kindOrd(%s) %s %s_kindOrd(%s))", rt, left, e.Op, rt, right)
		}
		return fmt.Sprintf("((%s) %s (%s))", left, e.Op, right)
	default: // ==, +, -, *, /
		return fmt.Sprintf("((%s) %s (%s))", c.compileExpr(e.Left, sc), e.Op, c.compileExpr(e.Right, sc))
	}
}

// compileIs handles the `is` operator.
//
//   - "peter is sad"        → _prop(peter, "mood") === "sad"
//   - "lamp is lit"         → _prop(lamp, "light") === "lit"
//   - "peter.mood is sad"   → _prop(peter,"mood") === "sad"  (left already a prop access)
//   - "x is Robot"          → _instanceof(x, "Robot")
//   - "x is location"       → x === "location" (instance ref comparison)
func (c *cg) compileIs(e *ast.BinaryExpr, sc *scope) string {
	right, isName := e.Right.(*ast.NameExpr)
	if !isName {
		return fmt.Sprintf("(%s === %s)", c.compileExpr(e.Left, sc), c.compileExpr(e.Right, sc))
	}

	// Class instanceof check
	if len(right.Name) > 0 && right.Name[0] >= 'A' && right.Name[0] <= 'Z' {
		return fmt.Sprintf("%s_instanceof(%s, %s)", rt, c.compileExpr(e.Left, sc), jsStr(right.Name))
	}

	// Kind value: "peter is sad" — left must be a node ref so we look up the kind prop
	if kindName, ok := c.kof[right.Name]; ok {
		left := c.compileExpr(e.Left, sc)
		if leftName, leftIsName := e.Left.(*ast.NameExpr); leftIsName {
			// "topic is nothing_to_talk_about" — left IS the kind variable itself
			// (e.g., a world-level kind var named the same as the kind). The var
			// already stores the value directly, so compare without _prop.
			if leftName.Name == kindName && !sc.vars[leftName.Name] {
				return fmt.Sprintf("(%s === %s)", left, jsStr(right.Name))
			}
			if sc.clsProps[leftName.Name] && sc.selfName != "" {
				// left is a class property already compiled as R._prop(self,"propName")
				// — it already holds the kind value, so compare directly
				return fmt.Sprintf("(%s === %s)", left, jsStr(right.Name))
			}
			// bare node ref → look up kind property on it
			return fmt.Sprintf("(%s_prop(%s, %s) === %s)", rt, left, jsStr(kindName), jsStr(right.Name))
		}
		// left is already a prop access or computed value
		return fmt.Sprintf("(%s === %s)", left, jsStr(right.Name))
	}

	// Boolean literals — kind values "true"/"false" are stored as strings at runtime.
	if right.Name == "true" || right.Name == "false" {
		return fmt.Sprintf("(%s === %s)", c.compileExpr(e.Left, sc), jsStr(right.Name))
	}

	// General equality (instance ref or world property comparison)
	return fmt.Sprintf("(%s === %s)", c.compileExpr(e.Left, sc), c.compileExpr(e.Right, sc))
}

// isKindExpr reports whether an expression statically resolves to a kind value.
// isWorldVar reports whether name is a world-level property (var declared at
// world scope). These have no compile-time type; dispatch uses runtime _class().
func (c *cg) isWorldVar(name string) bool {
	for _, p := range c.w.Root.Props {
		if p.Key == name {
			return true
		}
	}
	return false
}

func (c *cg) isKindExpr(e ast.Expr) bool {
	name, ok := e.(*ast.NameExpr)
	if !ok {
		return false
	}
	_, isKind := c.kof[name.Name]
	return isKind
}

func (c *cg) compilePropAccess(e *ast.PropertyAccess, sc *scope) string {
	obj := c.compileExpr(e.Object, sc)
	if e.KeyExpr != nil {
		key := c.compileExpr(e.KeyExpr, sc)
		return fmt.Sprintf("%s_prop(%s, %s)", rt, obj, key)
	}
	switch e.Key {
	case "length":
		return fmt.Sprintf("%s_length(%s)", rt, obj)
	case "class":
		return fmt.Sprintf("%s_class(%s)", rt, obj)
	case "name":
		return fmt.Sprintf("%s_name(%s)", rt, obj)
	}
	return fmt.Sprintf("%s_prop(%s, %s)", rt, obj, jsStr(e.Key))
}

func (c *cg) compileFuncCallExpr(e *ast.FuncCallExpr, sc *scope) string {
	args := make([]string, len(e.Args))
	for i, a := range e.Args {
		args[i] = c.compileExpr(a, sc)
	}
	joined := strings.Join(args, ", ")
	switch e.Name {
	case "floor":
		return "Math.floor(" + joined + ")"
	case "ceiling":
		return "Math.ceil(" + joined + ")"
	case "round":
		return "Math.round(" + joined + ")"
	case "absolute":
		return "Math.abs(" + joined + ")"
	case "biggest":
		return "Math.max(" + joined + ")"
	case "smallest":
		return "Math.min(" + joined + ")"
	case "random":
		return rt + "_random(" + joined + ")"
	case "seed":
		return rt + "_seed(" + joined + ")"
	case "through":
		return rt + "_through(" + joined + ")"
	}
	return rt + "_fn_" + e.Name + "(" + joined + ")"
}

// compileHandlerCallExpr emits a _call("sigKey", ...args) for an inline {call}.
// The sigKey is assembled from the word parts; argument expressions are emitted
// in order. The runtime resolves the sigKey against the handler table.
func (c *cg) compileHandlerCallExpr(e *ast.HandlerCallExpr, sc *scope) string {
	return c.compileHandlerCall(e, sc, false)
}

// compileHandlerCall is the shared implementation. tokenCtx=true emits _callT,
// which returns the token for both _SucceedSignal and _FailSignal — needed when
// the call is the switch expression of a when statement.
func (c *cg) compileHandlerCall(e *ast.HandlerCallExpr, sc *scope, tokenCtx bool) string {
	var words []string
	var argExprs []string
	for _, part := range e.Parts {
		switch p := part.(type) {
		case ast.HandlerCallWord:
			word := p.Word
			if sc.vars[word] {
				// Variable in scope: use its declared type in the sigKey so that
				// the call matches the registered handler (which uses type names,
				// e.g. "has Object" not "has item").
				typ := sc.varTypes[word]
				if typ == "" {
					typ = "_"
				}
				words = append(words, typ)
				argExprs = append(argExprs, c.compileName(word, sc))
			} else {
				words = append(words, word)
			}
		case ast.HandlerCallArg:
			// Use the literal type name when statically known so the sigKey
			// matches the handler registration ("score number", not "score _").
			typ := "_"
			switch p.Expr.(type) {
			case *ast.NumberLit:
				typ = "number"
			case *ast.StringLit:
				typ = "string"
			}
			words = append(words, typ)
			argExprs = append(argExprs, c.compileExpr(p.Expr, sc))
		}
	}
	sigKey := strings.Join(words, " ")
	var fn string
	switch {
	case tokenCtx:
		fn = rt + "_callT"
	case e.Silently:
		fn = rt + "_callS"
	default:
		fn = rt + "_call"
	}
	if len(argExprs) > 0 {
		return fmt.Sprintf("%s(%s, %s)", fn, jsStr(sigKey), strings.Join(argExprs, ", "))
	}
	return fmt.Sprintf("%s(%s)", fn, jsStr(sigKey))
}

// compileSignalToken compiles the token expression of a fail/succeed statement.
// Bare identifier tokens that are not kind values, instance names, or local
// variables are signal names — they must compile to their literal string, not
// to a world-property lookup via _get(). Kind values and instance names compile
// normally (they are already string literals via compileName).
func (c *cg) compileSignalToken(e ast.Expr, sc *scope) string {
	if name, ok := e.(*ast.NameExpr); ok {
		n := name.Name
		if !sc.vars[n] && !c.nod[n] {
			if _, isKind := c.kof[n]; !isKind {
				if n != "true" && n != "false" {
					return jsStr(n) // bare signal name → literal string
				}
			}
		}
	}
	return c.compileExpr(e, sc)
}

// ── Say string compilation ─────────────────────────────────────────────────

// htmlEscape escapes &, <, > so literal text is safe for insertAdjacentHTML.
func htmlEscape(s string) string {
	s = strings.ReplaceAll(s, "&", "&amp;")
	s = strings.ReplaceAll(s, "<", "&lt;")
	s = strings.ReplaceAll(s, ">", "&gt;")
	return s
}

// semanticHTMLInlineTags are [word] tags that emit native HTML elements, not
// <span>. They need no Style declaration and are not validated against Styles.
var semanticHTMLInlineTags = map[string]bool{
	"em": true, "strong": true, "code": true,
	"mark": true, "s": true, "u": true,
}

// isStyleName reports whether name is a declared Style instance (or subclass).
func (c *cg) isStyleName(name string) bool {
	node, ok := c.w.NodeMap[name]
	if !ok {
		return false
	}
	cls := node.ClassName
	for cls != "" {
		if cls == "Style" {
			return true
		}
		cl, ok := c.w.ClassMap[cls]
		if !ok {
			break
		}
		cls = cl.Parent
	}
	return false
}

// sayTok is one token from a say string: literal text, {expr} slot, or a tag.
// kind values:
//   "text"     — literal text (will be HTML-escaped)
//   "expr"     — {expr} interpolation slot
//   "spanOpen" — [StyleName] → <span class="StyleName">
//   "spanClose"— [/StyleName] → </span>
//   "htmlOpen" — [em], [strong], etc. → <em>, <strong>, etc.
//   "htmlClose"— [/em], [/strong], etc. → </em>, etc.
type sayTok struct {
	kind  string
	value string // text/expr content, span class, or HTML tag name
}

// splitSayInterp tokenises a raw say string, recognising {expr} interpolation
// and [Style]...[/Style] span tags. Unknown [word] tags pass through as text.
func (c *cg) splitSayInterp(raw string) []sayTok {
	var toks []sayTok
	var buf strings.Builder
	flushText := func() {
		if buf.Len() > 0 {
			toks = append(toks, sayTok{"text", buf.String()})
			buf.Reset()
		}
	}
	i := 0
	for i < len(raw) {
		switch {
		case raw[i] == '{':
			flushText()
			depth, j := 1, i+1
			for j < len(raw) && depth > 0 {
				if raw[j] == '{' {
					depth++
				} else if raw[j] == '}' {
					depth--
				}
				j++
			}
			toks = append(toks, sayTok{"expr", raw[i+1 : j-1]})
			i = j
		case raw[i] == '[':
			end := strings.IndexByte(raw[i:], ']')
			if end == -1 {
				buf.WriteByte('[')
				i++
				continue
			}
			end += i
			tag := raw[i+1 : end]
			i = end + 1
			if strings.HasPrefix(tag, "/") {
				word := tag[1:]
				if semanticHTMLInlineTags[word] {
					flushText()
					toks = append(toks, sayTok{"htmlClose", word})
				} else if c.isStyleName(word) {
					flushText()
					toks = append(toks, sayTok{"spanClose", word})
				} else {
					buf.WriteByte('[')
					buf.WriteString(tag)
					buf.WriteByte(']')
				}
			} else if semanticHTMLInlineTags[tag] {
				flushText()
				toks = append(toks, sayTok{"htmlOpen", tag})
			} else if c.isStyleName(tag) {
				flushText()
				toks = append(toks, sayTok{"spanOpen", tag})
			} else {
				buf.WriteByte('[')
				buf.WriteString(tag)
				buf.WriteByte(']')
			}
		default:
			buf.WriteByte(raw[i])
			i++
		}
	}
	flushText()
	return toks
}

// compileSayString produces an HTML-safe JS template-literal expression:
// literal text is HTML-escaped at compile time, {expr} uses R._hstr() for
// runtime HTML-escaping, [Style]...[/Style] becomes <span> elements, and
// [em]/[strong]/etc. become native HTML elements. Unclosed tags are
// automatically closed at the end of the string.
func (c *cg) compileSayString(raw string, sc *scope) string {
	toks := c.splitSayInterp(raw)
	var b strings.Builder
	var openStack []sayTok // tracks unclosed span/html opens for auto-close
	b.WriteRune('`')
	for _, tok := range toks {
		switch tok.kind {
		case "text":
			b.WriteString(escapeTmpl(htmlEscape(tok.value)))
		case "expr":
			expr, err := parser.ParseExpr(tok.value)
			if err != nil {
				fmt.Fprintf(&b, "${/* parse error: %s */\"\"}", tok.value)
				continue
			}
			b.WriteString("${" + rt + "_hstr(")
			b.WriteString(c.compileExpr(expr, sc))
			b.WriteString(")}")
		case "spanOpen":
			fmt.Fprintf(&b, `<span class="%s">`, tok.value)
			openStack = append(openStack, tok)
		case "spanClose":
			b.WriteString("</span>")
			if len(openStack) > 0 {
				openStack = openStack[:len(openStack)-1]
			}
		case "htmlOpen":
			fmt.Fprintf(&b, "<%s>", tok.value)
			openStack = append(openStack, tok)
		case "htmlClose":
			fmt.Fprintf(&b, "</%s>", tok.value)
			if len(openStack) > 0 {
				openStack = openStack[:len(openStack)-1]
			}
		}
	}
	// Auto-close any unclosed tags in reverse open order.
	for i := len(openStack) - 1; i >= 0; i-- {
		switch openStack[i].kind {
		case "spanOpen":
			b.WriteString("</span>")
		case "htmlOpen":
			fmt.Fprintf(&b, "</%s>", openStack[i].value)
		}
	}
	b.WriteRune('`')
	return b.String()
}

// ── String interpolation ───────────────────────────────────────────────────

// tmplSeg is one segment of an interpolated string — either literal text or
// a {expression} slot.
type tmplSeg struct {
	text string // non-empty for a literal text segment
	expr string // non-empty for an expression segment (raw Grue source)
}

// splitInterp splits a raw Grue string value into alternating text and
// expression segments. Brace depth is tracked so nested {obj.{key}} works.
func splitInterp(s string) []tmplSeg {
	var segs []tmplSeg
	var buf strings.Builder
	i := 0
	for i < len(s) {
		if s[i] == '{' {
			if buf.Len() > 0 {
				segs = append(segs, tmplSeg{text: buf.String()})
				buf.Reset()
			}
			depth, j := 1, i+1
			for j < len(s) && depth > 0 {
				if s[j] == '{' {
					depth++
				} else if s[j] == '}' {
					depth--
				}
				j++
			}
			segs = append(segs, tmplSeg{expr: s[i+1 : j-1]})
			i = j
		} else {
			buf.WriteByte(s[i])
			i++
		}
	}
	if buf.Len() > 0 {
		segs = append(segs, tmplSeg{text: buf.String()})
	}
	return segs
}

// escapeTmpl escapes characters that are special inside a JS template literal.
func escapeTmpl(s string) string {
	s = strings.ReplaceAll(s, `\`, `\\`)
	s = strings.ReplaceAll(s, "`", "\\`")
	s = strings.ReplaceAll(s, "${", "\\${")
	return s
}

// compileString converts a raw Grue string value (which may contain
// {expression} interpolation slots) into a JS expression — either a plain
// quoted string when there are no slots, or a template literal.
func (c *cg) compileString(raw string, sc *scope) string {
	segs := splitInterp(raw)

	// Fast path: no interpolation → plain JS string literal.
	hasExpr := false
	for _, seg := range segs {
		if seg.expr != "" {
			hasExpr = true
			break
		}
	}
	if !hasExpr {
		return jsStr(raw)
	}

	var b strings.Builder
	b.WriteRune('`')
	for _, seg := range segs {
		if seg.text != "" {
			b.WriteString(escapeTmpl(seg.text))
		} else {
			expr, err := parser.ParseExpr(seg.expr)
			if err != nil {
				// Emit a visible placeholder so the author sees the failure.
				fmt.Fprintf(&b, "${/* parse error: %s */\"\"}", seg.expr)
				continue
			}
			b.WriteString("${" + rt + "_str(")
			b.WriteString(c.compileExpr(expr, sc))
			b.WriteString(")}")
		}
	}
	b.WriteRune('`')
	return b.String()
}

// ── tests ──────────────────────────────────────────────────────────────────

// emptyScope is used when compiling {expr} test assertions, which have no
// handler parameters, class properties, or self reference.
var emptyScope = &scope{vars: make(map[string]bool), varTypes: make(map[string]string), clsProps: make(map[string]bool)}

func (c *cg) writeTests(b *strings.Builder) {
	if len(c.w.Tests) == 0 {
		b.WriteString("  tests: {},\n")
		return
	}
	b.WriteString("  tests: {\n")
	for _, test := range c.w.Tests {
		fmt.Fprintf(b, "    %s: { room: %s, steps: [\n", jsStr(test.Name), jsStr(test.Room))
		for _, step := range test.Steps {
			switch {
			case step.SetupStmt != nil:
				body := c.compileStmt(step.SetupStmt, emptyScope, "")
				fmt.Fprintf(b, "      { setup: function() { %s } },\n", strings.TrimSpace(body))
			case step.SubTest != "":
				fmt.Fprintf(b, "      { sub: %s },\n", jsStr(step.SubTest))
			case step.Expr != nil:
				compiled := c.compileExpr(step.Expr, emptyScope)
				if step.Assert != "" {
					fmt.Fprintf(b, "      { exprFn: function() { return R._str(%s); }, assert: %s, negate: %v },\n",
						compiled, jsStr(step.Assert), step.Negate)
				} else {
					fmt.Fprintf(b, "      { exprFn: function() { return R._str(%s); } },\n", compiled)
				}
			case step.Cmd == "":
				if step.Assert != "" {
					fmt.Fprintf(b, "      { tick: true, assert: %s, negate: %v },\n", jsStr(step.Assert), step.Negate)
				} else {
					b.WriteString("      { tick: true },\n")
				}
			default:
				if step.Assert != "" {
					fmt.Fprintf(b, "      { cmd: %s, assert: %s, negate: %v },\n",
						jsStr(step.Cmd), jsStr(step.Assert), step.Negate)
				} else {
					fmt.Fprintf(b, "      { cmd: %s },\n", jsStr(step.Cmd))
				}
			}
		}
		b.WriteString("    ] },\n")
	}
	b.WriteString("  },\n")
}

// ── exits and door connections ─────────────────────────────────────────────

// writeExits emits an exits:{} object on Room nodes listing direction→dest.
// Every RefValue property is emitted — custom directions (e.g. "top of ladder")
// are included alongside compass directions.
func writeExits(b *strings.Builder, node *world.Node) {
	if node.ClassName != "Room" {
		return
	}
	var parts []string
	for _, prop := range node.Props {
		if ref, ok := prop.Value.(world.RefValue); ok {
			parts = append(parts, fmt.Sprintf("%s: %s", jsStr(prop.Key), jsStr(ref.Name)))
		}
	}
	if len(parts) > 0 {
		fmt.Fprintf(b, ", exits: {%s}", strings.Join(parts, ", "))
	}
}

// writeConnects emits a connects:[] array on Door nodes listing the rooms
// each side leads to. Doors can have two "leads to" props (one per side).
func writeConnects(b *strings.Builder, node *world.Node) {
	if node.ClassName != "Door" {
		return
	}
	var dests []string
	for _, prop := range node.Props {
		if prop.Key == "leads to" {
			if ref, ok := prop.Value.(world.RefValue); ok {
				dests = append(dests, jsStr(ref.Name))
			}
		}
	}
	if len(dests) > 0 {
		fmt.Fprintf(b, ", connects: [%s]", strings.Join(dests, ", "))
	}
}

// ── grammar ────────────────────────────────────────────────────────────────

func writeGrammar(b *strings.Builder, g *grammar.Grammar) {
	b.WriteString("  grammar: ")
	writeTrieNode(b, g.Root, 1)
	b.WriteString(",\n")
}

func writeTrieNode(b *strings.Builder, node *grammar.TrieNode, depth int) {
	pad := strings.Repeat("  ", depth)
	b.WriteString("{\n")
	fmt.Fprintf(b, "%s  sigKey: %s,\n", pad, jsStr(node.SigKey))

	// keywords (sorted for determinism)
	if len(node.Keywords) == 0 {
		fmt.Fprintf(b, "%s  keywords: {},\n", pad)
	} else {
		fmt.Fprintf(b, "%s  keywords: {\n", pad)
		for _, word := range sortedKeys(node.Keywords) {
			fmt.Fprintf(b, "%s    %s: ", pad, jsStr(word))
			writeTrieNode(b, node.Keywords[word], depth+2)
			b.WriteString(",\n")
		}
		fmt.Fprintf(b, "%s  },\n", pad)
	}

	// params
	if len(node.Params) == 0 {
		fmt.Fprintf(b, "%s  params: []\n", pad)
	} else {
		fmt.Fprintf(b, "%s  params: [\n", pad)
		for _, edge := range node.Params {
			fmt.Fprintf(b, "%s    { type: %s, next: ", pad, jsStr(edge.Type))
			writeTrieNode(b, edge.Next, depth+2)
			b.WriteString(" },\n")
		}
		fmt.Fprintf(b, "%s  ]\n", pad)
	}

	fmt.Fprintf(b, "%s}", pad)
}

// ── vocab ──────────────────────────────────────────────────────────────────

// writeVocab emits the vocabulary map. Keys are lowercased so the runtime
// can match case-insensitive player input directly.
func writeVocab(b *strings.Builder, w *world.World) {
	if len(w.Vocab) == 0 {
		b.WriteString("  vocab: {},\n")
		return
	}
	b.WriteString("  vocab: {\n")
	// Deduplicate after lowercasing (first canonical name wins).
	lower := make(map[string]string, len(w.Vocab))
	for form, canonical := range w.Vocab {
		key := strings.ToLower(form)
		if _, exists := lower[key]; !exists {
			lower[key] = canonical
		}
	}
	for _, key := range sortedKeys(lower) {
		fmt.Fprintf(b, "    %s: %s,\n", jsStr(key), jsStr(lower[key]))
	}
	b.WriteString("  },\n")
}

// ── world tree helpers ─────────────────────────────────────────────────────

// worldNodes returns all instance nodes in document order (depth-first walk
// of Root.Children). Class template children are excluded.
func worldNodes(w *world.World) []*world.Node {
	var nodes []*world.Node
	for _, child := range w.Root.Children {
		collectNodes(&nodes, child)
	}
	return nodes
}

func collectNodes(out *[]*world.Node, node *world.Node) {
	*out = append(*out, node)
	for _, child := range node.Children {
		collectNodes(out, child)
	}
}

// locationOf returns the initial location of a node.
func locationOf(node *world.Node) string {
	for _, prop := range node.Props {
		if prop.Key == "location" {
			if ref, ok := prop.Value.(world.RefValue); ok {
				return ref.Name
			}
		}
	}
	if node.Parent != nil {
		return node.Parent.Name
	}
	return ""
}

// findStart returns the player's starting room name.
func findStart(w *world.World) string {
	if player, ok := w.NodeMap["player"]; ok {
		if loc := locationOf(player); loc != "" {
			return loc
		}
	}
	for _, child := range w.Root.Children {
		if child.ClassName == "Room" {
			return child.Name
		}
	}
	return ""
}

// ── JS helpers ─────────────────────────────────────────────────────────────

func jsStr(s string) string {
	b, _ := json.Marshal(s)
	return string(b)
}

func sortedKeys[V any](m map[string]V) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}
