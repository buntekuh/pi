# Grue language features

## Target platform
Grue 1.0 targets the Z-machine via Inform 6. Glulx (graphics, sound, full Unicode) is deferred to a future version.

## Source handling
- Multi-line quoted strings joined by preprocessor
- Python-style indentation for all blocks (no braces or end keywords)
- `#` line comments
- `uses` directive (reserved, not yet emitted)

## Rooms
- `room Name "description"` — display name and inline description
- Description in body: `room Name` then `"description"` on next line
- Exits: `north: "Room Name"` or `north: room_id`

## Objects
Kinds: `object`, `scenery`, `man`, `woman`, `robot`

- Inline description: `object crowbar "A heavy iron crowbar."`
- Compound nouns: `object blue door "desc"` → id `blue_door`, name `blue door`
- Comma synonyms: `scenery mailbox, box "desc"` → id `mailbox`, parser accepts all synonyms
- Behaviours: `is openable`, `is lockable`, `is container`, `is supporter`
- Boolean attributes: `locked: true`, `open: true` — any property with value `true` becomes an I6 `has` attribute
- `is locked.` is equivalent to `locked: true`; `is closed.` is equivalent to `open: false`
- Properties: `key: item_id`, `inside: room_id`

## Kinds and attributes

```
bendable: straight, bent
texture: rough, stubbly, smooth
```

- Declares a named kind with a list of values; the first value is the default
- Two values → I6 `Attribute` (second value is the attribute name; first is its absence)
- Three or more values → I6 `Property` with named constants
- `true` and `false` are prohibited as values — forces meaningful names
- Value names are scoped to an object's declared kinds; qualify as `kind:value` when ambiguous across libraries

### Setting and testing attributes in handlers

```
locked.              ! give self locked;
not locked.          ! give self ~locked;
the noun is bent.    ! give noun bent;
the noun is not bent.
if locked:           ! self has locked
if not locked:       ! self hasnt locked
```

Friendly aliases resolve to their canonical I6 attribute:
- `closed.` / `if closed:` → `~open` / `hasnt open`
- `unlocked.` / `if unlocked:` → `~locked` / `hasnt locked`
- `off.` / `if off:` → `~on` / `hasnt on`

## Doors
- In-room: `door blue door "desc"` inside a room block, with `leads:` property
- Top-level: declared outside rooms with bidirectional exit injection

    ```
    door blue door "desc"
        east: Inside
        west: Front of House
        is openable.
    ```

- Partner doors automatically brought into scope via `add_to_scope`

## Verbs
```
verb examine
    takes noun
    "You see nothing special."

verb pry, tear, wrench
    takes noun with held noun
    "There's nothing to pry there."

verb give to
    takes noun to creature noun
    "They don't want it."
```

Grammar line: `takes [qualifier] noun` — qualifier is optional.

| Qualifier | Meaning | Applies to |
|---|---|---|
| *(none)* | any visible object | first or second noun |
| `held` | object the player carries | first or second noun |
| `creature` | an NPC | first or second noun |
| `multi` | multiple visible objects | first noun only |
| `held multi` | multiple carried objects | first noun only |

For two-noun verbs the preposition separating them (e.g. `with`, `to`, `in`) matches the verb name suffix.

**Important:** qualifiers are parse-time scope/possession filters only. You cannot filter by kind or attribute at grammar time — `takes wet noun` is not valid. To act only on wet objects, accept any noun and guard in the handler:

```
verb dry
    takes noun
    "You can't dry that."

    instead of dry:
        if self is wet:
            self is dry.
            say "You dry it."
        else:
            say "It's already dry."
```

- First word of verb name capitalised as I6 action base
- Emits action stub routine and `Verb` declaration

## Handlers
On objects and doors:

```
instead of prying with crowbar:
    if open:
        say "Already open."
    else:
        say "You lever it free."
        open.
```

