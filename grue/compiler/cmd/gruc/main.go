package main

import (
	"flag"
	"fmt"
	"gruc/ast"
	"gruc/codegen"
	"gruc/grammar"
	"gruc/lexer"
	"gruc/parser"
	"gruc/sema"
	"gruc/world"
	"os"
)

func main() {
	outFlag := flag.String("o", "", "write HTML output to file (default: stdout)")
	flag.Usage = func() {
		fmt.Fprintln(os.Stderr, "usage: gruc [-o output.html] <file.grue>")
		flag.PrintDefaults()
	}
	flag.Parse()

	args := flag.Args()
	if len(args) < 1 {
		flag.Usage()
		os.Exit(1)
	}

	src, err := os.ReadFile(args[0])
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}

	// Step 1 — Lex
	tokens, err := lexer.Tokenize(string(src))
	if err != nil {
		fmt.Fprintf(os.Stderr, "lex error: %s\n", err)
		os.Exit(1)
	}

	// Step 2 — Parse
	file, err := parser.Parse(tokens)
	if err != nil {
		fmt.Fprintf(os.Stderr, "parse error: %s\n", err)
		os.Exit(1)
	}

	// Step 3 — Semantic analysis
	// TODO: resolve includes and library imports before Collect/Check.
	syms := sema.Collect(file)
	diags := syms.Check(file)
	hasError := false
	for _, d := range diags {
		fmt.Fprintf(os.Stderr, "%s:%d: %s: %s\n", args[0], d.Line, d.Code, d.Message)
		if d.Severity == sema.Error {
			hasError = true
		}
	}
	if hasError {
		os.Exit(1)
	}

	// Step 4 — World tree
	w := world.Build([]*ast.File{file}, nil)

	// Step 5 — Grammar
	g := grammar.Build(w)

	// Step 6 — Code generation + HTML assembly
	out := codegen.HTML(w, g)

	// Write output
	if *outFlag != "" {
		if err := os.WriteFile(*outFlag, []byte(out), 0o644); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
	} else {
		fmt.Print(out)
	}
}
