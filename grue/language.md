# Grue — Language Specification

A parser interactive fiction authoring language. Compiles to JavaScript.
PICO-8 in spirit: self-contained, shareable, sellable on itch.io.
Games export as self-contained HTML files.
Compiler: Go. IDE: Wails + Svelte + Go. Runtime: JavaScript.

---

## The Dictionary Model

The game world is a single tree of dictionary nodes. Every object, room, class,
style, and handler is a node. Properties are key-value pairs on a node. The
hierarchy in source code IS the hierarchy in the tree.

### World-level nodes

| Node | Description |
|------|-------------|
| Kinds | Global kind variables and their types |
| Properties | Global vars, score, etc. |
| Rooms | All rooms; exits are plain properties |
| Doors | Top-level door rooms |
| Objects | Global objects not inside any room |
| Player | The player object |
| Styles | Named style definitions |
| Classes | Class definitions (see below) |
| Handlers | Global `on` handlers |
| Internal handlers | Global `internal` handlers |
| Turn handlers | `on every turn:` |
| AI definitions | Named AI actor definitions |

### Class-level nodes

Classes are nodes that can contain everything the world can, except rooms:

| Node | Description |
|------|-------------|
| Kinds | Kind declarations scoped to the class |
| Properties | Default property values |
| Doors | Room level door |
| String properties | Declared as plain properties: `hello: "world"` |
| Numeric properties | Declared as plain properties: `position: 0` |
| Arrays | Fixed-size arrays (`array log 10`) |
| Objects | Objects that instances contain by default |
| Styles | Style definitions scoped to the class |
| Classes | Nested class definitions |
| Handlers | `on` handlers — the class's public interface |
| Internal handlers | `internal` handlers — callable from code only |
| Turn handlers | Per-class turn behavior |

### Accessing and iterating the tree

```
brass lantern.light
kitchen.north
world.styles.mono.bold
```

```
for item in player:              # player's inventory
for key, value in kitchen:       # all kitchen properties and exits
```

### The tree as authoring tool

Because the world is a single well-defined tree, the IDE can expose it as a
live navigable view at any time — rooms, exits, objects, handlers, kind states,
styles. The author always has a complete picture of their game world without
having to mentally reconstruct it from source files.

---

## Part I — The World Model

### 1. Classes, Inheritance and Instances

**Class names** are single words, capitalized: `Room`, `Door`, `Ledger`, `Robot`.
**Instance names** are multi-word, any capitalization: `kitchen`, `iron door`,
`Mare Tranquillitatis`, `HAL`.

The first word of any declaration is always the class name. Everything after
(before the optional description string) is the instance name.

Single inheritance. Implicit `extends Object` if omitted.
`Object` provides: name, keywords, description, location.

`.class` is a reserved property on every object. It may only be assigned a
class name — changing it switches the object's active handlers:
```
peter.class = Adolescent
```

Class names are capitalized single words — syntactically distinct from kind
values (lowercase). This lets `is` check both without ambiguity:
```
if peter is sad:                        # kind value
if cube.location.class is Robot:        # class name — compiler validated
```

```
class Ledger
    array log 10
    position: 0
    kind opened: closed, open

    on open at number:page:
        fail unless {has self silently}
        fail out_of_bounds unless page < log.length
        position = page
        opened = open
        say "Opened {self} at position {page}."
        succeed opened

class Rolodex extends Ledger
    array log 10

    on open at number:page:
        say "Clack. Clack. Clack."
        parent

class Notebook extends Ledger
    array log 20
```

#### Instances

Instances are real-world objects that share the behaviour and properties defined
by their class and ancestor classes. Declared as:

```
ClassName name, alias "Description"
```

The comma-separated alias list and description are optional:

```
Ledger rolodex, index "A clackity index card rolodex."
Robot HAL "A gleaming security robot."
Chest vault
```

Instances may declare additional properties and kinds beyond their class:

```
Robot HAL "A gleaming security robot."
    clearance_level: 3
    kind mood: calm, agitated, hostile
```

