# Future Features

---

## Grue as an embedded human-interaction engine

Grue's handler syntax reads like human language — `on examine Object:thing:` is not an implementation detail, it is the thing. This makes Grue's core dispatch model applicable to any domain where interaction needs to be described declaratively: not just text adventure commands but dialog, social rules, NPC behaviour, and decision trees. Ink won the narrative scripting space because it makes writing *feel* like writing. Grue is something different: a **reactive rules engine dressed in natural language**, and the parser input is just one way to trigger it.

Four design problems stand between current Grue and that broader role.

---

### 1. Inward-facing interface — receiving events from the host

The current `interface` mechanism is purely outbound: Grue calls out to a named JS function and receives a result asynchronously. The host cannot push events in.

For embedding, the host needs to fire into Grue: an NPC reached a waypoint, a timer fired, a physics collision occurred. These should dispatch through the handler chain just like player commands do.

**Runtime change**: expose `GrueRuntime.dispatch(sigKey, ...args)` in the public API. The internal `dispatch` function is already correct — it just needs to be exported.

**Language addition** (optional): a `receive` declaration documents which sigKeys the host is expected to fire, analogous to `interface` documenting outbound calls. It changes nothing about dispatch semantics — it is a declaration that this handler is part of the external API surface.

```grue
receive npc arrives at Room:room with Actor:npc:
    say "You notice {npc} enter." if npc.location is location
```

---

### 2. Actions as first-class values

Actions currently enter Grue in two forms — as text strings from the player (parsed by the grammar trie) or as pre-parsed command objects in test steps (also string-based). Neither is a value the game can manipulate at runtime. An NPC cannot construct an action, store it, pass it to a handler, or choose between alternatives without re-parsing strings.

An `Action` type resolves this. An action is a resolved (sigKey, args) pair — the form that `dispatch` already accepts — stored as a first-class value.

```grue
var greet_action: action greet player     # resolved once against the grammar
push greet_action to npc_queue            # stored in a list
{execute greet_action as barkeep}         # dispatched in actor context
```

**`action` expression**: `action <command-literal>` runs the literal through the grammar trie at construction time, not at execution time. The result is a typed object — resolution cost is paid once.

**`execute Action:act as Actor:actor`**: dispatches `act` through the handler chain with `actor` as the originating agent rather than the player. The same handler chain fires — locks, energy limits, NPC restrictions all apply.

NPC scripting, external event injection, and the test runner all currently work around the absence of this type. With first-class actions, patrol routes, scripted scenes, and remote commands become uniform.

---

### 3. List handling — concatenation, membership, and iteration syntax

The existing `List` design covers push/pop for stack and queue patterns. Three gaps remain before it is complete enough for production use (e.g. biro factory processing queues).

**Concatenation** — append one list to another. Useful for combining command queues, merging topic sets, building compound routes:

```grue
on concat List:source to List:dest:
    for i from source.head to source.tail:
        push source.items.{i} to dest
```

This is fully implementable in Grue using existing List handlers — no new language primitives needed.

**Membership test** — `List:l contains Object:item`, linear scan. Also expressible as a handler, though a compiler-backed primitive would be faster for large lists.

**`for item in list:` iteration** — currently you access items as `list.items.{i}` directly. A for-in form that desugars to the same index loop would be cleaner:

```grue
for item in npc_queue:
    say "Queued: {item}."
```

Map: iterate over items in the list and generate a new list

The primary outstanding work is writing and testing the `List` library class itself, not language changes.

---

### 4. Topic classes — dynamic dialog sets with availability rules

> **`talk to NPC` is not yet implemented.** The `on talk to NPC:npc:` command
> and its conversation UI depend on the choose overhaul described here.
> Giving items to NPCs is handled by `on give Item:thing to Person:npc:` in
> `standard.grue` — authors override per NPC or per item.

Ink's power is first-class dialog flow. Grue can match it through class instances where each topic carries its own availability rules. The handler chain already does the right thing — what is missing is a compact declaration syntax for the inclusion predicate.

```grue
class Topic
    on available:     # succeed = in the current topic set, fail = excluded
        succeed       # default: always available

    on discuss:       # fires when the player chooses this topic
        pass
```

Topics are ordinary instances:

```grue
Topic golden_fleece "The Golden Fleece"
    on available:
        succeed if player has jason_rumour
        fail

    on discuss:
        say "You recount the story of the Fleece..."
        golden_fleece_discussed = true
```

**`when:` block** — syntactic sugar for common availability predicates, instead of writing a full `on available:` handler. Conditions are the same boolean expressions used everywhere else in Grue:

```grue
Topic revenge_plan "The Revenge Plan"
    when:
        medea_trust >= trusted
        not revenge_discussed
```

`when:` compiles to an `on available:` handler that succeeds only if all listed conditions hold. The two are semantically equivalent; `when:` makes the conditions readable as a list without requiring the author to think in terms of fail/succeed signals. It also enables tooling: a debugger can show which topics are currently blocked and why, without running the handler.

**Dialog system** — an NPC's talk handler collects available topics and hands off to `choose`:

```grue
on talk to NPC:npc:
    for topic in filter(Topic):
        if {topic is available silently}:
            push topic to choices
    {choose "What would you like to talk about?"}
```

`choose` (stubbed in the language) is where Grue hands off to the host UI — a numbered menu in a text adventure, a dialog wheel in a 3D game, a voice prompt in audio. The host handles rendering; Grue handles what is available and what each choice does.

Topics are the clearest example of Grue used as a social rules engine. The host fires `GrueRuntime.dispatch("talk to NPC", [player, barkeep])`, Grue evaluates which topics are available, the host presents the menu, and the chosen topic's `on discuss:` fires. Narrative logic lives entirely in Grue; the host provides rendering and context.

---

## List processing

Lists are already expressible as Objects with integer keys and a position counter, but the language has no primitives to manipulate them. This is the missing half of the data model.

### Operations

| Operation | Stack | Queue | Deque |
|-----------|-------|-------|-------|
| `push Object:item to List:l` | push tail | enqueue | append |
| `push front Object:item to List:l` | — | — | prepend |
| `pop from List:l` | pop tail | dequeue head | remove head |
| `pop back from List:l` | — | — | remove tail |
| `peek List:l` | top | front | front |
| `peek back List:l` | — | — | back |
| `clear List:l` | reset | reset | reset |
| `List:l is empty` | predicate | predicate | predicate |
| `length of List:l` | count | count | count |

A single `List` class covers all three use cases (stack, queue, deque) depending on which end the author uses.

### Implementation

`List` is an Object with `head` and `tail` integer counters. Items live at `items.{head}` through `items.{tail - 1}`. `push front` decrements `head` — negative property keys are valid in the runtime so no special handling is needed.

```grue
class List
    Object items
    head: 0
    tail: 0

    on push Object:item to self:
        items.{tail} = item
        tail + 1

    on push front Object:item to self:
        head - 1
        items.{head} = item

    on pop from self:
        fail empty if head >= tail
        items.{head} = unset
        head + 1

    on pop back from self:
        fail empty if head >= tail
        tail - 1
        items.{tail} = unset

    on clear self:
        for i from head to tail:
            items.{i} = unset
        head = 0
        tail = 0
```

Peek is a property access, not a handler call: `my_list.items.{my_list.head}` for the front, `my_list.items.{my_list.tail - 1}` for the back.

### Usage examples

```grue
# Stack
push "first" to stack.
push "second" to stack.
pop back from stack.          # removes "second"

# Queue
push "a" to queue.
push "b" to queue.
var front = queue.items.{queue.head}
pop from queue.               # removes "a"

# Iteration (consume)
for i from queue.head to queue.tail:
    say "{queue.items.{i}}"
clear queue.
```

---

## NPC command queue — commanding actors around the map

The command queue primitive (built for the test runner) can be targeted at any
actor, not just the player. A queue associated with an NPC causes its commands
to be executed as that actor each turn rather than as the player.

### Shape

```grue
class Actor extends Person
    List queue

    on every turn:
        if queue is not empty:
            var cmd = peek queue
            pop from queue
            {execute cmd as self}   # dispatches the command with self as the actor
```

`execute cmd as Actor:actor:` would be a handler that re-parses the command
string in the context of `actor` rather than the player. The player's
`location` and inventory are not affected.

### Uses

