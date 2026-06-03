package main

import (
	"fmt"
	"gruc/ast"
	"gruc/lexer"
	"gruc/parser"
	"gruc/sema"
	"gruc/world"
	"os"
)

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: gruc <file.grue>")
		os.Exit(1)
	}

	src, err := os.ReadFile(os.Args[1])
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}

	tokens, err := lexer.Tokenize(string(src))
	if err != nil {
		fmt.Fprintf(os.Stderr, "lex error: %s\n", err)
		os.Exit(1)
	}

	file, err := parser.Parse(tokens)
	if err != nil {
		fmt.Fprintf(os.Stderr, "parse error: %s\n", err)
		os.Exit(1)
	}

	// Sema pass 1 — collect symbols (includes / libraries resolved here).
	syms := sema.Collect(file)

	// TODO: load files from syms.Includes and syms.Libraries and re-Collect.
	// For now, proceed with a single file and no library.

	// Sema pass 2 — validate.
	diags := syms.Check(file)
	hasError := false
	for _, d := range diags {
		fmt.Fprintf(os.Stderr, "%s:%d: %s: %s\n", os.Args[1], d.Line, d.Code, d.Message)
		if d.Severity == sema.Error {
			hasError = true
		}
	}
	if hasError {
		os.Exit(1)
	}

	// Step 4 — World tree construction.
	w := world.Build([]*ast.File{file}, nil)
	printWorldSummary(w)
}

func printWorldSummary(w *world.World) {
	if w.Game.Title != "" {
		fmt.Printf("game    %q by %s", w.Game.Title, w.Game.Author)
		if w.Game.Version != "" {
			fmt.Printf(" version %s", w.Game.Version)
		}
		fmt.Println()
	}

	fmt.Printf("kinds   %d\n", len(w.Kinds))
	fmt.Printf("classes %d\n", len(w.Classes))
	fmt.Printf("nodes   %d\n", len(w.NodeMap))
	fmt.Printf("vocab   %d terms\n", len(w.Vocab))

	fmt.Printf("root handlers       %d\n", len(w.Root.Handlers))
	fmt.Printf("root every-turn     %d\n", len(w.Root.EveryTurn))
	fmt.Printf("root turn-ranges    %d\n", len(w.Root.TurnRanges))

	if len(w.Root.Children) > 0 {
		fmt.Println("top-level nodes:")
		for _, n := range w.Root.Children {
			fmt.Printf("  %-10s %s\n", n.ClassName, n.Name)
		}
	}
}

func sigStr(sig []ast.SigPart) string {
	s := ""
	for _, part := range sig {
		switch p := part.(type) {
		case ast.SigKeyword:
			s += p.Word + " "
		case ast.SigParam:
			s += p.Type + ":" + p.Name + " "
		}
	}
	return s
}
