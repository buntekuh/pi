package main

import (
	"fmt"
	"gruc/ast"
	"gruc/lexer"
	"gruc/parser"
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

	printSummary(file)
}

func printSummary(file *ast.File) {
	fmt.Printf("%d top-level declarations:\n", len(file.Decls))
	for _, decl := range file.Decls {
		switch d := decl.(type) {
		case *ast.GameDecl:
			fmt.Printf("  game    %q by %s\n", d.Title, d.Author)
		case *ast.LibraryImport:
			fmt.Printf("  library %q\n", d.Path)
		case *ast.IncludeDecl:
			fmt.Printf("  include %q\n", d.Path)
		case *ast.KindDecl:
			fmt.Printf("  kind    %s: %v\n", d.Name, d.Values)
		case *ast.VarDecl:
			fmt.Printf("  var     %s\n", d.Name)
		case *ast.ClassDecl:
			fmt.Printf("  class   %s (%d body items)\n", d.Name, len(d.Body))
		case *ast.InstanceDecl:
			fmt.Printf("  %-7s %s\n", d.ClassName, d.Name)
case *ast.TurnHandlerDecl:
			if d.To == -1 {
				fmt.Printf("  turn    %d-\n", d.From)
			} else if d.From == d.To {
				fmt.Printf("  turn    %d\n", d.From)
			} else {
				fmt.Printf("  turn    %d-%d\n", d.From, d.To)
			}
		case *ast.InterfaceHandlerDecl:
			fmt.Printf("  iface   %s\n", sigStr(d.Signature))
		case *ast.HandlerDecl:
			if d.EveryTurn {
				fmt.Printf("  handler on every turn\n")
			} else {
				fmt.Printf("  handler %s\n", sigStr(d.Signature))
			}
		case *ast.TestDecl:
			if d.Name == "" {
				fmt.Printf("  test    (default)\n")
			} else {
				fmt.Printf("  test    %q\n", d.Name)
			}
		default:
			fmt.Printf("  %T\n", d)
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
