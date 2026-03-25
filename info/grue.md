# Grue — Adventure Game Language

Grue is a small declarative language for writing text adventure games on the
M56. It compiles to Pi-Forth. For logic too complex to express in Grue, drop
down to Pi-Forth directly.

The name comes from the darkness creature in Zork.


## Declarations

### Rooms

    Kitchen is a room.
    "Description text, shown when the player enters or looks."

### Objects

    Pan "Cast-iron skillet, perfect for roasting herring" is a surface.
    Pot "A battered metal pot" is a container.
    Red Herring "Suspiciously fishy" is here.

`is here` places the object in the most recently declared room.

Object types:

| Type          | Meaning                                  |
|---------------|------------------------------------------|
| `is a surface`    | things can be placed on it           |
| `is a container`  | things can be placed inside it (TBD) |
| `is a door`       | blocks passage between two rooms     |

### NPCs

    Auntie "Description text." pronoun is she.

Pronouns: `he`, `she`, `they`.

### Directions

    Kitchen is east of Dining Hall.
    Kitchen is west of Back Porch.

Standard directions: `north`, `south`, `east`, `west`, `up`, `down`.

### Doors

    Scullery Door "A low door with a crooked frame" is a door.
    Scullery Door is between Kitchen and Back Porch.
    Scullery Door is close.

Doors are special objects that block passage between their two rooms when
close. The engine handles the default behaviour automatically:

- `go west` while door is close → "The Scullery Door is close."
- `open Scullery Door` → door becomes open, "Opened."
- `close Scullery Door` → door becomes close, "Closed."
- `examine Scullery Door` → prints its description

Only write a handler to override the default or add side effects.


## State

Object state uses present-tense adjectives:

    Scullery Door is close.
    Scullery Door is open.
    Red Herring is nowhere.     -- removed from the world
    Lamp is on.
    Lamp is off.

Custom properties can be declared and tested freely.


## Verb patterns

Declare the grammar your game understands:

    verb (wait, look)
    verb object (eat, examine, take, drop)
    verb preposition object (listen to, look at)
    verb object preposition object (put key in lock)
    verb string (say "hello")
    verb preposition object string (say to Auntie "sit down")

The engine provides default handling for `look`, `examine`, `take`, `drop`,
`go <direction>`, `open`, `close`. Declare only what you need to override or
extend.


## Handlers

A handler signature is the player command verbatim — same words, same tense.

    eat Red Herring:
        "Tastes of regret and low tide."
        Red Herring is nowhere.
    end

    say to Auntie "sit down":
        "She fixes you with a stare that could curdle milk."
    end

    go north:
        "A strange force prevents you from leaving."
    end

Handlers fire instead of the default engine behaviour. If no handler exists
the engine falls back to its default (or "You can't do that.").


## Conditions

    if Red Herring is nowhere:
        "There is no herring here."
    elsif Red Herring is here:
        "You reluctantly eat it."
    else:
        "Something has gone wrong."
    end


## Escaping to Pi-Forth

For anything Grue cannot express — counters, puzzles with complex state,
procedural text — embed Pi-Forth directly:

    examine Pot:
        forth: pot-examine-counter 1 + dup pot-examine-counter !
               3 = if "You really like this pot." then ;forth
    end

Everything inside `forth: ... ;forth` is passed through to the Pi-Forth
compiler unchanged.


## What is deferred

- Containment (`put X in Y`, `take X from Y`)
- Darkness and light sources
- Conversation trees
- Saving and restoring
