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

### `world` — the singleton root

`world` is the root of the world tree. It is a singleton created automatically
by the runtime — authors never declare it. It cannot be subclassed or
re-declared; the compiler rejects `extends World` and any attempt to declare a
second `world`. All top-level declarations in a game file become properties or
children of `world`.

Turn handlers declared at the top level of a game file belong to `world` and
fire unconditionally every turn, like object-level handlers. This is what
distinguishes them from room-level turn handlers, which fire only when the
player is in that room.

`world` is addressable in code:
```
world.score
world.location
for arr in world.filter(Array):
```

### World-level nodes

| Node | Description |
|------|-------------|
| Kinds | Global kind variables and their types |
| Properties | Global vars, score, etc. |
| Rooms | All rooms; exits are plain properties |
| Doors | Top-level door rooms |
| Objects | Global objects not inside any room |
| Player | The player object |
| Classes | Class definitions (see below) |
| Handlers | Global `on` handlers |
| Internal handlers | Global `internal` handlers |
| Turn handlers | `on every turn:` |

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
| Handlers | `on` handlers — the class's public interface |
| Internal handlers | `internal` handlers — callable from code only |
| Turn handlers | Per-class turn behavior |

### Accessing and iterating the tree

```
brass lantern.light
kitchen.north
world.location
```

```
for item in player:              # player's inventory
for key, value in kitchen:       # all kitchen properties and exits
```

### Object reference semantics

Objects in the world tree are always **references** — passing an Object to a
handler passes a reference to the original node, not a copy. Modifications
inside the handler are immediately visible everywhere that holds a reference
to the same node. There is no implicit copying of Objects.

### Containment vs reference

**Containment** is determined by declaration position. An instance declared
inside another node's body is a child of that node — its `location` is set
automatically:

```
Room kitchen "A cramped kitchen."
    Item cookie jar "A ceramic jar."   # cookie jar.location = kitchen
```

**Reference** is a property value pointing to an existing instance. It does
not affect the instance's location:

```
Room living room "A comfortable room."
    jar: cookie jar    # reference only — cookie jar stays in kitchen
```

Declaring the same instance name a second time is a compiler error. Every
instance has exactly one declaration point, which is its initial location.
`item.location = X` in code moves the item at runtime.

**The containment edge is owned by the item, not the container.** Although the
source tree is written top-down (items declared inside rooms), the runtime
flattens this into a dictionary of back-references: every item carries a
`location` property pointing at its parent. Rooms do not store child lists.
`filter()` reconstructs the parent→children direction by scanning all nodes:

```
for item in player.location.filter(Item):   # O(n) scan — item.location == player.location
```

This reads container-centrically but the data is item-centric. The distinction
matters: adding an item to a room is always `item.location = room`, never an
operation on the room itself. A future optimisation could maintain explicit
`children` arrays on each node to make `filter()` O(k), but the `.location`
back-reference model is load-bearing throughout the engine and is not changing.

### The tree as authoring tool

Because the world is a single well-defined tree, the IDE can expose it as a
live navigable view at any time — rooms, exits, objects, handlers, kind states,
styles. The author always has a complete picture of their game world without
having to mentally reconstruct it from source files.

---

## Part I — The World Model

### 1. Classes, Inheritance and Instances

**Class names** are single words, capitalized: `Room`, `Door`, `Ledger`, `Robot`.

**Instance names** are sequences of words separated by spaces. Valid characters
in each word: letters, digits, underscores, hyphens, and apostrophes.
Numbers are valid name components: `3 wishes`, `2B`, `O'Brien`, `mother-in-law`.
Commas are not allowed in names — they are reserved as alias separators.

```
Room Mare Tranquillitatis "A vast lunar plain."
Object mother-in-law "A difficult relation."
Object O'Brien "The station commander."
Object 3 wishes "A small brass lamp."
```

The first word of any declaration is always the class name. Everything after
(before the optional description string) is the instance name.

**All instances must be named.** Anonymous objects are not allowed — this
applies to world declarations, inline door declarations, and handler
parameters. Handler parameters use the `Type:label` form where the label is
the name within the handler scope (`Object:response`, `Object:request`).

Single inheritance. Implicit `extends Object` if omitted.
`Object` provides: name, keywords, description, location.

`.class` is a reserved property on every object. Dynamically changing an
object's class is under consideration but not yet defined — deferred for
further design work.

#### Built-in class hierarchy