#### Special instances

`player` — the player object. Its class can be defined or changed by the author.

`location` — always refers to the room the player is currently in:
```
if location is kitchen:
for item in location:
```

#### The global namespace

The root of the world tree. Contains the player, location, and all global state.
The standard library pre-defines the following:

| Name | Type | Description |
|------|------|-------------|
| `player` | object | The player |
| `location` | object | The player's current room |
| `score` | value | Current score |
| `turn` | value | Turn counter |
| `game_state` | kind | `running`, `won`, `lost`, `ended` |
| `save_file_name` | property | Name of the save file |

Authors add their own global kinds, properties, and vars at the top level of
any game file. All top-level declarations become part of the global namespace.

### 2. Properties and Kinds

#### Properties

Named key-value pairs on any node. The name has meaning. Valid value types
are objects, numbers, and strings:
```
east: kitchen
max_occupants: 4
save_file_name: "autosave"
```

#### set and unset

`unset` is Grue's null type. A property that has never been assigned, or has
been explicitly assigned `unset`, exists as a key but holds no value. This is
the only way a property can be empty — there is no other null or nil.

`unset` is valid as a declaration value. The property's type is then inferred
from the first assignment:

```
0: unset                        # slot declared; type determined on first write
west: unset                     # exit declared but leads nowhere
```

```
my list.{position} = unset      # clears the entry; key remains
```

Test whether a property holds a value:
```
if log.{position} is set:       # has a value
if log.{position} is unset:     # holds no value
```

`unset` is only valid on plain properties. Kind variables always hold exactly
one of their declared values — they can never be empty. Naming the first kind
value `unset` is an idiom for representing an empty state, but that is a named
value, not the null type:

```
kind topic: *unset, jason, help     # topic.unset is a named value, not null
west: unset                         # this is the real null
```

#### Kinds

A kind defines a named, ordered value type. Under the hood each value is an
integer assigned left to right starting at 0, which is what makes them
comparable. A kind variable always holds exactly one of its declared values —
it can never be empty.

The default value is marked with `*`. If no `*` is given, the first value is
the default:
```
kind mood: happy, *balanced, sad
kind wet: *dry, damp, wet, drenched, drowned
kind game_state: *running, won, lost, ended
kind light: lit, extinguished               # lit is default (first, no * needed)
```

**Boolean kind** — exactly `true` and `false`, no other values. `true`/`false`
must appear as a pair or not at all — mixing with named values is a compiler error:
```
kind lockable: *false, true
kind open: *false, true
```

**Named list kind** — two or more named values; `true` and `false` are forbidden:
```
kind mood: happy, *neutral, sad
kind wet: *dry, damp, wet, drenched, drowned
```

**Declaring a kind** — `kind` always declares. At the top level it also creates
a global variable of that type:
```
kind topic: *unset, jason, help, stealing the fleece
kind mood: happy, *neutral, sad
```

**Kind values are globally unique.** No two kinds may share a value name — the
compiler enforces this. This allows conditions to use the value name directly,
without ever naming the kind:

```
if peter is sad:
if lamp is lit:
if door is lockable:
if peter is not sad:
```

**Using a kind on an object or class** — `is` references an existing kind from
the global namespace and sets its value for this instance:

| Syntax | Meaning |
|--------|---------|
| `is lockable` | boolean kind — sets to `true` |
| `is not lockable` | boolean kind — sets to `false` |
| `is sad` | named list kind — sets to `sad` |
| `is wet` | named list kind — uses declared default |

```
Object iron door "A heavy iron door."
    is lockable

Object fog "A low coastal fog."
    is not lockable
    is damp
```

Assign and compare in code:
```
lamp.light = lit
peter.wet = drenched
if peter is sad:
if peter is not sad:
if peter.wet < wet:
if door is lockable:
```

### 3. Handlers and Internal Handlers

Handlers are both function declarations and patterns to match player input
against. The signature IS the grammar — no separate verb table required.

