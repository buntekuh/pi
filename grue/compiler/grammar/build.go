package grammar

import (
	"gruc/ast"
	"gruc/world"
)

// Build constructs the player-input grammar trie from a world tree.
//
// All public (non-internal) on-handlers across global scope, classes, and
// instances are collected.  Handlers with the same SigKey are deduplicated —
// the first occurrence in world-tree order (global → classes → instances,
// depth-first) wins.  This matches the runtime dispatch priority order so
// that the grammar trie reflects exactly what patterns players can type.
func Build(w *world.World) *Grammar {
	g := &Grammar{Root: newTrieNode()}
	seen := make(map[string]bool)

	// Global handlers
	addHandlers(g, w.Root.Handlers, seen)

	// Class handlers (in declaration order)
	for _, cls := range w.Classes {
		addHandlers(g, cls.Handlers, seen)
	}

	// Instance handlers (world-tree order, depth-first)
	for _, child := range w.Root.Children {
		addNodeHandlers(g, child, seen)
	}

	return g
}

// addNodeHandlers walks a Node subtree depth-first, inserting each node's
// public handlers into the grammar.
func addNodeHandlers(g *Grammar, node *world.Node, seen map[string]bool) {
	addHandlers(g, node.Handlers, seen)
	for _, child := range node.Children {
		addNodeHandlers(g, child, seen)
	}
}

// addHandlers inserts each public handler in hs into the grammar trie, skipping
// internal handlers and any SigKey already seen.
func addHandlers(g *Grammar, hs []*world.Handler, seen map[string]bool) {
	for _, h := range hs {
		if h.Internal || seen[h.SigKey] {
			continue
		}
		seen[h.SigKey] = true
		insert(g.Root, h.ResolvedSig, h.SigKey)
	}
}

// insert walks (or creates) the trie path for sig, setting SigKey at the
// terminal node.  Keywords become literal word edges; parameters become
// typed slot edges (reusing an existing edge if the same type is already
// present at that position).
func insert(node *TrieNode, sig []ast.SigPart, sigKey string) {
	for _, part := range sig {
		switch p := part.(type) {
		case ast.SigKeyword:
			if node.Keywords == nil {
				node.Keywords = make(map[string]*TrieNode)
			}
			next, ok := node.Keywords[p.Word]
			if !ok {
				next = newTrieNode()
				node.Keywords[p.Word] = next
			}
			node = next

		case ast.SigParam:
			var next *TrieNode
			for _, edge := range node.Params {
				if edge.Type == p.Type {
					next = edge.Next
					break
				}
			}
			if next == nil {
				next = newTrieNode()
				node.Params = append(node.Params, &ParamEdge{Type: p.Type, Next: next})
			}
			node = next
		}
	}
	node.SigKey = sigKey
}