The runtime and standard library pre-define the following classes. Authors
extend them freely but may not redefine or replace them:

```
Object
├── Player                  # the player — auto-instantiated as world.player
├── Room                    # a location
│   └── Door                # pass-through connection between rooms
├── Item                    # anything that can be carried or contained
│   ├── Container           # an Item that holds other Items (open/close/lock)
│   └── Supporter           # an Item that other Items rest on top of
├── Scenery                 # fixed room fixtures; cannot be taken
├── Person                  # a named character; suppresses [the] and [a] articles
│   ├── Man                 # Person with gender: male
│   └── Woman               # Person with gender: female
├── Animal                  # a creature; gender defaults to neuter
├── Array                   # ordered collection
└── Style                   # named CSS class — no properties; validated by compiler
```

`kind gender: *neuter, male, female` is declared at world level — available
on every object. `Man` pre-sets `gender: male`, `Woman` pre-sets
`gender: female`. `Animal` and bare `Person` default to `neuter`.

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
        fail unless has self silently
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

#### `world` properties

The standard library pre-defines the following properties on `world`:

| Name | Type | Description |
|------|------|-------------|
| `player` | object | The player |
| `location` | object | The player's current room |
| `score` | value | Current score |
| `turn` | value | Turn counter |
| `game_state` | kind | `running`, `won`, `lost`, `ended` |
| `gender` | kind | `neuter` (default), `male`, `female` — available on every object |
| `save_file_name` | property | Name of the save file |

Authors add their own kinds, properties, and vars at the top level of any game
file. All top-level declarations become properties or children of `world`.

### 2. Properties and Kinds

#### Properties

Named key-value pairs on any node. Property names may be multiple words
but must not contain reserved keywords as standalone words — `is`, `and`,
`or`, `not`, `if`, `unless`, `on`, `in`, `to`, `from`, `for`, `fail`,
`succeed`, `true`, `false`, `unset`, and all other language keywords.
The compiler enforces this.

```
east: kitchen
max_occupants: 4
save_file_name: "autosave"
top of ladder: Mare Tranquillitatis
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

**Kind names and kind values are always single words** (letters, digits,
underscores). Multi-word concepts use underscores: `love_interest`,
`stealing_the_fleece`. The reserved word `not` is forbidden as a kind value,
since `is not X` always means boolean negation.

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

**Declaring a kind** — `kind` registers the kind and its values. It does not
set any property anywhere. Use `is <value>` to apply a kind to a specific
context (world, class, instance, or handler body):

```
kind topic: *unset, jason, help, stealing_the_fleece
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

**Applying a kind** — `is <value>` sets the kind property on the current
context. The same syntax works in class bodies, instance bodies, the world
body, and handler bodies:

| Syntax | Meaning |
|--------|---------|
| `is lockable` | boolean kind — sets to `true` |
| `is not lockable` | boolean kind — sets to `false` |
| `is sad` | named list kind — sets to `sad` |

```
Object iron door "A heavy iron door."
    is lockable

Object fog "A low coastal fog."
    is not lockable
    is damp
```

At the world level (top of a game file), `is <value>` sets a property on the
world object itself:

```
kind deployment: *development, release   # declares the kind
is development                           # world.deployment = development
```

Override it later in the file or in a handler body:
```
is release                               # top-level: sets world.deployment = release

on deploy:
    is release                           # handler body: same effect at runtime
```

**Implicit world-level kind check** — `is <value>` used as a condition (in an
`if`, `unless`, or postfix guard) checks the world's property for that kind:

```
seed(1) if is development
say "Debug info." if is development
```

This is equivalent to `deployment is development` but does not require naming
the kind explicitly.

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

| Type | Matches | Player types |
|------|---------|--------------|
| `object:name` | any game object | bare word — `take lantern` |
| `number:name` | an integer | bare integer — `open ledger at 3` |
| `string:name` | a quoted string | double-quoted text — `record "Jason" in rolodex` |
| `ClassName:name` | an instance of that class | bare word matching an instance of that class |
| `self` | the owning instance | bare word matching this instance (class/object bodies only) |

```
on take object:item:
on open Ledger:ledger at number:page:
on record string:entry in Ledger:ledger:
on talk to Michelle:npc:
on traverse passage in the dark:
```

**`string:name`** captures free-form player input. The bound variable holds the
string value without its surrounding quotes and can be used anywhere an expression
is valid:

```
class Ledger
    on record string:entry in self:
        log.{position} = entry          # store the string
        say "Recorded: {entry}."        # interpolate it

on name object:thing string:label:      # rename thing to label
    thing.name = label
    say "{thing} is now called {label}."
```

The player types the value in double quotes: `record "Jason Bourne" in rolodex`.
Quotes are required — unquoted words are matched as object names or keywords, not
strings. The grammar treats `string` as a distinct slot type, so a handler with a
`string:x` parameter never conflicts with one using `object:x` at the same
position.

#### self

`self` is only valid inside a `class` or object body. It is sugar for
`ClassName:self` and binds the handler to its owning type in the grammar:

```
class Door
    on open self with key:      # matches any Door instance — "open gate with key"
        fail unless key matches self.key
        opened = true

Object yoke
    on examine self:            # matches "yoke" specifically
        say "A sturdy wooden yoke."
        parent
```

At global scope use an explicit class parameter instead:
```
on open Door:door with key:     # equivalent to the Door class handler above
```

#### Public and internal handlers

Public handlers (default) become player grammar — the player can type them.
`internal` handlers are callable from code only, never by the player:

```
internal has object:thing:
    take thing unless player has thing
    succeed if player has thing
    fail not_here

on open Ledger:ledger at number:page:    # player can type "open rolodex at 3"
    fail unless has ledger silently
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
`fail` and `succeed` stop the handler chain — no further handlers run unless `parent` was already called.

Guard clauses:
```
fail "no ledger" unless player has ledger
fail "out of bounds" if page >= 10
```

#### Calling handlers

Handlers are called by name with their arguments. Arguments are references to
existing objects in the world tree — types are already known and do not need
to be repeated at the call site:

```
operate telephone
fix machine with spanner
```

**Explicit class override** — an argument may be qualified with a class name
to select a specific level in the handler chain. The class must be the
object's actual class or one of its ancestors; using an unrelated class is a
compile error. All arguments are checked against the handler's declared
parameter types:

```
operate Machine:telephone     # use Machine's handler, not Telephone's
```

**Inline object creation** — the last argument in a call may be a new object
created inline. The class name is required because the object does not yet
exist in the world tree. A trailing `:` signals that a property body follows:

```
play Sound:sound:
    file: "pling.wav"
    volume: 80
```

Only the final argument may have an inline body. Earlier arguments must be
references to existing objects.

Handler calls are written bare in code — no brackets needed. `silently`
suppresses `say` throughout the call chain:

```
fail unless has ledger silently

if traverse passage in the dark:
    say "You survived."

say "You survived." if traverse passage in the dark
say "Blocked." unless traverse passage in the dark
```

`when` dispatches on the token from a handler call, or on any string expression.
Arms may be identifier tokens or quoted strings. Unhandled tokens propagate to
the caller:
```
when traverse passage in the dark:
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

`{}` wrapping a handler call is never needed in code — write the call bare.
`{}` after a dot remains valid for dynamic property access: `object.{variable}`.

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

#### Includes

`include` splits a game across multiple source files. All declarations in an
included file merge into the same namespace at the same precedence as the main
file — they are the same game, just written across several files:

```
include "chapter_2"
include "chapter_3"
```

Declaring a handler with the same signature in two different included files is
the same error as declaring it twice in one file. The compiler enforces
uniqueness across the main file and all includes together.

Includes are resolved recursively. An included file may itself include further
files. Circular includes are a compiler error.

#### Library imports

`library` imports reusable external code. Library handlers sit at the bottom
of the selection chain — own-code handlers (from the main file or any include)
always take precedence:

```
library "standard"
library "containers"
library "containers" as std    # alias on collision
```

Declaring a handler with the same signature as a library handler silently
overrides it — this is intentional, not an error.

All imported files are plain `.grue` files. Library files conventionally begin
with a metadata comment:
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

**Top-level door** — two exit properties required, one for each connected room.
Use this form for prominent doors that are naturally described at world level:

```
Door iron door, gate "A heavy iron door."
    east: landing
    west: bedroom
    is lockable
    key: rusty key
```

**Inline door** — declared on a room exit using `leads to:` for the
destination. An inline door is one-directional on its own:

```
Room cellar "A damp cellar."
    up: Door trapdoor "A heavy trapdoor."
        leads to: kitchen
```

**Shared inline door** — declare the same named door in two rooms with
matching `leads to:` properties. The compiler merges them into a single
object; both sides share state (locked, open, etc.):

