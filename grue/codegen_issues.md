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

---

## `matchParam` uses exact class match, not instanceof — [runtime.js](compiler/codegen/runtime.js)

`matchParam` in the runtime resolves a grammar parameter slot by checking `node.class.toLowerCase() === typeLower`. This is an exact match against the node's declared class — it does not walk the class hierarchy.

The consequence: `on examine Vehicle:thing:` will only match nodes whose class is literally `Vehicle`. A `Robot` instance (even if `Robot extends Vehicle`) will not match and the handler will never fire for it. Every handler with a class-typed parameter only works for instances of that exact class, not subclasses.

This breaks M8 — the handler chain fires correctly once a sigKey is resolved, but the grammar trie cannot resolve the right sigKey for subclass instances.

### What needs to happen

Replace the exact-class check with an `_instanceof` call:

```js
if (node && (typeLower === "object" || _instanceof(canonical, type))) {
    return { value: canonical, consumed: len };
}
```

`_instanceof` already walks the class hierarchy correctly. The `typeLower === "object"` fast-path stays for the common "any object" case.

### Impact

- Any handler with a non-`Object` class parameter silently fails to match subclass instances
- M8 (handler chain with class hierarchy) cannot be demonstrated without this fix
- Needs to land before M9 (take/drop) since those handlers use `Item` typed parameters

---

## `for item in filter(Class):` wraps filter result in `_children()` — [codegen.go](compiler/codegen/codegen.go)

`compileForIn` unconditionally wraps its collection in `R._children(...)`. For node names this is correct — `_children("kitchen")` returns the children of the kitchen node. But when the collection is a `FilterExpr` (e.g. `player.filter(Object)`), `_filter` already returns an array of node names and wrapping it in `_children` passes an array where a string is expected, silently returning nothing.

```grue
for item in player.filter(Object):   # broken — compiles to _children(_filter(...))
    say "{item}"
```

compiles to:
```js
for (const item of R._children(R._filter("player", "Object"))) {  // wrong
```

should be:
```js
for (const item of R._filter("player", "Object")) {  // correct
```

The same problem affects `for key, value in X.filter(Class):` — `_entries` is called with an array instead of a node name.

### Fix

In `compileForIn`, detect `FilterExpr` collections and emit them directly without the `_children()` wrapper:

```go
if _, isFilter := s.Collection.(*ast.FilterExpr); isFilter {
    return fmt.Sprintf("%sfor (const %s of %s) {\n%s%s}\n",
        indent, s.Key, coll, body, indent)
}
```

### Impact

Every iterator test that uses `.filter()` in a `for` loop is silently broken. This includes `iterators.grue`, `library/standard.grue` (containment check), and any game that iterates inventory or room contents.

The same applies to `for key, value in X.filter(Class):` — that path wraps the filter result in `_entries()` instead of `_children()`, with the same effect: an array is passed where a node name is expected, silently returning `[]`.

---

## `_filter()` passes array to `_instanceof` via O(n²) lookup — [runtime.js](compiler/codegen/runtime.js)

`_filter` uses `Object.entries` but ignores the key in the destructuring (`[, n]`), then searches for the key by object identity:

```js
.filter(([, n]) => n.location === nameOrRef &&
    _instanceof(nameOrRef === nameOrRef
        ? Object.keys(nodes).find(k => nodes[k] === n)
        : null, className))
```

`nameOrRef === nameOrRef` is a tautology (always true), so the conditional is dead code. The `Object.keys().find()` lookup correctly recovers the node name, but does so with an O(n) scan per node — O(n²) overall. The node name is already available as the first element of the `Object.entries` pair.

### Fix

Use `([name, n])` destructuring and pass `name` directly:

```js
function _filter(nameOrRef, className) {
    const nodes = _game.nodes || {};
    return Object.entries(nodes)
        .filter(([name, n]) => n.location === nameOrRef && _instanceof(name, className))
        .map(([name]) => name);
}
```

---