- **Scripted NPC movement**: push `"go north"`, `"go east"` to guide an NPC
  along a patrol route
- **Cutscenes**: push a sequence of actions onto several NPCs at once to
  orchestrate a scene
- **Reusable templates**: a library handler `escort Player:player to Room:dest:`
  could build and enqueue a route on the escort NPC using the same BFS as
  `go to`
- **Testing NPC state**: test blocks can target an NPC's queue instead of
  the player, verifying that NPCs end up in the right places and states

### Relation to test runner

The test runner is the first user of the command queue primitive; NPC queues
are the second. Both use the same `List`-based queue and the same
`on every turn:` drain pattern. The only difference is the actor the command
is dispatched as.

### Dependencies

- `List` class (list processing feature)
- `execute cmd as Actor:actor:` handler — resolves grammar in actor context
- Command queue primitive (test runner milestone)

---

## `go to Room:destination` — auto-pathfinding

**Implemented** in `library/navigation.grue`.

### Usage

```grue
library "navigation"

go to cave.
go to the ridge.
```

### Design

Route storage uses a world-level `Object auto_route` with two integer counters
(`auto_route_len`, `auto_route_pos`), avoiding any List dependency.  Rooms are
stored by integer key with index 0 = destination, index 1 = room before
destination, …, index len-1 = first step.  Each turn the auto-advance handler
reads from index len-1 downward so no reversal is needed.

```grue
Object auto_route
var auto_route_len: 0
var auto_route_pos: 0

on go to Room:destination:
    var Object bq         # leading node-var block (Pascal-style)
    var Object visited
    var Object pred

    say "You are already there." if player.location is destination
    fail if player.location is destination
    auto_route_len = 0    # clear — a failed BFS leaves no stale route

    var bq_head: 0
    var bq_tail: 0
    bq.{bq_tail} = player.location
    bq_tail = bq_tail + 1
    visited.{player.location} = 1

    var found: 0
    for step from 0 to 500:
        if found == 0:
            if bq_head < bq_tail:
                var cur: bq.{bq_head}
                bq_head = bq_head + 1
                if cur is destination:
                    found = 1
                else:
                    for dir, next in cur:
                        if next is Room:
                            if next isnt Door:
                                if visited.{next} is unset:
                                    visited.{next} = 1
                                    pred.{next} = cur
                                    bq.{bq_tail} = next
                                    bq_tail = bq_tail + 1

    say "You can't find a way there." unless found == 1
    fail unless found == 1

    var r: destination
    for i from 0 to 200:
        if r isnt player.location:
            if r is set:
                auto_route.{auto_route_len} = r
                auto_route_len = auto_route_len + 1
                r = pred.{r}

    auto_route_pos = auto_route_len - 1

internal every turn:
    if auto_route_len > 0:
        if auto_route_pos >= 0:
            var dest: auto_route.{auto_route_pos}
            auto_route_pos = auto_route_pos - 1
            {go dest}
            if auto_route_pos < 0:
                auto_route_len = 0
                say "You have arrived."
```

### Limitations

- **Doors are not traversable.** BFS skips Door exits — Door nodes carry no
  room-typed props of their own.  Traversal through open doors is a future
  milestone.
- **Manual movement does not cancel the route.**  The player can cancel by
  typing `go to <current room>` (fails with "already there", clears len).
- **Maximum route: 200 steps.**

---

## `has <kindname>` — declare kind participation with default value

`is <value>` sets a property to a specific value. Sometimes the intent is
different: "this object participates in this kind" without caring which value
it starts at — the default is fine.

```grue
Object door
    has open      # door is openable; starts at the default (closed)
    has locked    # door is lockable; starts at the default (unlocked)
```

`has open` is equivalent to `is closed` when `kind open: *closed, open` — it
applies the default value. The distinction is expressive: `has open` says
"this object is openable," `is closed` says "this object is currently closed."

Can be combined with an explicit override:

```grue
Object front door
    has open, is open    # openable, and starts open
```

`has` would be a new body declaration form. All existing `is <value>` usage
stays valid. Purely additive.

---

## Drop `var` at top level

Top-level `var score: 0` is redundant — it declares a world-level property, which is exactly what a bare `score: 0` declaration would do (same as `capacity: 10` in a class body). The `var` keyword at file scope adds nothing the parser could not infer from `word: value`.