```
Room vestibule "A grand entrance hall."
    east: Door brass door
        leads to: kitchen
        is lockable
        key: brass key
    west: garden

Room kitchen "The smell of burnt coffee lingers."
    west: Door brass door
        leads to: vestibule
```

The compiler validates that the two `leads to:` values cross-reference each
other. Declaring the same door name in more than two rooms is an error.

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
    manhole: the sewers
    port: docking bay
    west: landing pad
```

The input handler matches the player's input against all Room-valued properties
of the current location, so `manhole` and `port` work as movement commands
automatically.

### 7. Actors

Actors are not a distinct language concept — any object or class with an
`on every turn:` handler is effectively an actor. Object and class turn
handlers always fire every turn regardless of where the player is.

Room turn handlers are scoped: they fire only when the player is currently
in that room. This makes rooms natural containers for scripted sequences
without manual location guards.

`on every turn:` exists at three levels: global, room, and object/class.
Global and object/class handlers fire every turn without restriction. Room
handlers fire only when `location is` that room.

Unlike player-input handlers, all turn handlers (`on every turn:`, `on turn N:`,
and all range forms) may be declared **multiple times** at the same level — all
instances fire independently, in declaration order. There is no override and no
handler chain. Each declaration is a separate, self-contained reaction to the
passing of a turn:

```
on every turn:
    if location isnt last_room:    # room entry tracking
        entered location
        last_room = location

on every turn:
    say "Rain patters on the windows." if weather is rainy
```

`turn` is a global counter that increases by one every turn. It starts at 0
before the player's first input — use `if turn == 0:` for initialization.
`turn` is writable — assigning `turn = 0` resets the counter, which restarts
all `on turn` handlers relative to that point. This is the mechanism for
room-relative or scene-relative turn counting:

```
on go Room:destination:
    turn = 0 if destination is cave    # reset on entering the cave
    parent
```

There is no separate `on start:` — authors who want one can define their own:

```
on every turn:
    lamp.light = lit if turn == 0
    say "You wake up in a cold, dark room..." if turn == 0

on spawn Robot:
    say "The killer robots are on the march."
    
Room doomsday chamber "Banks of humming machinery."
    on every turn:
        spawn Robot killer robot

Object time bomb "A ticking device."
    fuse: 5
    on every turn:
        fuse--
        explode if fuse == 0
```

`on turn` handlers fire only on specific turns or turn ranges, without
needing a manual condition:

```
on turn 1:
    say "You wake up on the cold floor."

on turn 3-5:
    say "Time passes slowly."

on turn 10-:
    say "You have been here a long time."

on turn -2:
    say "The first moments."
```

| Form | Fires when |
|---|---|
| `on turn 1:` | exactly turn 1 |
| `on turn 3-5:` | turns 3, 4, and 5 |
| `on turn 10-:` | turn 10 and every turn after |
| `on turn -8:` | every turn up to and including turn 8 |

All `on turn` forms follow the same multiple-declaration rule: any number of
handlers with the same form may be declared at the same level and all fire.

#### Proximity guards

Object and class turn handlers fire every turn regardless of where the player
is. Output inside them should normally be guarded so the player only receives
it when they can actually perceive it:

```
internal on beep Robot:robot:
    say "{robot} beeps happily." if robot.location is player.location
```

Without the guard, the player would hear every robot in the game world on every
turn — including ones in other rooms. The guard `robot.location is player.location`
limits the output to robots the player is standing next to.

To force output regardless of location — a public address system, a loud
explosion, a dream sequence — simply omit the guard:

```
internal on alarm Robot:robot:
    say "Warning! {robot} has detected an intruder!"
```

Or override the handler in your game file without the proximity condition:

```
on beep Robot:robot:
    say "{robot} beeps."    # no location guard — always heard
    parent                  # still runs the default beep behaviour
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
| `stop` | Disable all further player input |
| `fail` | Exit handler with failure |
| `succeed` | Exit handler with success |
| `parent` | Call parent handler |
| `choose` | Player choice block |
| `interface` | Interface to external capabilities |
| `test` | Define / run tests |

`say` is the output primitive. It appends text to the text buffer and can be
overridden like any handler.

#### Output pipeline

```
say → text buffer → [resolve directives] → stdout
```

`say` appends text to the text buffer. At the end of each turn, inline
directives (`[nobreak]`, `[nobr]`, `[comma]`, `[the]`, `[a]`, etc.) are resolved in a
single pass over the buffer — at that point the full turn output is known,
making deferred decisions like "last item in list" and article selection
possible. The resolved buffer then goes to stdout.