- Timing: `instead of`, `on`, `after`
- Action matched by base verb form (`instead of pry`); gerund form also accepted for compatibility
- Second-noun filter: `with crowbar` → `if (second ~= crowbar) rfalse;`
- Self conditions: `if locked:` / `if not locked:` / `if closed:` / `else:` — any I6 attribute name
- Chained conditions: `else if <cond>:` after any `if` branch — compiles to nested I6 `if/else`
- Subject conditions: `if SUBJ is VAL:` / `if SUBJ is not VAL:` / `if SUBJ has OBJ:` / `if SUBJ has not OBJ:` — see *Subject-qualified conditions* below
- Statements: `say "..."`, `locked.`, `not locked.`, `the noun is bent.`, `go room`, `box "..."`
- `after` handlers emit to Inform 6 `after` property; all others to `before`
- `on turn N:` fires on a specific turn count via `each_turn` with `turns == N` guard
- `each turn:` fires every turn via `each_turn`

## Say / string features
- `say "text"` in handlers emits `print`
- `{obj}` interpolation → `(name) obj` for known game objects, bare expression otherwise
- `{the obj}` → `(the) obj`, `{a obj}` → `(a) obj`
- `{s var}` → plural s: prints "s" unless var == 1 (e.g. `{item_count} item{s item_count}`)
- Runtime object variables resolved automatically: `noun`, `second`, `self`, `actor`, `location`
- `\n` → `^` (Inform 6 newline)
- `\t` → `@@9` (tab character)
- `"` → `~` (Inform 6 string escape)
- ISO 8859-1 characters (é, ñ, ü, etc.) encoded automatically as `@@decimal`
- Extra whitespace normalised

## Tests
```
test "default"
    take crowbar. "Taken."
    east. "Inside"
```

Each `test` block is a named sequence of commands with expected output substrings. The test runner (`runner.py`) runs them automatically and reports pass/fail.

```
test manually "chest puzzle"
    north. east.
    unlock chest with brass key. "Click."
    open chest. "The chest swings open."
```

`test manually` marks a test as skipped by the automated runner — it requires specific game state to be set up first (navigation to the right location, prior actions, etc.). Manual tests are still recorded in the `.gts` file and can be run with `runner.py --all`, or the developer can replay the commands by hand.

The `.gts` file records all tests alongside the compiled `.inf`; the runner only skips those explicitly marked `manual`.

## Manual and examples

The test files in `tests/` are intended to be published alongside the language manual as living examples. Each test file:

- Opens with a `#` comment naming the feature it demonstrates
- Shows the minimal Grue source needed to exercise that feature
- Is guaranteed correct because the build enforces it

When writing the manual, each chapter should have a short prose explanation followed by the verbatim test file for that feature. Readers can run the examples themselves with `build.sh -bt tests/<feature>.grue`.

## Classes

Define a shared type with default properties, required properties, and shared handlers:

```
class Wolf
    ferocity: 5
    speed: required
    is animate.

    instead of hunt:
        say "The wolf gives chase."
```

Instantiate inside a room block using the class name as the type keyword:

```
room Forest "A dark forest."

    Wolf gray "A gray wolf"
        speed: 6

    Wolf Fenrir "Fenrir"
        speed: 9
        ferocity: 10

        instead of hunt:
            say "Fenrir howls and lunges."
```

- Class properties become I6 `Class with` properties; instances inherit them automatically
- `required` marks a property that every instance must supply — omitting it is a compile error (E071)
- Instance handlers override the class handler for that action on that instance only
- Boolean and kind properties work the same as on plain objects (`charge: full.`, `is animate.`)

## Subject-qualified conditions

Conditions can test attributes or containment on an arbitrary named object, not just `self`:

```
if murderer is wet:          ! murderer has wet
if robot is not full:        ! robot hasnt full  (two-value kind)
if android is low:           ! android.charge == LOW  (three-value kind)
if bag has coin:             ! coin in bag
if bag has not key:          ! ~~(key in bag)
```

`player` works as a subject with no extra syntax:

```
if player is wet:
if player has trophy:
```

## End conditions

Three statements end the game from any handler:

```
win "You seize the trophy and claim victory!"
fail "The poison takes hold. Everything goes dark."
end story "Years later, no one remembered the incident."
```

- `win` — positive ending; displays the message then `*** You have won ***`
- `fail` — negative ending; displays the message then `*** You have died ***`
- `end story` — neutral ending; displays the message inside `*** ... ***` with no win/fail judgement
- The message is optional for `win` and `fail`; `end story` without a message shows `*** ***`

## NPC ordering

```
man robot "A helpful robot."
    is animate.

    on order take:
        move noun to self
        say "The robot picks up {noun}."

    on order drop:
        move noun to location
        say "The robot sets down {noun}."
```

`on order <verb>:` handles player commands directed at the NPC (`robot, take flask`). The verb matches the same names as `instead of` handlers. `noun` is the object the player named. Unrecognised orders are silently ignored.

## Moving objects

```
move crate to assembly
move self to workshop
move parcel to basket
```

Moves an object to a room, another object, or a container. Works in any handler. `self` refers to the object whose handler is running — useful for NPCs that move themselves between rooms.

## Arrays

```
array program 4
```

Declares a fixed-size word array of N elements, zero-initialised. Elements are read and written by index:

```
program[0] = 10
program[1] = 20
entry = program[0]
```

Indices start at 0. Use with `var` to hold the read value. Arrays are global — they persist for the entire game.

## Random numbers

```
roll = random 6
```

Assigns a random integer from 1 to N (inclusive) to a variable. Equivalent to rolling an N-sided die.

```
seed: 42
```

Top-level declaration that fixes the random seed at startup, making all `random` calls produce a deterministic sequence. Use this in test files to pin expected values; omit it in shipped games for genuine randomness.

Note: the Z-machine spec does not mandate a specific RNG algorithm, so the same seed may produce different sequences on different interpreters. Pinned test values are only guaranteed stable when running under the same interpreter (the test runner always uses `dfrotz`).

## Scoring

```
max score: 10
```

Declares the maximum possible score for the game. Defaults to 0 (unscored).

```
score + 5
score - 2
```

Increment or decrement the score from any handler.

## Player description

```
player "You look sharp and ready for adventure."
```

Sets the description shown when the player types `examine me`.

## Status line

```
status score, moves
```

Configures the right side of the status bar. Built-in slot names:

| Slot | Displays |
|---|---|
| `score` | `Score: N` |
| `moves` | `Moves: N` |
| `time` | `Time: N` |
| *any var name* | `Varname: N` |

The left side always shows the current room name. Default (when `status` is omitted) shows `Score: N  Moves: N`.

## Planned

### Language completeness
- User-defined functions — named routines callable from handlers, for shared logic (`func greet: say "Hello."`)
- Loops — `while <cond>:` and `each <obj> in <container>:` (maps to I6 `objectloop`)
- General arithmetic — full expressions in assignments and conditions (`x = a + b * 2`)
- Object iteration — `each <var> in <container>:` walks child objects at runtime

### Object model
- Class possessions — child objects automatically created per instance
- Containment queries — `count of <container>`, `first in <container>` as expressions

### Source organisation
- Multiple source files — `uses` directive (reserved but not yet emitted)
- Library imports — standard verb/class packs shared across games

### Output and presentation
- Inventory — customisable formatting of carried objects list
- Text styles — `bold`, `italic`, `reverse` for emphasis in `say` output
- Conversation topics — `ask about` / `tell about` with topic tables
- String variables — named text slots, assignable and interpolatable

### Tooling and quality
- Multi-line strings — review the preprocessor join behaviour in detail; confirm edge cases and document clearly
- Articles — audit `{a obj}`, `{an obj}`, `{the obj}` in detail: I6's `(a)` routine handles "a"/"an" automatically based on the object name, but Grue currently only recognises `a` and `the` as article keywords in interpolation, not `an`; also review how initial articles in object display names interact with I6's article system
- `on order` validation — emit a compile error when `on order` appears on a non-animate object