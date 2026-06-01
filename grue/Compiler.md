# Grue — Compiler Pipeline

Source to self-contained HTML in seven steps.
Implementation language: Go. No external parser tools — hand-written throughout.

---

## The Two Parsers

The pipeline contains two distinct parsers with different natures:

**Source parser** — recursive descent. Reads `.grue` files and produces the
world tree. The grammar is indentation-sensitive but not deeply ambiguous.

**Player input parser** — a pattern trie constructed at compile time from the
game's own handler signatures, against a vocabulary of multi-word object names
that varies per game. Dynamic by nature — no parser generator can produce this.

---

## Step 1 — Lex

Source text → token stream.

Tokens: `WORD`, `STRING`, `NUMBER`, `INDENT`, `DEDENT`, `OPERATOR`.

Key responsibilities:
- **Indentation stack** — emits `INDENT`/`DEDENT` tokens for block structure.
  Python-style: indent level tracked as a stack of column numbers.
- **String mode** — switches on `"`, handles:
  - Multi-line collapsing: `\n\s+` → single space
  - `{...}` interpolation regions
  - `[...]` directive regions (`[nobreak]`, `[comma]`, `[the]`, etc.)
- **Comments** — `#` to end of line, discarded.
- **Test dot** — `.` at end of a test command line, context-sensitive.

Multi-word identifiers (`brass lantern`, `iron door`) are not resolved here.
The lexer emits individual `WORD` tokens; the parser groups them.

---

## Step 2 — Parse

Token stream → AST.

Hand-written recursive descent. Key responsibilities:
- **Multi-word identifier grouping** — parser resolves where names begin and end
  using handler signature patterns and declaration context.
- **Handler signatures** — parsed as alternating keywords and `type:name`
  parameter pairs.
- **Expression trees** — arithmetic, conditions, string interpolation.
- **Indentation blocks** — `INDENT`/`DEDENT` tokens define block boundaries.
- **Include resolution** — `include "chapter_2"` files are lexed, parsed, and
  merged into the AST. Each handler signature may appear only once.
- **Library loading** — `library "standard"` files are loaded and marked as
  library-level in the handler chain.

---

## Step 3 — Semantic Analysis

AST → validated, resolved AST.

- Kind value uniqueness — no two kinds share a value name globally.
- Class inheritance — resolves `extends`, validates no cycles.
- Handler signature uniqueness — duplicate signatures in own code are errors.
- Identifier token cross-references — `fail out_of_bounds` / `when out_of_bounds:`
  arms are matched; mismatches are warnings.
- Class name validation — `cube.location.class is Robot` checks `Robot` exists.
- Type inference — `unset` property declarations are typed on first assignment.
- Default kind values — `*` markers resolved; first value used if absent.

---

## Step 4 — World Tree Construction

Builds the runtime world tree from the resolved AST.

- Places all rooms, objects, classes, styles, handlers into the tree.
- Resolves nested declarations — source hierarchy IS the world hierarchy.
- Builds the handler chain for every signature:
  `object → class → parent class → global → library`
- Registers object names, aliases, and synonyms into the vocabulary.

---

## Step 5 — Grammar Construction

Builds the player input parser from all public handler signatures.

Each `on` handler signature becomes a pattern in the trie:
```
on open Ledger:ledger at number:page:
```
→ matches player input `open rolodex at 3`, resolving `rolodex` as a Ledger
instance from the vocabulary and `3` as a number.

`internal` handlers are excluded. The resulting trie is the complete grammar
of valid player commands for this game — derived entirely from the source,
with no separate verb table.

---

## Step 6 — Code Generation

Emits JavaScript:

- World state as JS objects mirroring the world tree.
- Handler chains as JS functions, ordered by specificity.
- Compiled player input grammar (the pattern trie from step 5).
- Style definitions compiled to CSS class declarations.
- `js { }` blocks embedded verbatim.

---

## Step 7 — HTML Bundling

Produces a single self-contained `.html` file:

- Inlines the JS runtime (standard library, game loop, output pipeline).
- Inlines the compiled game JS from step 6.
- Inlines the CSS from style definitions.
- No external dependencies — the file runs anywhere.

---

## Test Runner

A separate compiler mode. Driven by the default `test` block.

- Compiles the game normally.
- Simulates player input turn by turn.
- Captures text output per turn.
- Evaluates assertions:
  - `command. "text"` — output contains text
  - `command. not "text"` — output does not contain text
  - `test "name".` — runs named test, passes if it passes
- Reports pass/fail per test block with output diffs on failure.
- Scoped tests (`Room archive "..." test "local"`) start the player in that room.
