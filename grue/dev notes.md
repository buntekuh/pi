M1 — Static world
Descriptor: meta, nodes (rooms + player), start
Runtime: render title/author, place player, print start room description
Demonstrable: title screen and "A plain kitchen." appear

M2 — Input loop + look
Descriptor: + handlers (sigKey → fn list), + grammar, + vocab
Runtime: text input box, turn loop, trie parser, vocabulary lookup, say(), dispatch
Demonstrable: player can type look and get the room description back

M3 — Objects + examine + take/drop
Descriptor: + location/containment on nodes
Runtime: containment model, inventory, scope (what's reachable)
Demonstrable: pick up an object, examine it, drop it

M4 — Kinds + string interpolation
Descriptor: + kinds
Runtime: kind state on nodes, {expr} compiled to template literals
Demonstrable: say "The lantern is {light}." prints correctly

M5 — Classes + handler chain
Descriptor: + classes
Runtime: class-level handler lookup, full chain: instance → class → parent → global → library
Demonstrable: a class handler fires for any instance of that class

M6 — Standard library
Descriptor: library handlers folded into handler chains
Demonstrable: movement, inventory, examine work out of the box without author writing them

M7 — fail / succeed / when
Runtime: chain control — fail, succeed, when token: arms, failed { }: blocks
Demonstrable: a locked door that blocks movement

M8 — Every-turn + turn ranges
Runtime: fire every-turn handlers after each turn, check turn range conditions
Demonstrable: a candle that burns down over time

M9 — Save / load
Runtime: snapshot world state to localStorage, restore on reload
Demonstrable: close the tab, reopen, continue where you left off

M10 — Styles + CSS
Descriptor: + styles
Runtime: apply CSS classes to say output spans
Demonstrable: say mono "SECTOR 7 report." renders in a monospace block

M11 — HTML bundling (Step 7)
Go driver: inline runtime + game JS + CSS into a single .html file
Demonstrable: one file, drag into any browser, plays offline