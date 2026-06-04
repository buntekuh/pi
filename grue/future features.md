# Future Features

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