#### Handler signatures

Keywords are bare words. Parameters are `type:name` pairs. The parser derives
all valid player commands from the declared signatures:

| Type | Matches |
|------|---------|
| `object:name` | any game object |
| `number:name` | an integer |
| `string:name` | quoted text |
| `ClassName:name` | an instance of that class |

```
on take object:item:
on open Ledger:ledger at number:page:
on record string:entry in Ledger:ledger:
on talk to Michelle:npc:
on traverse passage in the dark:
```

#### self

Inside a class or object body, `self` can appear in a handler signature as the
typed parameter for the instance itself. It is what ties the handler into the
grammar — the parser uses it to route `open door with key` to the Door class handler:

```
class Door
    on open self with key:      # self matches "door", "gate", any Door instance
        fail unless key matches self.key
        opened = true

Object yoke
    on examine self:            # self matches "yoke" specifically
        say "A sturdy wooden yoke."
        parent
```

At the global level `self` is not available — use an explicit typed parameter:
```
on open Door:door with key:     # equivalent to the class handler above
```

`self` inside a class is sugar for `ClassName:self`.

#### Public and internal handlers

Public handlers (default) become player grammar — the player can type them.
`internal` handlers are callable from code only, never by the player:

```
internal has object:thing:
    take thing unless player has thing
    succeed if player has thing
    fail not_here

on open Ledger:ledger at number:page:    # player can type "open rolodex at 3"
    fail unless {has ledger silently}
    ...
```

#### Fail and succeed

`fail` exits the current handler with a failure result. Reaching the end of a
handler without failing is an implicit anonymous succeed. Use `succeed "token"`
only when the caller needs to distinguish the success case:

```
fail                        # anonymous failure
fail "no ledger"            # failure with string token
succeed "stored"            # named success
```

Tokens are plain strings — no declaration needed, no special identity.
`fail` and `succeed` do not stop the chain — parent handlers still run.

Guard clauses:
```
fail "no ledger" unless player has ledger
fail "out of bounds" if page >= 10
```

#### Calling handlers

`{handler args}` calls a handler inline. `silently` suppresses `say` throughout
the call chain:

```
fail unless {has ledger silently}

if {traverse passage in the dark}:
    say "You survived."

say "You survived." if {traverse passage in the dark}
say "Blocked." unless {traverse passage in the dark}
```

`when` dispatches on the token from a handler call, or on any string expression.
Arms may be identifier tokens or quoted strings. Unhandled tokens propagate to
the caller:
```
when {traverse passage in the dark}:
    eaten_by_grue:
        say "It's even darker down here."
    fail:
        say "Something blocked the way."
    succeed:
        say "You made it through."
    default:
        say "Something happened."

when location.name:
    "kitchen":
        say "You smell coffee."
    "garden":
        say "You smell flowers."
    default:
        say "You look around."
```

#### The game loop

1. Player enters a command
2. Parser matches it against all public handler signatures
3. The matching handler fires, from most specific class to least
4. After the command resolves, turn handlers fire in declaration order
5. The game waits for the next command

### 4. Overriding Handlers and Library Imports

#### Handler selection

The runtime selects the most specific applicable handler automatically:
object → class → parent class → library. Continuation is explicit — calling
`parent` invokes the next level; not calling it stops the chain there.

This gives three behaviors from the same syntax, depending on where `parent` appears:

```
Object yoke
    on examine self:
        say "You inspect it closely."
        parent               # before — own code first, then next level

on examine horse:Whatchamacallit:
    parent               # after — next level first, then own code
    say "You step back."

on examine object:Truc:
    say "Custom only."  # instead of — next level never runs
```

#### Library imports

`library` imports external reusable code. Library handlers sit at the bottom
of the selection chain — own code always takes precedence:

```
library "standard"
library "containers"
library "containers" as std    # alias on collision
```

Declaring a handler with the same signature as a library handler overrides it.
Declaring a handler with the same signature as another handler in own code is a
compiler error — each signature may appear only once across the main file and all includes:

```
include "chapter_2"
include "chapter_3"
```

All imported files are plain `.grue` files. Library metadata by convention:
```
# containers — portable container objects with open/close/lock
# author: Jane Smith
# version: 1.0
```

### 5. Rooms and Doors

#### Rooms

Rooms are always top-level nodes in the world tree — never nested inside
another object or room. The player's `location` is always a room. Objects
placed inside a room are declared as nested children.

Exit properties define the map. Their names are defined by the standard
library (`north`, `south`, `east`, `west`, `up`, `down`, `in`, `out`):

```
Room kitchen "The smell of burnt coffee lingers."
    north: hallway
    east: garden
    Object table "A scrubbed pine table."
    Object brass lantern, lamp "A tarnished brass lantern."

Room great hall "A vast echoing hall."
    south: kitchen
    up: tower
```

#### Doors

`Door` extends `Room`. Doors are pass-through — the player moves through
them transparently without feeling they have entered a separate room.

**Top-level door** — two exit properties required, one for each connected room:

```
Door iron door, gate "A heavy iron door."
    east: landing
    west: bedroom
    is lockable
    key: rusty key
```

**Room-level (nested) door** — declared inline on a room exit using `leads to:`
for the destination. The return connection is inferred:

```
Room vestibule "A grand entrance hall."
    east: Door brass door
        leads to: kitchen
        is lockable
        key: brass key
    west: garden
```

The player can refer to the door by name (`open brass door`) and the compiler
infers the reverse exit from `kitchen` back to `vestibule`.

### 6. Going Places

Movement is handled by a standard library handler like any other — nothing
special about `go` at the language level. The author can override it:

```
on go Room:destination:
    parent
    energy--
```

Compass abbreviations (`n`, `nw`, `se`, etc.) are expanded by the input
preprocessor before reaching the runtime — `nw` becomes `north west`,
`se` becomes `south east`. The movement handler sees only the full form.

The standard library resolves the direction against the current room's
exit properties, checks for blocking conditions (locked doors, dark rooms),
and moves the player. All of this is overridable.

Any property with a Room value is a valid exit — custom directions work with
no extra declaration:

```
Room crater rim "The edge of the crater."
    top of ladder: Mare Tranquillitatis
    manhole: the sewers
    west: landing pad
```

The input handler matches the player's input against all Room-valued properties
of the current location, so `top of ladder` and `manhole` work as movement
commands automatically.

### 7. Actors

Actors are not a distinct language concept — any object, class, or room with
an `on every turn:` handler is effectively an actor. The handler always fires
every turn regardless of where the player is. The author guards with conditions.

`on every turn:` exists at three levels: global, room, and object/class.
All fire every turn without restriction.

`turn` is a global counter that increases by one every turn. It starts at 0
before the player's first input — use `if turn == 0:` for initialization.
There is no separate `on start:` — authors who want one can define their own:

```
on every turn:
    lamp.light = lit if turn == 0
    say "You wake up in a cold, dark room..." if turn == 0

Room doomsday chamber "Banks of humming machinery."
    on every turn:
        spawn Robot killer robot

Object time bomb "A ticking device."
    fuse: 5
    on every turn:
        fuse--
        explode if fuse == 0
```

There is no `on turn x:` syntax — use a condition:
```
on every turn:
    say "The villain arrives at the castle!" if turn == 20
```

#### AI

`Ai` is a library class. An instance binds a model, source material, and role.
The class defines `internal on respond` which the author calls from handlers.
`js { }` is available to any author — the library uses it for the actual API call:

```
class Ai
    internal on respond Ai:ai with Object:schema:
        js {
            const result = await callAiApi(ai.model, ai.role, schema)
            // map result back to Grue properties
        }

Ai Eliza
    model: "claude-haiku"
    source: "eliza_background.md"
    role: "You are ELIZA, 1966. A mirror, not an advisor."
    language: "short sentences, always a question, never advice"
    history: 10
    context: mood, location
```

