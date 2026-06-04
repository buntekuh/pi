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
	"strings"

	"gruc/grammar"
	"gruc/world"
)

//go:embed runtime.js
var RuntimeJS string

// Emit generates the game-script JS for the given world and grammar.
// The output is a single GrueRuntime.init({...}) call.
// Fields not yet implemented for the current milestone are omitted; the
// runtime ignores unknown fields, so older scripts run against newer runtimes.
func Emit(w *world.World, _ *grammar.Grammar) string {
	var b strings.Builder
	b.WriteString("GrueRuntime.init({\n")
	writeMeta(&b, w.Game)
	writeNodes(&b, w)
	writeStart(&b, w)
	b.WriteString("});\n")
	return b.String()
}

// HTML returns a complete self-contained HTML page: the runtime and the
// game script are both inlined. No external resources are referenced.
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
<script>
%s</script>
<script>
%s</script>
</body>
</html>
`, html.EscapeString(title), RuntimeJS, Emit(w, g))
}

// ── Descriptor sections ────────────────────────────────────────────────────

func writeMeta(b *strings.Builder, game world.GameInfo) {
	b.WriteString("  meta: {\n")
	fmt.Fprintf(b, "    title:   %s,\n", jsStr(game.Title))
	fmt.Fprintf(b, "    author:  %s,\n", jsStr(game.Author))
	fmt.Fprintf(b, "    version: %s\n", jsStr(game.Version))
	b.WriteString("  },\n")
}

func writeNodes(b *strings.Builder, w *world.World) {
	nodes := worldNodes(w)
	if len(nodes) == 0 {
		b.WriteString("  nodes: {},\n")
		return
	}
	b.WriteString("  nodes: {\n")
	for i, node := range nodes {
		fmt.Fprintf(b, "    %s: { class: %s", jsStr(node.Name), jsStr(node.ClassName))
		if node.Desc != "" {
			fmt.Fprintf(b, ", desc: %s", jsStr(node.Desc))
		}
		if loc := locationOf(node); loc != "" {
			fmt.Fprintf(b, ", location: %s", jsStr(loc))
		}
		b.WriteString(" }")
		if i < len(nodes)-1 {
			b.WriteString(",")
		}
		b.WriteString("\n")
	}
	b.WriteString("  },\n")
}

func writeStart(b *strings.Builder, w *world.World) {
	fmt.Fprintf(b, "  start: %s\n", jsStr(findStart(w)))
}

// ── Helpers ────────────────────────────────────────────────────────────────

// worldNodes returns all instance nodes in document order (depth-first walk
// of Root.Children). Class template children are excluded — they are not
// live world instances.
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

// locationOf returns the initial location of a node: the value of its
// explicit "location" property if present, otherwise the name of its
// parent node (i.e. it was declared inside another instance's body).
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

// findStart returns the name of the player's starting room.
// It checks for an explicit player.location prop first, then falls back
// to the first Room declared at the top level.
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

// jsStr returns the JSON encoding of s, which is also valid JavaScript.
func jsStr(s string) string {
	b, _ := json.Marshal(s)
	return string(b)
}