### say

`say` is the output primitive. It formats a string and appends it to the text buffer.
Output flows through the pipeline: `say → text buffer → [directives] → stdout`.

#### String interpolation

`{}` inside a string evaluates a handler call or an expression and splices the
result into the output. The compiler distinguishes handler calls from expressions
by matching against declared handler signatures:

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

Use `[break]`, `[br]` or `[paragraph break]`, `[p]` when a real line break is needed inside a string.

#### Special characters

Source files are UTF-8. Any Unicode character may appear directly in strings.

| Write | Meaning |
|-------|---------|
| `[break]` or `[br]` | newline |
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
`fail`, `succeed`, and `when` arms across the codebase. The compiler warns
when an identifier token is emitted by a handler but no `when` arm in any
caller catches it. String tokens are arbitrary — the compiler cannot check them.

Guard clause forms:
```
fail out_of_bounds if page >= 10
fail "no ledger" unless player has ledger
succeed if player has self
```

`when` dispatches on the token from a handler call, or on any string expression.
Arms may be identifier tokens or quoted strings:
```
when traverse passage in the dark:
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



### 10. stop, save, quit, restart

`stop` is the only built-in primitive for ending player interaction. It
disables all further input immediately.

`save`, `load`, `quit`, `restart`, and `restore` are not built into the
language — they are standard library handlers defined on top of `stop` and
`interface`. Because they are ordinary handlers, authors can override them
like any other:

```
on quit:
    stop        # no confirmation dialog — hardcore mode
```

The standard library defines these using `interface` handlers for the
platform-specific parts (file dialogs, persistence). Authors who want
different behaviour declare handlers with the same signatures and the library
versions are replaced.

### 11. choose

`choose` presents labeled options to the player and dispatches on their
selection. Optional prompt string. Nestable. Branches contain arbitrary code.

```
choose "What do you want to talk about?":
    "Tell me about Jason.":
        topic is jason
        choose:
            "Exasperating.":
                medea_and_jason is exasperating
            "The man I love.":
                medea_and_jason is love_interest
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

### 13. Arrays

`Array` is a built-in class for ordered collections. Array literals use `[...]`
syntax and create an `Array` instance with integer keys assigned left to right
starting at 0:

```
primes: [2, 3, 5, 7, 11]
names:  ["Ben", "Bob", "Bruno"]
scores: [base, base + 10, base * 2]    # elements are expressions
```

Only unkeyed values are permitted inside `[...]`. Named properties are a
compile error — they belong on a named Object:

```
valid:   [1, 2, 3]             # ✓
invalid: [1, label: "x", 2]   # ✗ compile error

Object cursor                  # named metadata alongside an Array
    items: [10, 20, 30]
    position: 0
```

#### Accessing items

Static access uses a literal integer after the dot. Dynamic access uses `{expr}`:

```
say "{primes.0}"          # 2  — static, key is the literal 0
say "{primes.{i}}"        # dynamic — key is the value of i
primes.{i} = 99           # dynamic write
```

`arr.position` is always static — it accesses the property literally named
`position`, not the item at the index stored in `position`.
Use `arr.{position}` for dynamic lookup.

#### length

`length` is a computed property available on every Object. It returns the count
of set properties. For a dense Array it equals the number of elements:

```
say "{primes.length}"        # 5
say "{player.length}"        # number of items carried
say "{location.length}"      # number of properties on the current room
```

#### Iterating

Both iterator forms work on any Object including Array:

```
for item in primes:
    say "{item}"             # 2, 3, 5, 7, 11

for i, item in primes:
    say "{i}: {item}"        # 0: 2,  1: 3,  …
```

#### Dynamic property access

`{expr}` after a dot evaluates the expression and uses its result as the key.
Works for reads, writes, and any expression on any Object:

```
log.{position} = "Jason"       # dynamic write — key is value of position
log.{player.name} = 10         # dynamic write — key is player's name
log.{position} = unset         # clears the entry; key remains
say "{log.{position}}"         # dynamic read
```

#### Array is a convention

The `[...]` restriction is enforced at the literal only. Once an Array exists
in the world tree it is a plain Object — the runtime does not prevent adding
named properties after creation. `dwarves.position = 7` is legal code. If an
author chooses to treat an Array as a general Object, that is on them.

