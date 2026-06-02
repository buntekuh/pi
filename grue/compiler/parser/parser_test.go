package parser_test

import (
	"os"
	"path/filepath"
	"testing"

	"gruc/lexer"
	"gruc/parser"
)

// TestValidFiles verifies that every .grue file in tests/ parses without error.
func TestValidFiles(t *testing.T) {
	files, err := filepath.Glob(filepath.Join("..", "..", "tests", "*.grue"))
	if err != nil {
		t.Fatal(err)
	}
	if len(files) == 0 {
		t.Fatal("no test files found")
	}
	for _, path := range files {
		t.Run(filepath.Base(path), func(t *testing.T) {
			src, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			tokens, err := lexer.Tokenize(string(src))
			if err != nil {
				t.Fatalf("lex error: %s", err)
			}
			if _, err := parser.Parse(tokens); err != nil {
				t.Fatalf("parse error: %s", err)
			}
		})
	}
}