Objects call the respond handler. For a plain text response:

```
Object teletype "A huge teletype machine."
    on talk self:
        say "The machine clacks and prints:"
        {respond Eliza with Object}
```

For a structured response, pass an inline Record with the expected schema:

```
    on talk self:
        {respond Eliza with Record
            speech: string
            topic: unset
        }:
            say speech
            medea_awareness + 1 if topic isnt unset
```

---

## Part II — The Language

> **Statement termination** — statements end at the newline. No dot or semicolon
> required. The `.` character is reserved for test assertions, where it separates
> the command from its expected outcome (`open rolodex at 3. succeed opened`).

### 8. Name and Author

The game declaration appears at the top of the main file:

```
"Passing the Brass Lantern" by Bernd Eickhoff version guttoral goat
```

`"title"` — quoted string. `by author name` — multi-word, no quotes.
`version version_name` — optional, multi-word codename, no quotes.

### 9. Built-in Commands and Inline Directives

| Command | Purpose |
|---------|---------|
| `print` | Raw string output — the primitive |
| `fail` | Exit handler with failure |
| `succeed` | Exit handler with success |
| `parent` | Call parent handler |
| `end` | End the story |
| `quit` | Exit the application |
| `save` | Save game state |
| `restore` | Load saved game |
| `restart` | Restart from beginning |
| `choose` | Player choice block |
| `js { }` | JavaScript escape |
| `test` | Define / run tests |

`say` is a standard library handler that wraps `print` with styles, inline
directives, and string interpolation. Authors use `say`; `print` is for library
authors and low-level output. `say` can be overridden like any handler.

#### Output pipeline

```
say → print → text buffer → [resolve directives] → stdout
```

`print` appends text to the text buffer. At the end of each turn, inline
directives (`[nobreak]`, `[comma]`, `[the]`, `[a]`, etc.) are resolved in a
single pass over the buffer — at that point the full turn output is known,
making deferred decisions like "last item in list" and article selection
possible. The resolved buffer then goes to stdout.

### say

`say` is a standard library handler that formats a string and calls `print`.
Output flows through the pipeline: `say → print → text buffer → [directives] → stdout`.

#### String interpolation

`{}` evaluates either a Grue handler call or an expression. The compiler
distinguishes the two at compile time by matching against declared handler signatures:

```
say "The lamp flickers."
say "You carry {player.filter(Object).length} items."
say "Total: {score * 10} points."
say "{self} is open at position {position}."
say "The door is {if door is lockable "locked" else "open"}."
```

#### Block styles

A named style applied to the whole line:
```
say mono "SECTOR 7 status report."
say header "Chapter One"
```

#### Inline spans

Named styles opened and closed within a string. Only span-level style
properties apply; block-level properties are ignored:
```
say "Press [key]ENTER[/key] to continue."
say "[key]N[/key] North   [key]S[/key] South"
```

#### Multi-line strings

A string may span multiple lines. A newline followed by any amount of
whitespace is collapsed to a single space:

```
Room drawing room "Richly decorated sofas, armchairs and the occasional table
    are tastefully arranged around the room. Nameless ancestors look sternly
    down on you, proud through the ages."
```

Use `[newline]` or `[paragraph]` when a real line break is needed inside a string.

#### Special characters

Source files are UTF-8. Any Unicode character may appear directly in strings.

| Write | Meaning |
|-------|---------|
| `[newline]` or `[n]` | newline |
| `[tab]` or `[t]` | tab |
| `[paragraph]` or `[p]` | paragraph break |
| `["]` | literal `"` |
| `[[]` | literal `[` |
| `[]]` | literal `]` |
| `[{]` | literal `{` |
| `[}]` | literal `}` |

#### Inline directives

Resolved in the text buffer at end of turn — after all output for the turn is known.

`[nobreak]` — suppresses the newline after the current `say`:
```
say "You are carrying: [nobreak]"
for item in player.filter(Object):
    say "{item}[comma]"
```
→ `You are carrying: lamp, mug, and key.`

