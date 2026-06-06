M1 — Static world ✓
Descriptor: meta, nodes (rooms + player), start
Runtime: render title/author, place player, print start room description
Demonstrable: title screen and "A plain kitchen." appear

M2 — Input loop + look ✓
Descriptor: + handlers (sigKey → fn list), + grammar, + vocab
Runtime: text input box, turn loop, trie parser, vocabulary lookup, say(), dispatch
Demonstrable: player can type look and get the room description back

M3 - if, else, unless ✓ (compiler)
Multiline Expression blocks with if, else if and else
Prefix and postfix if and unless expressions

M4 — Kinds + string interpolation ✓ (compiler)
Descriptor: + kinds
Runtime: kind state on nodes, {expr} compiled to template literals
Demonstrable: say "The lantern is {light}." prints correctly

M5 — Classes and Instances, Player, Object, filter, length
Descriptor: classes, Animals, Man, Woman, Items, Rooms, Doors, Objects
Runtime: class-level handler lookup, 

M6 - Dynamic property access ✓ (compiler + runtime)
e.g. 
say "{primes.0}"          # 2  — static, key is the literal 0
say "{primes.{i}}"        # dynamic — key is the value of i
primes.{i} = 99           # dynamic write
log.{position} = "Jason"       # dynamic write — key is value of position
log.{player.name} = 10         # dynamic write — key is player's name
log.{position} = unset         # clears the entry; key remains
say "{log.{position}}"         # dynamic read

M7 - Iterators ✓ (compiler + runtime)

M8 — handler chain
full chain: instance → class → parent → global → library
Demonstrable: a class handler fires for any instance of that class
Note: matchParam uses exact class match — see codegen_issues.md

M9 — Items + examine + take/drop ✓
Descriptor: + location/containment on nodes
Runtime: containment model, inventory, scope (what's reachable)
Demonstrable: pick up an object, examine it, drop it, very simple on examine, take and drop handlers without failure checking (e.g. object must be present)

M10 — fail / succeed / when
Runtime: chain control — fail, succeed, when token: arms, failed { }: blocks
Demonstrable: a gun that can be fired only if a magazine is loaded and it has sufficient bullets

M11 - Movement
Descriptor: Moving the player from room to room, lisiting exits in room description, moving items to the location
Demonstrable: player can move from room to room on a navigatable map.

M12 - Doors and Keys working
Descriptor: Openable, Lockable, global doors, room level doors,  2 room level doors merge if they are vis-à-vis
Demonstrable: Doors are openable, closable, lockable and unlockable, doors are unlocked with a specific key and are open & unlocked also from the other side.

M13 - Standard Object types
Descriptor: Animals, Man, Woman, Items, Rooms, Doors, Objects

M14 - Arrays
Descriptor: Arrays and lists

M15 — Standard library
Descriptor: library handlers folded into handler chains
Demonstrable: movement, inventory, examine work out of the box without author writing them

M16- Libraries
Descriptor: Containers, Supporters, etc. all libraries we want we want implemented 
Demonstrable: containers, supporters, etc. in action

M17 — Every-turn + turn ranges
Runtime: fire every-turn handlers after each turn, check turn range conditions
Demonstrable: a candle that burns down over time
Note: teatime.grue — grandmother's sitting room; fill her cup, hand it to her, she drinks it
over a few turns, hand it back empty, refill, offer biscuits in between

M18 - print evaluation (post processor): 
Inline directives: (`[nobreak]`, `[nobr]`, `[comma]`, `[the]`, `[a]`)
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

M19 Choose
Largely deprecated, decide whether we want to implement it now or something more sophisticated later

M20 Fonts
Block styles and inline styles
Descriptor: + styles
Runtime: apply CSS classes to say output spans
Demonstrable: say mono "SECTOR 7 report." renders in a monospace block

M21 Interface and Js calling

M22 stop, quit, restart

M23 — Save / load
Runtime: snapshot world state to localStorage, restore on reload
Demonstrable: close the tab, reopen, continue where you left off

M24 - Whatever is missing

M25 — HTML bundling
Go driver: inline runtime + game JS + CSS into a single .html file
Demonstrable: one file, drag into any browser, plays offline