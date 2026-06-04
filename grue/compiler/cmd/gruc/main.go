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
	"path/filepath"
	"strings"
)

func main() {
	outFlag  := flag.String("o", "", "write HTML output to file (default: stdout)")
	libFlag  := flag.String("L", "", "library directory (default: <game-dir>/../library)")
	treeFlag := flag.Bool("tree", false, "print world tree and exit, do not emit HTML")
	flag.Usage = func() {
		fmt.Fprintln(os.Stderr, "usage: gruc [-o output.html] [-L libdir] [-tree] <file.grue>")
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

	// Step 3a — Collect symbols to discover library imports.
	syms := sema.Collect(file)

	libDir := *libFlag
	if libDir == "" {
		libDir = filepath.Join(filepath.Dir(args[0]), "..", "library")
	}

	ownFiles := []*ast.File{file}
	var libFiles []*ast.File
	for _, name := range syms.Libraries {
		path := filepath.Join(libDir, name+".grue")
		lsrc, err := os.ReadFile(path)
		if err != nil {
			fmt.Fprintf(os.Stderr, "library %q: %v\n", name, err)
			os.Exit(1)
		}
		ltokens, err := lexer.Tokenize(string(lsrc))
		if err != nil {
			fmt.Fprintf(os.Stderr, "library %q: lex: %v\n", name, err)
			os.Exit(1)
		}
		lfile, err := parser.Parse(ltokens)
		if err != nil {
			fmt.Fprintf(os.Stderr, "library %q: parse: %v\n", name, err)
			os.Exit(1)
		}
		libFiles = append(libFiles, lfile)
	}

	// Step 3b — Re-collect with all files, then validate.
	allFiles := append(ownFiles, libFiles...)
	syms = sema.Collect(allFiles...)
	diags := syms.Check(allFiles...)
	hasError := false
	for _, d := range diags {
		if d.Severity == sema.Error {
			hasError = true
		}
		fmt.Fprintf(os.Stderr, "%s:%d: %s: %s\n", args[0], d.Line, d.Code, d.Message)
	}
	if hasError {
		os.Exit(1)
	}

	// Step 4 — World tree
	w := world.Build(ownFiles, libFiles)

	if *treeFlag {
		out := treeHTML(w)
		if *outFlag != "" {
			if err := os.WriteFile(*outFlag, []byte(out), 0o644); err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
		} else {
			fmt.Print(out)
		}
		return
	}

	// Step 5 — Grammar
	g := grammar.Build(w)

	// Step 6 — Code generation + HTML assembly
	out := codegen.HTML(w, g)

	if *outFlag != "" {
		if err := os.WriteFile(*outFlag, []byte(out), 0o644); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
	} else {
		fmt.Print(out)
	}
}

// ── World tree HTML ────────────────────────────────────────────────────────

func treeHTML(w *world.World) string {
	var b strings.Builder

	title := w.Game.Title
	if title == "" {
		title = "World Tree"
	}

	b.WriteString(`<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>` + he(title) + ` — world tree</title>
<style>
  body  { font-family: monospace; font-size: 13px; padding: 1em 2em; color: #111; }
  h1    { font-size: 1.1em; margin-bottom: 0.2em; }
  h2    { font-size: 1em; border-bottom: 1px solid #ccc; margin-top: 1.4em; margin-bottom: 0.4em; color: #444; }
  table { border-collapse: collapse; width: 100%; margin-bottom: 0.6em; }
  td    { padding: 1px 10px 1px 0; vertical-align: top; white-space: nowrap; }
  td.desc { white-space: normal; color: #666; font-style: italic; }
  .cls  { color: #06c; }
  .name { font-weight: bold; }
  .alias { color: #888; font-size: 0.9em; }
  .handler { color: #080; }
  .internal { color: #a60; }
  .turn { color: #06c; }
  .prop { color: #666; }
  .lib  { color: #aaa; font-size: 0.85em; }
  .default { text-decoration: underline; }
  .indent1 { padding-left: 1.5em; }
  .indent2 { padding-left: 3em; }
  .indent3 { padding-left: 4.5em; }
</style>
</head>
<body>
`)

	// Header
	if w.Game.Title != "" {
		b.WriteString(`<h1>"` + he(w.Game.Title) + `" by ` + he(w.Game.Author))
		if w.Game.Version != "" {
			b.WriteString(" &mdash; " + he(w.Game.Version))
		}
		b.WriteString("</h1>\n")
	}

	// Kinds
	if len(w.Kinds) > 0 {
		b.WriteString("<h2>Kinds</h2><table>\n")
		for _, k := range w.Kinds {
			b.WriteString("<tr><td class='name'>" + he(k.Name) + "</td><td>")
			for i, v := range k.Values {
				if i > 0 {
					b.WriteString(" &nbsp; ")
				}
				if i == k.DefaultIdx {
					b.WriteString("<span class='default'>" + he(v) + "</span>")
				} else {
					b.WriteString(he(v))
				}
			}
			b.WriteString("</td></tr>\n")
		}
		b.WriteString("</table>\n")
	}

	// Classes
	if len(w.Classes) > 0 {
		b.WriteString("<h2>Classes</h2><table>\n")
		for _, cls := range w.Classes {
			lib := ""
			if cls.IsLibrary {
				lib = " <span class='lib'>[lib]</span>"
			}
			parent := ""
			if cls.Parent != "" {
				parent = " <span class='cls'>extends " + he(cls.Parent) + "</span>"
			}
			b.WriteString("<tr><td class='name'>" + he(cls.Name) + parent + lib + "</td><td>")
			var parts []string
			for _, p := range cls.Props {
				parts = append(parts, "<span class='prop'>"+he(p.Key)+"</span>")
			}
			for _, h := range cls.Handlers {
				cls2 := "handler"
				if h.Internal {
					cls2 = "internal"
				}
				parts = append(parts, "<span class='"+cls2+"'>"+he(h.SigKey)+"</span>")
			}
			if len(cls.EveryTurn) > 0 {
				parts = append(parts, "<span class='turn'>(every turn)</span>")
			}
			for _, child := range cls.Children {
				parts = append(parts, "<span class='cls'>child "+he(child.ClassName)+" "+he(child.Name)+"</span>")
			}
			b.WriteString(strings.Join(parts, " &nbsp;&bull;&nbsp; "))
			b.WriteString("</td></tr>\n")
		}
		b.WriteString("</table>\n")
	}

	// World node tree
	b.WriteString("<h2>World</h2><table>\n")
	for _, child := range w.Root.Children {
		writeNodeHTML(&b, child, 0)
	}
	b.WriteString("</table>\n")

	// Global handlers
	var ownH, libH []*world.Handler
	for _, h := range w.Root.Handlers {
		if h.IsLibrary {
			libH = append(libH, h)
		} else {
			ownH = append(ownH, h)
		}
	}
	if len(ownH) > 0 || len(w.Root.EveryTurn) > 0 || len(w.Root.TurnRanges) > 0 {
		b.WriteString("<h2>Global handlers</h2><table>\n")
		for _, h := range ownH {
			cls := "handler"
			if h.Internal {
				cls = "internal"
			}
			b.WriteString("<tr><td class='" + cls + "'>" + he(h.SigKey) + "</td></tr>\n")
		}
		for range w.Root.EveryTurn {
			b.WriteString("<tr><td class='turn'>(every turn)</td></tr>\n")
		}
		for _, tr := range w.Root.TurnRanges {
			b.WriteString("<tr><td class='turn'>" + turnLabel(tr.From, tr.To) + "</td></tr>\n")
		}
		b.WriteString("</table>\n")
	}
	if len(libH) > 0 {
		b.WriteString("<h2>Library handlers</h2><table>\n")
		for _, h := range libH {
			cls := "handler"
			if h.Internal {
				cls = "internal"
			}
			b.WriteString("<tr><td class='" + cls + "'>" + he(h.SigKey) + "</td></tr>\n")
		}
		b.WriteString("</table>\n")
	}

	// Footer
	fmt.Fprintf(&b, "<p class='lib'>%d vocab terms &nbsp;&bull;&nbsp; %d nodes</p>\n",
		len(w.Vocab), len(w.NodeMap))
	b.WriteString("</body></html>\n")
	return b.String()
}

func writeNodeHTML(b *strings.Builder, node *world.Node, depth int) {
	indentClass := ""
	if depth > 0 {
		indentClass = fmt.Sprintf(" class='indent%d'", min(depth, 3))
	}
	lib := ""
	if node.IsLibrary {
		lib = " <span class='lib'>[lib]</span>"
	}
	aliases := ""
	if len(node.Aliases) > 0 {
		aliases = " <span class='alias'>(" + he(strings.Join(node.Aliases, ", ")) + ")</span>"
	}
	desc := ""
	if node.Desc != "" {
		d := strings.ReplaceAll(node.Desc, "\n", " ")
		if len(d) > 60 {
			d = d[:60] + "…"
		}
		desc = he(d)
	}

	fmt.Fprintf(b, "<tr><td%s><span class='cls'>%s</span></td><td class='name'>%s%s%s</td><td class='desc'>%s</td>",
		indentClass, he(node.ClassName), he(node.Name), aliases, lib, desc)

	// Inline handlers as coloured pills
	var pills []string
	for _, h := range node.Handlers {
		cls := "handler"
		if h.Internal {
			cls = "internal"
		}
		pills = append(pills, "<span class='"+cls+"'>"+he(h.SigKey)+"</span>")
	}
	for range node.EveryTurn {
		pills = append(pills, "<span class='turn'>(every turn)</span>")
	}
	for _, tr := range node.TurnRanges {
		pills = append(pills, "<span class='turn'>"+turnLabel(tr.From, tr.To)+"</span>")
	}
	b.WriteString("<td>" + strings.Join(pills, " ") + "</td></tr>\n")

	for _, child := range node.Children {
		writeNodeHTML(b, child, depth+1)
	}
}

// he HTML-escapes a string for safe insertion into HTML.
func he(s string) string {
	s = strings.ReplaceAll(s, "&", "&amp;")
	s = strings.ReplaceAll(s, "<", "&lt;")
	s = strings.ReplaceAll(s, ">", "&gt;")
	s = strings.ReplaceAll(s, `"`, "&quot;")
	return s
}

func turnLabel(from, to int) string {
	if to < 0 {
		return fmt.Sprintf("turn %d-", from)
	}
	if from == to {
		return fmt.Sprintf("turn %d", from)
	}
	return fmt.Sprintf("turn %d-%d", from, to)
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