`[comma]` — `, ` between items, ` and ` before the last. Oxford comma on by default.
Resolved when the enclosing loop ends.

`[the]` / `[The]` — inserts "the" before the next `{}` value, skipped for persons:
```
say "[The] {item} glows."         → "The brass lantern glows."
say "You see [the] {npc}."        → "You see Medea."
```

`[a]` / `[A]` — inserts "a" or "an" based on the following word's sound, skipped for persons:
```
say "You find [a] {item}."        → "You find an umbrella."
```

`[s]` — inserts plural "s" based on the last preceding number:
```
say "{x} turn[s] left till the bomb explodes." → "1 turn left till the bomb explodes."
```

### fail/succeed/parent

`fail` and `succeed` exit the current handler and return a result to the caller.
Neither stops the handler chain — the parent handler still runs.

Reaching the end of a handler without failing is an implicit anonymous succeed.
Use a token only when the caller needs to distinguish which outcome occurred.

Tokens come in two forms:

```
fail out_of_bounds          # identifier token — no spaces, compiler can validate
fail "out of bounds"        # string token — free-form, author validates
succeed stored
succeed "stored"
```

Identifier tokens (no quotes, no spaces) let the compiler cross-reference
`fail`, `succeed`, and `when` arms across the codebase. String tokens are
arbitrary — the compiler cannot check them.

Guard clause forms:
```
fail out_of_bounds if page >= 10
fail "no ledger" unless player has ledger
succeed if player has self
```

`when` dispatches on the token from a handler call, or on any string expression.
Arms may be identifier tokens or quoted strings:
```
when {traverse passage in the dark}:
    eaten_by_grue:
        say "It's even darker down here."
    fail:
        say "Something blocked the way."
    succeed:
        say "You made it through."
    default:
        say "Something happened."
```

Because tokens are strings under the hood, `when` works on any string value:
```
when location.name:
    "kitchen":
        say "You smell coffee."
    "garden":
        say "You smell flowers."
    default:
        say "You look around."
```

`parent` calls the next handler in the chain (parent class or library). Its
position determines before/after/instead-of behavior:
```
on examine self:
    say "You inspect it closely."
    parent              # before

on examine self:
    parent              # after
    say "You step back."

on examine self:
    say "Custom only."  # instead of — parent never runs
```

`last_fail` and `last_succeed` hold the token from the most recent call:
```
last_fail               # token from the last failed handler call
last_succeed            # token from the last successful handler call
```


### 10. save, quit, end game

`stop` is the built-in primitive that disables all further player input.
Everything else is a library handler built on top of it.

| Command | Type | Behaviour |
|---------|------|-----------|
| `stop` | built-in | Disables all further input |
| `end` | handler | Sets `game_state`, calls `stop`. Overridable |
| `quit` | handler | Opens confirmation dialog, then calls `stop` |
| `save` | handler | Opens save dialog via `js { }` |
| `load` | handler | Opens load dialog via `js { }` |
| `restart` | handler | Opens confirmation dialog, resets game to turn 0 |
| `restore` | alias | Old-timey IF alias for `load` |

Because `end`, `quit`, `save`, and `load` are library handlers, they can all
be overridden. The dialog-opening handlers use `js { }` for the actual
browser dialog interaction:

```
internal on save:
    js {
        const name = await showSaveDialog()
        if (name) saveGameState(name)
    }
```

`restore` may be retired in favour of `load` — the decision is left to the
standard library.

### 11. choose

`choose` presents labeled options to the player and dispatches on their
selection. Optional prompt string. Nestable. Branches contain arbitrary code.

```
choose "What do you want to talk about?":
    "Tell me about Jason.":
        topic is jason
        choose:
            "Exasperating.":
                medea and jason is exasperating
            "The man I love.":
                medea and jason is love interest
    "I need your help.":
        topic is help
    "Farewell.":
        topic is unset
```

`choose` without a prompt is valid for nested choices. Like `when`, each arm
contains arbitrary code and can be nested to any depth.