#### Array as a class

`Array` is a first-class class. The standard library may add handlers to it.
Authors can use it in handler signatures and `filter` expressions:

```
on summarise Array:list:
    for item in list:
        say "{item}[comma]"

for arr in world.filter(Array):
    say "{arr.length} items"
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
score = random(0, 50)               # random integer, min and max inclusive
seed(42)                            # seed the RNG — use in tests for determinism, remove before publishing
if turn modulo 5 == 0:              # modulo — infix operator
```
## 15. Styles

Grue does not define fonts, colors, or layout — that is CSS's job. Grue
only assigns names. The `Style` built-in class is a pure name registry:
instances carry no properties. What a style name means visually is entirely
up to the stylesheet that accompanies the exported HTML.

#### Declaring styles

```
Style mono
Style bold
Style key
Style headline
Style alert
```

Each declaration registers a name the compiler can validate. The standard
library pre-declares `headline` (used by the room-display handler). All
others are author- or library-defined.

#### Block style

A style name immediately after `say` wraps the whole output line in a
`<p class="name">` element:

```
say headline "The Boiler Room"       → <p class="headline">The Boiler Room</p>
say mono "All systems nominal."      → <p class="mono">All systems nominal.</p>
```

A block-style say always starts and ends its own paragraph — it never merges
with surrounding unstyled says.

#### Inline spans

`[name]...[/name]` inside a say string wraps the enclosed text in a
`<span class="name">`. The compiler validates that `name` is a declared Style:

```
say "Press [key]ENTER[/key] to continue."
say "Score: [bold]{score}[/bold] points."
```

`{expr}` interpolation inside a span works normally:

```
say "[alert]{warning_text}[/alert]"
```

#### CSS

The exported HTML file contains no inline styles. Authors supply their own
CSS file (or embed `<style>` rules in the container) targeting the class names
they declared:

```css
p.headline  { font-size: 1.4em; font-weight: bold; }
p.mono      { font-family: monospace; }
span.key    { font-family: monospace; background: #222; padding: 0 4px; }
span.alert  { color: crimson; font-weight: bold; }
```

Using an undeclared style name — in `say name "..."` or in `[name]...[/name]`
— is a compiler error.

### interface

`interface` declares a handler that calls an external capability outside of
Grue. The body identifies the target with `call:`. The runtime dispatches on
the `call:` value and silently ignores any type it does not recognise — so
interface handlers degrade gracefully on runtimes that lack the capability.

Currently only `call: js` is defined. Other types — graphics, audio, spans,
and more — can be defined in future.

#### call: js

Wires the handler to a JavaScript function. There is no inline JavaScript in
Grue — the Grue file stays pure Grue, and JavaScript files stay pure
JavaScript.

The response Object comes first in the signature, inputs follow:

```
internal interface Object:response Object:request:
    call: js
    function: "processData"
    filename: "handlers.js"
```

The body contains only Grue property declarations:

| Property | Purpose |
|----------|---------|
| `call` | The external capability to invoke. Currently: `js` |
| `function` | (`call: js`) Name of the JavaScript function to call |
| `filename` | (`call: js`) Path to the JavaScript file, relative to the game file |

The runtime serialises each Grue Object to a plain JavaScript object, calls
the named function, and awaits the promise. The response Object is passed by
reference — writes to its properties update the original world tree node
directly, so changes are visible to the caller immediately after the call
returns.

The JavaScript function mirrors the Grue declaration order:

```javascript
// handlers.js
async function processData(response, request) {
    const result = await someApi(request.input)
    response.output = result.text
    response.status = "done"
}
```

`interface` handlers are always internal — they are never reachable by player
input. Input-only handlers (no response) are valid for side effects:

```
internal interface Object:event:
    call: js
    function: "logEvent"
    filename: "analytics.js"
```

#### Example — calling an external service

The response object is declared in advance so the caller has a named place to
read the result. The `interface` handler wires up the JavaScript function. The
call passes the pre-declared response object and a request object:

```
class TranslationResult
    text: unset

TranslationResult result

internal interface translate Object:response Object:request:
    call: js
    function: "translate"
    filename: "translate.js"

on ask:
    translate result question
    say "{result.text}"
```

```javascript
// translate.js
async function translate(response, request) {
    const out = await callTranslationApi(request.text)
    response.text = out.text
}
```

The runtime populates `result` in place. After `translate result question`
returns, `result.text` holds the response and the game continues.

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