## `_call` does not return fail tokens — `when` arms on fail signals never fire — [runtime.js](compiler/codegen/runtime.js)

`_call` captures the token from a `_SucceedSignal` but swallows `_FailSignal` silently, always returning `null` on failure:

```js
} catch (e) {
    if (e instanceof _SucceedSignal) result = e.token;
    else if (!(e instanceof _FailSignal)) throw e;
}
```

`when` clauses that branch on named failure outcomes never match:

```grue
when {open ledger at page}:
    out_of_bounds:              # never reached — _call returns null, not "out_of_bounds"
        say "That page is out of bounds."
    opened:
        ...
```

`fail out_of_bounds` inside the handler throws `_FailSignal{token:"out_of_bounds"}`, which is caught and discarded. The `when` switch receives `null` and falls through every arm.

### Tension with truthy/falsy use

`_call` is also used in boolean context — `unless {has item silently}`. If fail tokens were returned, `unless "not_here"` would be `false` (truthy string), meaning the guard would not fire on failure. The two uses require different semantics:

- `when {handler}:` needs the token regardless of fail/succeed
- `unless {handler silently}` needs null for any failure

### Fix options

**Option A** — two call variants: `_call` (returns null on fail, token on succeed) for boolean context; `_callT` (returns token for both) used by compiled `when` expressions. The compiler emits `_callT` when the call is the switch expression of a `when`.

**Option B** — return a result object `{ok, token}` from `_call` and update all call sites.

Option A is the smaller change and keeps existing boolean uses working without modification.

---

## `on examine self:` at global scope produces malformed sigKey — [world/build.go](compiler/world/build.go) + [sema.go](compiler/sema/sema.go)

`self` as a parameter type is valid inside class and instance bodies, where it resolves to the owning class name. At global scope there is no owning class, so `ownerClass` is `""` and `sigKey()` produces a key with an empty component — `"examine "` rather than `"examine Object"`.

The handler is then registered under `"examine "` and the grammar trie also emits `sigKey: "examine "`. Neither the handler map nor the grammar can ever match a player command — the handler is permanently unreachable.

Sema does not check that `self` is only used inside a class or instance body.

### Fix

Add a sema error: `self` as a parameter type is only valid inside a `class` or instance body. Emit `reserved_name` or a dedicated `self_outside_class` error at global scope.

---

## `compileIs` calls `_prop()` when left side is a kind value, not a node — [codegen.go](compiler/codegen/codegen.go)

When the right side of `is` is a kind value, `compileIs` checks whether the left side is syntactically a bare `NameExpr`. If so, it wraps it in `R._prop(left, kindName)` on the assumption that the left side is a node reference. But the left side might itself be a kind value name, in which case `_prop()` is wrong.

```grue
kind mood: *happy, sad

if happy is happy:   # compiles to R._prop("happy", "mood") === "happy"
                     # _prop("happy", ...) returns null — the string "happy" is not a node
```

In practice this arises when a kind value is passed as an argument and then compared — less likely than comparing a node, but valid Grue.

### Fix

In `compileIs`, before wrapping in `_prop()`, check whether the left `NameExpr` is itself a kind value (present in `c.kof`). If so, compile it as a plain string literal comparison rather than a property lookup:

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

A bare `.` in a test block compiles to `{ tick: true, assert: "...", negate: false }`. The test runner handles `step.exprFn` and `step.cmd` but has no branch for `step.tick` — it falls through with no `executeTurn` call, producing no output. Any assertion on a tick step always fails with `got: ""`.

```grue
test "execution"
    press red button of Benson. "whirrs into action"
    insert beep cube in Benson.
    . "beeps happily"   ← tick: true — executeTurn never called, assertion always fails
```

The comment in the source already notes this as deferred to M17, but the missing `executeTurn("")` call means tick steps are completely inert even for the turn counter and any synchronous side effects.

### Fix

Add the missing branch in `runTests`:

```js
} else if (step.tick) {
    await executeTurn("");
}
```

This lands with M17 (every-turn handlers), but the call itself is one line.