`var` inside a handler body remains meaningful (it declares a local JS `let`, scoped to the call), so the keyword stays there.

### What to do

Allow bare `key: value` at top level as an alternative to `var key: value`. Migrate all existing `.grue` files. Eventually deprecate `var` at top level.

### Impact

- Parser: recognise `word COLON expr? NEWLINE` at file scope as a world-property declaration (same path as `VarDecl`, no new AST node needed).
- Existing code: mechanical search-and-replace of top-level `var ` with nothing — all `.grue` files affected.
- Handler-body `var` is unchanged.

---

## String concatenation

Grue has no string concatenation. The `+` operator is numeric only; nested quotes inside a `{...}` interpolation slot break the outer string literal. Building a string from parts requires pre-computing a variable, which itself cannot be assigned incrementally.

### What to do

Allow `+` to concatenate strings when either operand is a string value. In the compiled JS this is already correct — `("hello") + (" world")` works — the only blocker is the lexer ending the outer string on the inner `"`.

The fix is in `splitInterp`: when scanning for `{...}` slots, track quote depth so that `"` inside a slot does not terminate the outer string. This is a lexer/scanner change in the interpolation splitter, not in the main lexer.

```grue
say "Hello, {name + "!"}."          # concatenate name with punctuation
say "{first + " " + last} arrived." # join two properties
```

String literals in expression position (`"..."` used as a value) are already parsed correctly everywhere except inside `{...}` slots in a containing string.

---

## Conditional interpolation

There is no way to include text conditionally inside a `say` string. Conditional output today requires separate `say` statements, which produce separate paragraphs rather than inline text.

### Syntax

A conditional expression inside a `{...}` slot: the expression evaluates to a string or to `""` if the condition is false.

```grue
say "Fruit: apples, pears{", bananas" if player has banana}."
say "The lantern is {if lit}glowing{else}dark{/if}."
```

Two forms:

**Postfix** — `{expr if condition}` evaluates to `expr` when `condition` is true, `""` otherwise. This is the common case (optionally adding words).

**if/else** — `{if condition}text{else}other text{/if}` for when both branches have content. This is a template-level construct, not an expression.

### Implementation

The postfix form is simplest and covers most cases. It maps to a JS ternary inside the template literal:

```js
`Fruit: apples, pears${condition ? ", bananas" : ""}.`
```

The `if/else` form requires the interpolation splitter to recognise `{if ...}...{else}...{/if}` as a single multi-part slot rather than a `{...}` expression. This is a larger parser change and can follow the postfix form.

### Relation to string concatenation

Both features together unlock natural-language sentence assembly without resorting to pre-computed variables or multi-paragraph output. They are the Grue equivalent of Ink's inline conditional text.

---

## Typed properties

`when` dispatching on instance names already works today. `fail`/`succeed` with object names as tokens cross-reference against `when` arms in sema. What is missing is the type safety layer: ensuring the value stored in a property is always an instance of the right class.

### Syntax

A property declaration prefixed with a class name declares a typed slot:

```grue
class CommandCube extends Item
    Command command: unset
```

`command` may only hold a `Command` instance or `unset`. Assigning anything else is a compile error:

```grue
CommandCube beep cube
    command: lantern    # error: lantern is not a Command
```

Without a type annotation the property is untyped — any value accepted (current behaviour).

### Implementation

`isSubclassOf` is already implemented for handler argument checking. Typed property assignments use the same check: the right-hand side must be an instance whose class is a subclass of the declared type.

---

## Polymorphic dispatch

Currently sigkeys are resolved at **compile time** from declared parameter types. True polymorphism would let `{execute program.{program_counter} for self}` walk the class hierarchy at runtime, selecting the most specific handler for the actual runtime type.

This requires typed property declarations (above) so the compiler knows the declared type of the slot. Each command class would then define its own `on execute for Robot:robot:` handler, replacing the `when` block entirely.

---

## Output post-processor and `print`

### The pipeline

`say` adds a unit of text to the output buffer. Before any of it reaches the DOM, a post-processor runs over the accumulated buffer and assembles the final paragraphs. This separation lets layout directives embedded in strings control how adjacent `say` outputs are joined:

