# Codegen Issues

---

## Cross-kind comparisons are not caught by sema — [sema.go](compiler/sema/sema.go)

Kind values are typed enumerations with an integer backing, ordered within their
kind. Comparing values from two different kinds is a type error — `dry < hungry`
is meaningless even though both resolve to integers internally — but sema does
not detect it.

The fixture that proves this is missing lives at
[tests/sema/kind_comparison_mismatch.grue](tests/sema/kind_comparison_mismatch.grue)
(moved out of `errors/` to keep the suite green).

### What needs to happen

To catch this, sema pass 2 needs to infer the kind type of each side of a
`<` / `>` / `<=` / `>=` / `==` / `is` / `isnt` comparison:

- A bare kind-value name (e.g. `wet`) has the kind it was declared in
  (`wetness`), which is already known from `kindValues`.
- A property access `obj.prop` has the kind of `prop` as declared on
  `obj`'s class — this requires resolving the property type through the
  class hierarchy, which sema does not yet do.

Both sides must resolve to the same kind. If either side is not a kind value
(it is a numeric expression) no kind check applies.

### Error to emit

`kind_comparison_mismatch` — "cannot compare values of kind %q and kind %q"

---

## Kind values in handler body expressions are not validated by sema — [sema.go](compiler/sema/sema.go)

`checkKindUseRefs` only walks `KindUseDecl` nodes — the `is X` form in instance
and class declaration bodies. It never enters handler bodies. `checkClassRefsInExpr`
does walk handler bodies for `is`/`isnt`, but calls `checkClassRef`, which skips
all lowercase names. Kind values are always lowercase, so they fall through
entirely.

The result: an undeclared kind value used in a handler condition passes sema
without complaint:

```
kind mood: *neutral, happy, sad

Object peter "A man."

on examine Object:peter:
    if peter is cheerful:    # cheerful not declared — sema silent
        say "He's cheerful."
```

At runtime this silently misbehaves — the kind lookup finds nothing and the
condition evaluates incorrectly.

### What needs to happen

Extend `checkClassRefsInExpr` to validate the right-hand side of `is`/`isnt`
when it is a lowercase `NameExpr`: look it up in `kindValues` and `kindNames`,
and emit `unknown_kind_value` if it is not found. This is the same check
`checkKindUseValue` already performs for declaration bodies — it just needs to
be applied in the expression walker too.

### Error to emit

`unknown_kind_value` — reuse the existing code, same message.

---

## `World` does not expose a kind-value → kind-name lookup — [world.go](compiler/world/world.go)

The world builder maintains a private `b.kindOf map[string]string` (kind value
name → kind name, e.g. `"sad" → "mood"`) but does not expose it on the `World`
struct. The codegen needs this map to classify bare `NameExpr` tokens — deciding
whether `sad` in an expression is a kind value (compile to an integer index) or a
world property lookup (compile to `_get("sad")`).

Without it, codegen must rebuild the same map by walking `w.Kinds` at the start
of every compilation. That works but is redundant and easy to forget.

### Fix

Add a `KindOf map[string]string` field to `World` and populate it in
`pass1Kinds` alongside the existing `b.kindOf` assignment:

```go
type World struct {
    ...
    KindOf map[string]string // kind value name → kind name; excludes true/false
}
```

```go
b.w.KindOf[v] = d.Name   // alongside b.kindOf[v] = d.Name
```

---

## `writeExits` drops custom exits — [codegen.go:338–359](compiler/codegen/codegen.go)

`writeExits` only emits the eight compass directions plus `up`/`down`/`in`/`out`. Any room exit with a custom multi-word direction — `top of ladder`, `manhole`, `port`, `airlock` — is silently dropped from the compiled node descriptor.

This means custom exits are **dead in the runtime**: they cannot be navigated, they do not appear in the map panel, and they are invisible to any code that reads `node.exits`. It is not a missing feature — it is a correctness bug. A game that compiles without errors may behave completely differently at runtime depending on whether its exits happen to be compass directions.

### Fix

Remove the `compassDirs` guard in `writeExits`. Emit every Room-valued property as an exit, regardless of key name:

```go
func writeExits(b *strings.Builder, node *world.Node) {
    if node.ClassName != "Room" {
        return
    }
    var parts []string
    for _, prop := range node.Props {
        if ref, ok := prop.Value.(world.RefValue); ok {
            dest := ref.Name
            // emit if destination is a Room or a Door
            parts = append(parts, fmt.Sprintf("%s: %s", jsStr(prop.Key), jsStr(dest)))
        }
    }
    if len(parts) > 0 {
        fmt.Fprintf(b, ", exits: {%s}", strings.Join(parts, ", "))
    }
}
```

The destination-class check (`Room` or `Door`) can be added if needed to exclude non-navigation Room-valued properties, but the primary fix is lifting the compass whitelist.

### Impact

- Movement test `movement.grue` uses `top of ladder`, `bottom of ladder`, `manhole` — none of these work in the compiled output today
- BFS pathfinding (see `future features.md`) requires all exits to be present
- Map panel in the tree inspector shows an incomplete picture of the world
