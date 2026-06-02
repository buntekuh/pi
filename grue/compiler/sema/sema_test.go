package sema_test

import (
	"bufio"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"

	"gruc/lexer"
	"gruc/parser"
	"gruc/sema"
)

// expectation is parsed from a "# expect: severity code line N" header comment.
type expectation struct {
	severity sema.Severity
	code     string
	line     int
}

// parseExpectations reads all "# expect:" lines from a .grue fixture file.
// Format: # expect: error kind_value_conflict line 7
func parseExpectations(path string) ([]expectation, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()

	var out []expectation
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if !strings.HasPrefix(line, "# expect:") {
			break // expectations are only at the top of the file
		}
		rest := strings.TrimSpace(strings.TrimPrefix(line, "# expect:"))
		parts := strings.Fields(rest)
		if len(parts) < 2 {
			return nil, fmt.Errorf("%s: malformed expect line: %q", path, line)
		}
		e := expectation{severity: sema.Severity(parts[0]), code: parts[1]}
		if len(parts) == 4 && parts[2] == "line" {
			n, err := strconv.Atoi(parts[3])
			if err != nil {
				return nil, fmt.Errorf("%s: bad line number in %q", path, line)
			}
			e.line = n
		}
		out = append(out, e)
	}
	return out, scanner.Err()
}

func runFixtures(t *testing.T, pattern string) {
	t.Helper()
	files, err := filepath.Glob(pattern)
	if err != nil {
		t.Fatal(err)
	}
	if len(files) == 0 {
		t.Fatalf("no fixture files matched %s", pattern)
	}

	for _, path := range files {
		t.Run(filepath.Base(path), func(t *testing.T) {
			expectations, err := parseExpectations(path)
			if err != nil {
				t.Fatal(err)
			}
			if len(expectations) == 0 {
				t.Fatalf("no # expect: lines found in %s", path)
			}

			src, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			tokens, err := lexer.Tokenize(string(src))
			if err != nil {
				t.Fatalf("lex error: %s", err)
			}
			file, err := parser.Parse(tokens)
			if err != nil {
				t.Fatalf("parse error: %s", err)
			}

			diags := sema.Analyse(file)

			for _, exp := range expectations {
				found := false
				for _, d := range diags {
					lineMatch := exp.line == 0 || d.Line == exp.line
					if d.Severity == exp.severity && d.Code == exp.code && lineMatch {
						found = true
						break
					}
				}
				if !found {
					t.Errorf("expected %s %q (line %d) — got %v",
						exp.severity, exp.code, exp.line, diags)
				}
			}
		})
	}
}

func TestSemaErrors(t *testing.T) {
	runFixtures(t, filepath.Join("..", "..", "tests", "sema", "errors", "*.grue"))
}

func TestSemaWarnings(t *testing.T) {
	runFixtures(t, filepath.Join("..", "..", "tests", "sema", "warnings", "*.grue"))
}

// TestSemaClean verifies that files in tests/sema/clean/ produce zero diagnostics.
func TestSemaClean(t *testing.T) {
	files, err := filepath.Glob(filepath.Join("..", "..", "tests", "sema", "clean", "*.grue"))
	if err != nil {
		t.Fatal(err)
	}
	if len(files) == 0 {
		t.Fatal("no clean fixture files found")
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
			file, err := parser.Parse(tokens)
			if err != nil {
				t.Fatalf("parse error: %s", err)
			}
			if diags := sema.Analyse(file); len(diags) > 0 {
				t.Errorf("expected zero diagnostics, got %v", diags)
			}
		})
	}
}