- `[nobreak]` / `[nbr]` — combine this output with the next one into a single paragraph instead of two
- `[br]` / `[break]` — insert a line break within a paragraph
- `[p]` / `[paragraph break]` — force a new paragraph at this point

The compiler and `say()` are untouched; the post-processor is the only place directives are interpreted.

### `print`

`print` was the keyword for declaring and invoking post-processor rules — it sat between the `say` buffer and the final DOM render. It was removed and needs to be redesigned.

The intent: authors can declare named output rules that control how the buffer is assembled for specific contexts. For example, an inventory listing rule that joins items with commas and `and` before the last one, rather than one paragraph per item.

```grue
on inventory:
    for item in player.filter(Item):
        say "{item}[nobreak]"
    say "."          # closes the nobreak chain into one line
```

versus a `print` rule that handles the comma-joining explicitly:

```grue
print inventory list:
    # post-processor rule: join buffer entries with ", " and " and " before last
```

The exact syntax and scope of `print` rules needs to be designed before implementation.

---

## Output styling — block classes and inline spans

Grue expresses **semantic intent**; the theme engine controls **visual presentation**. No fonts, colours, or layout values appear in `.grue` source.

### Block styles

`say <style> "text"` emits a block element. Three predefined styles:

| Keyword    | HTML emitted              | Notes                        |
|------------|---------------------------|------------------------------|
| `text`     | `<p>text</p>`             | default — same as bare `say` |
| `headline` | `<h1>text</h1>`           | structural heading           |
| `box`      | `<p class="box">text</p>` | aside / callout box          |

`headline` uses `<h1>` because it carries structural meaning (room name, chapter title). All other styles emit `<p class="name">` so the theme can override freely.

Authors may use any word as a block style — `say alert "Warning: …"` emits `<p class="alert">…</p>`. Unknown classes are valid; the theme simply has no rule for them until one is added.

### Inline spans

`[tag]text[/tag]` inside a `say` string emits `<span class="tag">text</span>`. The predefined tags match HTML semantics that most themes will honour without explicit rules:

- `[em]…[/em]` → `<span class="em">` (emphasis)
- `[strong]…[/strong]` → `<span class="strong">` (strong importance)
- `[mono]…[/mono]` → `<span class="mono">` (monospace / code)

```grue
say "L'état c'est [strong]moi[/strong]."
say "Press [mono]ENTER[/mono] to continue."
say mono "Wir sind die Roboter."
```

Inline tags are parsed by the runtime's `say()` function using a small stack-based DOM builder — safe against injection regardless of what `{interpolation}` produces. Unrecognised or malformed tags render as plain text.

**Relation to layout directives**: `[nobreak]`, `[br]`, `[p]` are post-processor layout controls (no closing tag). Span tags always have a matching `[/tag]` and emit DOM content. The two syntaxes coexist without ambiguity.

---

## Theme engine and Wails authoring app

The intended delivery vehicle for Grue is a **Wails desktop app** — a Go backend wrapping a web frontend — similar in spirit to Pico-8 and the Inform 7 IDE. The app hosts:

- **Editor** — syntax-highlighted `.grue` source editing
- **Map editor** — visual room/exit graph, round-trips with source
- **Live game view** — the compiled HTML runtime embedded in a webview, with hot-reload on save
- **Debugger** — world-state inspector, breakpoints on handler dispatch, turn replay
- **Tutorial and manual** — built-in, browseable without leaving the app
- **Theme tab** — CSS variable editor; the only place visual presentation is configured

### Theme engine

The theme engine maps Grue's semantic class names (`headline`, `box`, `em`, `mono`, author-defined names) to CSS. It is a CSS variable sheet — no framework required. Authors who need full control can:

1. Override individual variables in the theme tab
2. Drop in a `.css` file that is injected into the compiled HTML's `<head>`
3. Embed a CSS framework via that same mechanism

The compiled HTML uses CSS custom properties throughout (`--grue-bg`, `--grue-fg`, `--grue-font`, `--grue-mono-font`, etc.) so theme overrides are isolated to variable declarations, not selector hunting.

The theme tab generates a `<style>:root { … }</style>` block; author-supplied CSS files are appended after it so they can override anything.
