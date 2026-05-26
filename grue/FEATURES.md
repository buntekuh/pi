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
- Properties: `key: item_id`, `security: locked`, `containment: open`, `inside: room_id`

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
verb pry, tear, wrench
    * noun 'with' held
    "There's nothing to pry there."
```
- First word capitalised as action base; `held`/`'with'` in grammar appends `With`
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
- Action matched by gerund (`prying` → `pry`) against declared verbs and standard action table
- Second-noun filter: `with crowbar` → `if (second ~= crowbar) rfalse;`
- Conditionals: `if open:` / `if closed:` / `else:`
- Statements: `say "..."`, `open.`, `close.`, `go room`, `box "..."`
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
Writes a `.gts` JSON file alongside the `.inf` for use by a test runner.

## Planned
- User-defined functions — named routines callable from handlers, for shared logic
