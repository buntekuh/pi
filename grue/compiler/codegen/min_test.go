package codegen_test

import (
	"strings"
	"testing"
	"gruc/ast"
	"gruc/codegen"
	"gruc/grammar"
	"gruc/lexer"
	"gruc/parser"
	"gruc/sema"
	"gruc/world"
)

func compileWithSema(t *testing.T, src string) string {
	t.Helper()
	tokens, err := lexer.Tokenize(src)
	if err != nil { t.Fatal(err) }
	file, err := parser.Parse(tokens)
	if err != nil { t.Fatal(err) }
	syms := sema.Collect(file)
	_ = syms.Check(file)
	w := world.Build([]*ast.File{file}, nil)
	g := grammar.Build(w)
	return codegen.Emit(w, g)
}

// TestCompileIsKindProp: `opened is open` inside a class handler must compile
// as R._prop(self,"opened") === "open", not double-wrapped.
func TestCompileIsKindProp(t *testing.T) {
	out := compileWithSema(t, `
class Ledger
    kind opened: *closed, open

    on record string:entry in self:
        say "not open" unless opened is open
        say "open"
`)
	idx := strings.Index(out, `"record string in Ledger": [`)
	if idx < 0 {
		t.Fatal("record chain not found")
	}
	end := strings.Index(out[idx:], "],\n")
	chain := out[idx : idx+end+3]

	if strings.Contains(chain, `_prop(R._prop`) {
		t.Errorf("double-wrapped kind check:\n%s", chain)
	}
	if !strings.Contains(chain, `_prop(self, "opened") === "open"`) {
		t.Errorf("expected R._prop(self,\"opened\") === \"open\" in chain:\n%s", chain)
	}
}
