# Grue Compiler — Pipeline

The compiler transforms one or more `.grue` source files into a self-contained
HTML file containing the JavaScript runtime and the serialised world tree.

---

## Step 1 — Lexical Analysis

Source text → token stream.

- Normalises line endings.
- Emits synthetic `INDENT` / `DEDENT` tokens so the parser sees explicit block
  boundaries rather than raw indentation counts.
- Keywords are plain `WORD` tokens — the parser distinguishes them by context.
- **Package:** `gruc/lexer`

---

## Step 2 — Parsing

Token stream → AST (`*ast.File`).

- Recursive descent, context-driven.
- Produces one `*ast.File` per source file. Included files are parsed
  separately and passed to sema as a slice.
- **Package:** `gruc/parser`

---

## Step 3 — Sema Pass 1: Declaration Collection

AST slice → populated symbol tables.

Walks every file in declaration order and collects:

- All **kind** names and their values (global uniqueness enforced here).
- All **class** names, parent names, and declaration order (needed for
  deterministic cycle detection in Pass 2).
- All **instance** names and their effective class (`is ClassName` in an
  instance body overrides the declared class).
- All **handler** signatures with their owning class (for argument type
  checking in Pass 2).
- All **include** and **library** directives, so the driver can load
  additional files before Pass 2 runs.

No errors are emitted in Pass 1 — it is a pure collection pass.

- **Package:** `gruc/sema`

---

## Step 4 — Sema Pass 2: Reference Resolution

Symbol tables → validated, resolved AST.

Using the symbol tables built in Pass 1, checks:

- **Kind value uniqueness** — no two kinds share a value name globally.
- **Kind redeclaration** — a kind name may only be declared once.
- **Kind value references** — `is lockable` in an instance body must name a
  declared kind value (lowercase) or a class (capitalised).
- **Inheritance** — resolves `extends`, validates no cycles, validates all
  parent class names exist.
- **Handler signature uniqueness** — duplicate signatures in the same scope
  are errors.
- **Class name validation** — class names in signatures, `is`/`isnt`
  expressions, and `filter()` calls must be declared.
- **Property value name resolution** — NameExpr values in property
  declarations must resolve to a known instance, room, kind value, or kind
  name. Unresolved names are errors.
- **Argument type checking** — instances passed to handlers must be compatible
  with the declared parameter type (including subclass matching).
- **Identifier token cross-references** — `fail token` / `succeed token`
  identifiers are matched against `when` arm labels; mismatches are warnings.

Errors prevent further compilation. Warnings are reported but do not stop the
pipeline.

- **Package:** `gruc/sema`

---

## Step 5 — World Tree Construction

Validated AST → runtime world tree (Go IR).

- Places all rooms, objects, classes, styles, and handlers into the tree.
- Resolves the source hierarchy into the world hierarchy.
- Builds the handler chain for every signature:
  `object → class → parent class → global → library`
- Registers instance names, aliases, and synonyms into the vocabulary.
- **Package:** `gruc/world` *(not yet implemented)*

---

## Step 6 — Code Generation

World tree → self-contained HTML file.

- Serialises the world tree to JavaScript.
- Embeds the JavaScript runtime.
- Bundles any referenced assets (`.spans`, audio, images) as base64.
- Produces a single `.html` file that runs in any browser with no server.
- **Package:** `gruc/codegen` *(not yet implemented)*

---

## Multi-file support

`include "chapter_2"` merges another `.grue` file's declarations into the same
namespace. `library "standard"` adds library handlers at the bottom of every
handler chain.

The driver resolves includes recursively before sema runs. Both passes receive
the full slice of ASTs. Library files are processed last so own-code handlers
always take precedence.

---

## Implementation status

| Step | Package | Status |
|------|---------|--------|
| Lexer | `gruc/lexer` | Complete |
| Parser | `gruc/parser` | Complete |
| Sema Pass 1 | `gruc/sema` | Partially complete — kinds, classes, instances, handlers collected; include/library resolution pending |
| Sema Pass 2 | `gruc/sema` | Partially complete — kind checks, inheritance, duplicate handlers, unknown classes, token cross-refs, argument types done; property value name resolution and kind value reference checks pending |
| World Tree | `gruc/world` | Not started |
| Code Generation | `gruc/codegen` | Not started |
