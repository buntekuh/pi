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

## `writeExits` drops custom exits — [codegen.go](compiler/codegen/codegen.go)

`writeExits` only emits the twelve compass directions plus `up`/`down`/`in`/`out`.
Any room exit with a custom direction — `top of ladder`, `manhole`, `port`,
`airlock` — is silently dropped from the compiled node descriptor.

This means custom exits are **dead in the runtime**: they cannot be navigated,
they do not appear in the map panel, and they are invisible to any code that reads
`node.exits`. It is not a missing feature — it is a correctness bug.

### Fix

Remove the `compassDirs` guard in `writeExits`. Emit every `RefValue`-typed
property on a Room node as an exit, regardless of key name:

```go
func writeExits(b *strings.Builder, node *world.Node) {
    if node.ClassName != "Room" {
        return
    }
    var parts []string
    for _, prop := range node.Props {
        if ref, ok := prop.Value.(world.RefValue); ok {
            parts = append(parts, fmt.Sprintf("%s: %s", jsStr(prop.Key), jsStr(ref.Name)))
        }
    }
    if len(parts) > 0 {
        fmt.Fprintf(b, ", exits: {%s}", strings.Join(parts, ", "))
    }
}
```

### Impact

- Movement test `movement.grue` uses `top of ladder`, `bottom of ladder`, `manhole` — none of these work in the compiled output today
- BFS pathfinding requires all exits to be present
- Map panel in the tree inspector shows an incomplete picture of the world

---

## `on examine self:` at global scope produces malformed sigKey — [world/build.go](compiler/world/build.go) + [sema.go](compiler/sema/sema.go)

`self` as a parameter type is valid inside class and instance bodies, where it
resolves to the owning class name. At global scope there is no owning class, so
`ownerClass` is `""` and `sigKey()` produces a key with an empty component —
`"examine "` rather than `"examine Object"`.

The handler is then registered under `"examine "` and the grammar trie also emits
`sigKey: "examine "`. Neither the handler map nor the grammar can ever match a
player command — the handler is permanently unreachable.

Sema does not check that `self` is only used inside a class or instance body.

### Fix

Add a sema error: `self` as a parameter type is only valid inside a `class` or
instance body. Emit `reserved_name` or a dedicated `self_outside_class` error at
global scope.

---

## `compileIs` calls `_prop()` when left side is a kind value, not a node — [codegen.go](compiler/codegen/codegen.go)

When the right side of `is` is a kind value, `compileIs` checks whether the left
side is syntactically a bare `NameExpr`. If so, it wraps it in
`R._prop(left, kindName)` on the assumption that the left side is a node
reference. But the left side might itself be a kind value name, in which case
`_prop()` is wrong.

```grue
kind mood: *happy, sad

if happy is happy:   # compiles to R._prop("happy", "mood") === "happy"
                     # _prop("happy", ...) returns null — the string "happy" is not a node
```

In practice this arises when a kind value is passed as an argument and then
compared — less likely than comparing a node, but valid Grue.

### Fix

In `compileIs`, before wrapping in `_prop()`, check whether the left `NameExpr`
is itself a kind value (present in `c.kof`) or a local variable. If so, compile
it as a plain string literal comparison rather than a property lookup:

```go
if kindName, ok := c.kof[right.Name]; ok {
    left := c.compileExpr(e.Left, sc)
    if nameExpr, leftIsName := e.Left.(*ast.NameExpr); leftIsName {
        if _, leftIsKind := c.kof[nameExpr.Name]; !leftIsKind && !sc.vars[nameExpr.Name] {
            return fmt.Sprintf("(%s_prop(%s, %s) === %s)", rt, left, jsStr(kindName), jsStr(right.Name))
        }
    }
    return fmt.Sprintf("(%s === %s)", left, jsStr(right.Name))
}
```

---

## Bare `.` tick steps in test runner are silently skipped — [runtime.js](compiler/codegen/runtime.js)

A bare `.` in a test block compiles to `{ tick: true, assert: "...", negate: false }`.
The test runner handles `step.exprFn` and `step.cmd` but has no branch for
`step.tick` — it falls through with no `executeTurn` call, producing no output.
Any assertion on a tick step always fails with `got: ""`.

```grue
test "execution"
    press red button of Benson. "whirrs into action"
    insert beep cube in Benson.
    . "beeps happily"   ← tick: true — executeTurn never called, assertion always fails
```

### Fix

Add the missing branch in `runTests`:

```js
} else if (step.tick) {
    await executeTurn("");
}
```

Lands with M17 (every-turn handlers).

---

## Fixed

The following issues were resolved during M5 and are kept here for reference.

### `matchParam` uses exact class match, not instanceof ✓

Fixed in M5: `matchParam` now calls `_instanceof(canonical, type)` to walk the
class hierarchy instead of comparing `node.class` directly.

### `for item in filter(Class):` wraps filter result in `_children()` ✓

Fixed in M5: `compileForIn` detects `FilterExpr` collections and emits them
directly without the `_children()` wrapper.

### `_filter()` O(n²) lookup ✓

Fixed in M5: `_filter` uses `([name, n])` destructuring and passes `name`
directly to `_instanceof`, eliminating the `Object.keys().find()` scan.

### `_call` does not return fail tokens — `when` arms on fail signals never fire ✓

Fixed in M5: `_callT` returns the token for both `_SucceedSignal` and
`_FailSignal`. The compiler emits `_callT` when a handler call is the switch
expression of a `when` statement; `_call` (null on fail) is kept for boolean
contexts such as `unless {handler silently}`.
