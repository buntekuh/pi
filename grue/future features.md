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

The primary outstanding work is writing and testing the `List` library class itself, not language changes.

---

### 4. Topic classes — dynamic dialog sets with availability rules

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

### Relation to pathfinding

The `go to` auto-pathfinding feature (below) depends on `List` directly — BFS uses it as a frontier queue and the reconstructed route is stored as a list of directions consumed one per turn.

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

A `go to` handler that finds the shortest route to any named room via BFS and moves the player there step by step, one turn at a time.

### What we already have

- **Exit iteration on any room**: `for dir, dest in room_var.filter(Room):` works because `FilterExpr.Collection` is any `Expr`, so runtime room variables are fine
- **Object-as-map**: serves as BFS queue, visited set, and predecessor map via `obj.{key}` dynamic access
- **Bounded loops**: `for i from 0 to N:` handles the BFS outer loop (bound ≈ max rooms in the game)
- **`on every turn:`**: the natural hook for auto-advance

### What's missing

**1. List processing** (see above — prerequisite)

**2. Codegen bug — custom exits silently dropped** (see `codegen_issues.md`)

**3. `go to` handler and BFS logic**

```grue
List auto_route

on go to Room:destination:
    say "You are already there." if location is destination
    fail if location is destination

    # BFS setup
    Object bq
    var bq_head: 0, bq_tail: 0
    Object visited, pred_room, pred_dir

    bq.{bq_tail} = location
    bq_tail + 1
    visited.{location} = 1

    var found: 0
    for step from 0 to 500:
        if found == 0 and bq_head < bq_tail:
            var cur = bq.{bq_head}
            bq_head + 1
            if cur is destination:
                found = 1
            else:
                for dir, next in cur.filter(Room):
                    if visited.{next} is unset:
                        visited.{next} = 1
                        pred_room.{next} = cur
                        pred_dir.{next} = dir
                        bq.{bq_tail} = next
                        bq_tail + 1

    say "You can't find a way there." unless found
    fail unless found

    # Reconstruct: walk back from destination, prepend each direction
    clear auto_route
    var r = destination
    for i from 0 to 100:
        if r isnt location:
            push front pred_dir.{r} to auto_route
            r = pred_room.{r}

```

The route stores **direction strings** (e.g. `"north"`, `"top of ladder"`), not room names. Each step is consumed by `on every turn:` — one direction per turn, dispatching through the normal `go Room:destination` handler so locked doors, energy limits, and any other movement overrides apply naturally.

```grue
on every turn:
    if auto_route.head < auto_route.tail:
        var next_dir = auto_route.items.{auto_route.head}
        pop from auto_route
        {go next_dir}
        say "You have arrived." if auto_route.head >= auto_route.tail
```

The test stepper (`.` in test blocks) advances turns without player input, so auto-routing is fully testable:

```
go to Mare Tranquillitatis.
. "You move top of ladder."
. "You have arrived."
```

### Work breakdown

1. `List` class — see list processing feature above
2. Fix `writeExits` bug (see `codegen_issues.md`)
3. `go to` + BFS handler in `standard.grue` (or `navigation.grue`)
4. `on every turn:` auto-advance in `standard.grue` — driven by the test stepper in tests, normal turn processing in interactive play

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
