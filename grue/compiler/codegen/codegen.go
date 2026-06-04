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
	"gruc/world"
)

//go:embed runtime.js
var RuntimeJS string

// Emit generates the game-script JS for the given world and grammar.
// The output is a single GrueRuntime.init({...}) call.
func Emit(w *world.World, g *grammar.Grammar) string {
	var b strings.Builder
	b.WriteString("GrueRuntime.init({\n")
	writeMeta(&b, w.Game)
	writeKinds(&b, w)
	writeClasses(&b, w)
	writeNodes(&b, w)
	writeStart(&b, w)
	writeHandlers(&b, w)
	writeGrammar(&b, g)
	writeVocab(&b, w)
	b.WriteString("});\n")
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
</head>
<body>
<div id="output"></div>
<div id="tree" style="display:none"></div>
<div id="input-area">
  <input id="cmd" type="text" autofocus>
  <button id="go">Go</button>
  <button id="tree-btn">Tree</button>
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
	if len(nodes) == 0 {
		b.WriteString("  nodes: {},\n")
		return
	}
	b.WriteString("  nodes: {\n")
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
		b.WriteString(", props: ")
		writePropsObject(b, node.Props)
		b.WriteString(" },\n")
	}
	b.WriteString("  },\n")
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
type handlerEntry struct {
	owner   string
	handler *world.Handler
}

// writeHandlers emits the handlers map: sigKey → ordered list of {owner, fn}.
// Chain order: instance → class → global own → global library.
func writeHandlers(b *strings.Builder, w *world.World) {
	chains := buildHandlerChains(w)
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
			fmt.Fprintf(b, "      { owner: %s, fn: %s },\n",
				owner, compileHandler(e.handler))
		}
		b.WriteString("    ],\n")
	}
	b.WriteString("  },\n")
}

func buildHandlerChains(w *world.World) map[string][]handlerEntry {
	chains := make(map[string][]handlerEntry)
	add := func(sigKey, owner string, h *world.Handler) {
		chains[sigKey] = append(chains[sigKey], handlerEntry{owner, h})
	}
	// Instance handlers (most specific)
	for _, node := range worldNodes(w) {
		for _, h := range node.Handlers {
			if !h.Internal {
				add(h.SigKey, node.Name, h)
			}
		}
	}
	// Class handlers
	for _, cls := range w.Classes {
		for _, h := range cls.Handlers {
			if !h.Internal {
				add(h.SigKey, cls.Name, h)
			}
		}
	}
	// Global own-game handlers
	for _, h := range w.Root.Handlers {
		if !h.Internal && !h.IsLibrary {
			add(h.SigKey, "", h)
		}
	}
	// Global library handlers (last)
	for _, h := range w.Root.Handlers {
		if !h.Internal && h.IsLibrary {
			add(h.SigKey, "", h)
		}
	}
	return chains
}

// ── handler compilation ────────────────────────────────────────────────────

// compileHandler emits a JS function expression for a single handler.
// For M2, only SayStmt with a plain string literal is compiled; all other
// statement types are left as stubs and will be filled in later milestones.
func compileHandler(h *world.Handler) string {
	var params []string
	for _, part := range h.ResolvedSig {
		if p, ok := part.(ast.SigParam); ok {
			params = append(params, p.Name)
		}
	}
	body := compileStmts(h.Body)
	if body == "" {
		return fmt.Sprintf("function(%s) {}", strings.Join(params, ", "))
	}
	return fmt.Sprintf("function(%s) {\n%s      }",
		strings.Join(params, ", "), body)
}

func compileStmts(stmts []ast.Stmt) string {
	var b strings.Builder
	for _, stmt := range stmts {
		switch s := stmt.(type) {
		case *ast.SayStmt:
			if lit, ok := s.Text.(*ast.StringLit); ok {
				fmt.Fprintf(&b, "        say(%s);\n", jsStr(lit.Value))
			}
			// M4: non-literal (interpolated) say expressions
		// M3+: assign, if, for, fail, succeed, call, parent, …
		}
	}
	return b.String()
}

// ── exits and door connections ─────────────────────────────────────────────

// compassDirs is the set of property keys treated as room exits.
var compassDirs = map[string]bool{
	"north": true, "south": true, "east": true, "west": true,
	"up": true, "down": true, "in": true, "out": true,
	"northeast": true, "northwest": true, "southeast": true, "southwest": true,
}

// writeExits emits an exits:{} object on Room nodes listing direction→dest.
func writeExits(b *strings.Builder, node *world.Node) {
	if node.ClassName != "Room" {
		return
	}
	var parts []string
	for _, prop := range node.Props {
		if compassDirs[prop.Key] {
			if ref, ok := prop.Value.(world.RefValue); ok {
				parts = append(parts, fmt.Sprintf("%s: %s", jsStr(prop.Key), jsStr(ref.Name)))
			}
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
		b.WriteString("  vocab: {}\n")
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
	b.WriteString("  }\n")
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