### 12. Iterators

Four forms:

```
for item in collection:             # single value — children of any node
for key, value in collection:       # key-value pair
for i from 0 to max_slots:         # range with index variable
from 0 to 3:                        # range without variable — repeat N times
    say "Your wish is granted."
```

`filter(ClassName)` is a method on any collection, not a separate iterator form.
It returns only children matching the given class, including subclasses:

```
for item in location.filter(Ledger):       # only Ledger instances
for item in player.filter(Object):         # player inventory
for key, value in kitchen.filter(Room):    # all exits — rooms and doors
for key, value in kitchen.filter(Door):    # only exits through doors
```

Since `Door` extends `Room`, `filter(Room)` returns both. A locked exit is
just a door whose handler prevents passage.

### 13. Lists

Lists are plain `Object` instances. All items are just properties — numeric
keys, named keys, and kinds coexist freely on the same object. No new syntax.

Properties declared inline at definition are static — their key is a literal:

```
Object my list
    0: "zero"
    1: "one"
    2: "two"
```

**Dynamic property access** uses `{expr}` after the dot. The expression is
evaluated at runtime and its result used as the key. This works for reads,
writes, and any expression:

```
my list.0 = "first entry"          # static — key is literally "0"
my list.{position} = "Jason"       # dynamic — key is value of position
my list.{player.name} = 10         # dynamic — key is player's name string
my list.{"entry_" + turn} = "yes"  # dynamic — computed key
my list.{position} = unset         # clears the entry; key remains
```

`log.position` is always static — it accesses the literal property named
`"position"` on the object, not the property at the index stored in `position`.
Use `log.{position}` for dynamic lookup.

Iterate as any node:

```
for key, value in my list:
    say "{key}: {value}[comma]"
```

Use `filter` to select properties by type — see section 12.

Pre-declaring slots with `unset` is valid — the type is inferred on first write:

```
Object log
    0: unset
    1: unset
    2: unset
```

Or leave the Object empty and let entries be created on first write — both work.
Size limits are enforced at runtime:

```
class Ledger
    Object log
        0: unset
        1: unset
        2: unset
    position: 0
    kind opened: *closed, open

    on record string:entry in self:
        say "Out of bounds." if position >= 3
        fail out_of_bounds if position >= 3
        log.{position} = entry
        position + 1
        say "Recorded."
```

Static and dynamic reads:
```
say "{log.0}"               # static — literal key "0"
say "{log.{position}}"      # dynamic — key is value of position
```

### 14. Conditions and Expressions

#### if / unless

Block form:
```
if x > 5:
    say "Big."
else if x == 5:
    say "Exactly five."
else:
    say "Small."
```

Postfix guard — any statement can be conditionally executed:
```
fail no_ledger unless player has ledger
say "The torch dims." if turn > 20
score + 10 if location is treasury
```

`unless` is `if not`. Both work as postfix or block form.

#### Conditions

```
if x == 5:
if x is 5:
if x isnt 5:
if x > y:
if x >= y:
if player has lamp:
if log.0 is set:
if log.0 is unset:
if peter is sad:
if door is lockable:
```

`and`, `or`, `not` are readable aliases for `&&`, `||`, `!`:
```
if peter is sad and lamp is lit:
if location is kitchen or location is garden:
if not door is lockable:
```

#### Truthiness

There is no implicit type conversion. Exactly two values are false: the boolean
kind value `false`, and `unset`. Everything else is true — including `0`,
empty strings, and all other integers.

#### Arithmetic

All variables and properties are integers. Floats exist only as intermediate
expression values and can never be stored. Division produces a float
intermediate; assigning it to a variable rounds to the nearest integer.
Use `floor` or `ceiling` when you need explicit control:

