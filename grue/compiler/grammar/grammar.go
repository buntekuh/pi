// Package grammar constructs the player-input parser for a Grue game from
// all public (non-internal) handler signatures in the world tree.
//
// The output is a pattern trie. Each path through the trie corresponds to one
// valid command pattern. Leaves carry the SigKey that the runtime dispatches
// to when a player command matches that path.
//
// Trie structure:
//
//	TrieNode
//	├── Keywords  map[word → TrieNode]   — literal word edges
//	└── Params    []*ParamEdge           — typed parameter slots
//	    └── Type string                  — "number", "string", "Object", or class name
//
// Example — `on open Ledger:ledger at number:page:` inserts:
//
//	root →["open"]→ node1 →[Ledger]→ node2 →["at"]→ node3 →[number]→ leaf{SigKey:"open Ledger at number"}
//
// Multiple handlers may share prefixes; the trie merges them naturally.
// Handlers with the same SigKey are deduplicated — only the first occurrence
// (in world-tree order) contributes a trie entry.
package grammar

// Grammar is the compiled player-input grammar produced by Step 5.
// It is consumed by Step 6 (code generation) to emit the runtime parser.
type Grammar struct {
	Root *TrieNode
}

// TrieNode is one node in the pattern trie.
type TrieNode struct {
	Keywords map[string]*TrieNode // keyword word → child node
	Params   []*ParamEdge         // typed parameter slots (ordered by insertion)
	SigKey   string               // non-empty at terminal (leaf) nodes
}

// ParamEdge is an outgoing typed-parameter edge from a TrieNode.
// At runtime the player-input parser uses Type to decide what to consume:
//   - "number"      — any integer token
//   - "string"      — a quoted string token
//   - "Object"      — any object/item name from the vocabulary
//   - a class name  — any instance of that class (or a subclass) in the vocabulary
type ParamEdge struct {
	Type string
	Next *TrieNode
}

func newTrieNode() *TrieNode {
	return &TrieNode{}
}