```
score + 10                          # shorthand for score += 10
score - 1                           # shorthand for score -= 1
score += 10
score -= 1
score = score * 2
score = score / 2                   # 7 / 2 → 3.5 → stored as 4
score = floor(score / 2)            # 7 / 2 → 3.5 → stored as 3
score = ceiling(score / 2)          # 7 / 2 → 3.5 → stored as 4
score = round(score / 2)            # same as bare assignment, explicit
score = absolute(score - target)    # absolute value
score = biggest(score, 0)           # maximum of two values
score = smallest(score, 100)        # minimum of two values
if turn modulo 5 == 0:              # modulo — infix operator
```
## 15. Styles

Named styles group font and layout properties. Only `default` is predefined —
all other styles are declared by the author or a library. Unset properties
inherit from `default`.

```
Style default
    Font
        family: serif
        face: "Georgia"
        size: 16
    align: left
    color: black

Style mono
    Font
        family: monospaced
        face: "Courier New"
        size: 13
    align: left

Style key
    Font
        family: monospaced
        bold: true
    color: dodgerblue
```

`Font` is a class with a fixed set of properties:

| Property    | Values                          |
|-------------|---------------------------------|
| `family`    | `serif`, `sans`, `monospaced`   |
| `face`      | string — specific typeface name |
| `size`      | integer — point size            |
| `bold`      | boolean kind                    |
| `italic`    | boolean kind                    |
| `underline` | boolean kind                    |

Style properties:

| Property | Values                                              |
|----------|-----------------------------------------------------|
| `align`  | `left`, `right`, `center`, `justified`              |
| `color`  | CSS named color (`black`, `tomato`, …) or `#abcdef` |

Style properties are either **block-level** (apply to the whole `say`) or
**span-level** (can open and close inline within a string).
Block-level: `family`, `face`, `size`, `align`.
Span-level: `bold`, `italic`, `underline`, `color`.
When a span style is used inline, its block-level properties are ignored.

```
say mono "SECTOR 7 status report."          # block style — whole line
say "Press [key]ENTER[/key] to continue."   # inline span
```

#### Box (planned)

`Box` will extend `Font` with a rendered box — background, shade, and padding,
as seen in Inform 6 and 7 games. Deferred because it requires a dedicated
JavaScript render handler:

```
Box extends Font
    style: box
    background: grey
    shade: 20
    padding: 20
```

### js {}

Inserts an arbitrary JavaScript block. The application is responsible for
proper sandboxing. Use for external API calls, browser interaction, or anything
the Grue runtime does not provide directly:

```
on talk to terminal:
    js { elizaRespond(player_input) }

on examine screen:
    js { displayImage('terminal.png') }

internal on save:
    js {
        const name = await showSaveDialog()
        if (name) saveGameState(name)
    }
```

`js { }` is available to any author, but is primarily intended for library
authors. Game authors should prefer handlers.

### 16. Tests

Tests simulate a player at a keyboard — they issue commands and assert on the
text output. There are no internal tokens or success/failure states visible in
tests; only what the player would actually see.

#### The default test

The unnamed `test` block is the default test. The build tool runs it
automatically on every build. It is the entry point for the full test suite:

```
test
    go n. "Factory floor"
    test "rolodex".
    test "doors".
```

#### Named tests

Named tests are declared with a quoted name. They can be called from the
default test or from other named tests:

```
test "rolodex"
    open rolodex at 3. "Opened rolodex at position 3."
    record "Jason" in rolodex. "Recorded."
    open rolodex at 99. not "Opened"

test "doors"
    open iron door. "The door is locked."
    take brass key. "Taken."
    open iron door. "The door swings open."
```

#### Assertions

Each command line ends with `.` followed by an optional assertion:

| Form | Passes when |
|------|-------------|
| `command.` | command runs — no output assertion |
| `command. "text"` | output contains `text` |
| `command. not "text"` | output does not contain `text` |
| `test "name".` | runs named test — passes if it passes |

#### Scoped tests

Tests declared inside a room or object start the player there:

```
Room archive "A dusty storage facility."
    test "archive tests"
        open rolodex at 3. "Opened rolodex at position 3."
        examine rolodex. "position 3"
```
