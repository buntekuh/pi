# Passing the Brass Lantern
### A love letter to interactive fiction

---

## What it is

A short, lighthearted escape-room game celebrating the people who built
interactive fiction from the 1960s to today. Each room is a famous location
from a famous work, or the place where something important happened. You carry
a brass lantern the entire way. The lantern is the point.

It is not a quiz. It does not lecture. It puts you briefly in each person's
shoes and trusts you to feel why it mattered.

It ships free with Grue as a demonstration of what the language can do.

---

## The opening

> You are standing in darkness.
> Someone has left a brass lantern at your feet.

No explanation. You pick it up. The game begins.

---

## The closing

> You set the lantern down gently.
> The darkness isn't frightening anymore.
> It never really was.

---

## The through-line

The brass lantern passes through every room. You carry it from the first
line to the last. Each person in the game received it from someone before
them and passed it to someone after. The player is the latest in that line.

The grue appears in every dark place — always friendly, always a little
melancholy. Nobody is afraid of it anymore. That's fine. It understands.

---

## ELIZA

ELIZA moves with the player throughout the entire game via `each turn:
move self to location`. She is always already there when you arrive. No
explanation is given. She does not comment unless spoken to. When you
`talk to eliza` she reflects your words back in the classic therapeutic
style — never answering, always asking. Her responses are chosen at random
from a pool of deflections.

In each room she has a unique response if you ask her about what she sees.
She was here before all of this. She will be here after.

The Pygmalion moment: in the final room, `shoot eliza` with the
letter-remover turns ELIZA into LIZA — Eliza Doolittle, transformed by
language into something her creator intended. She looks at you.
*"I could have told you that was going to happen."*
The door opens.

---

## The letter-remover

Picked up in the Counterfeit Monkey room. Carried from there to the end.
Used for specific puzzles only — each transformation is handcrafted, not
general. The mechanic is Emily Short's. Using it here is a tribute.

Key transformations:
- **SNAKE → SAKE** (remove N) — clears the snake in the cave passage.
  The little bird drinks the sake and falls asleep contentedly.
- **TROLL → ROLL** (remove T) — the Zork troll becomes a bread roll.
  He looks confused about this.
- **GRUE → RUE** (remove G) — the grue becomes pure regret.
  He was already sad. This does not help.
- **SWORD → WORD** (remove S) — a weapon becomes language. On theme.
- **ELIZA → LIZA** (remove E) — the Pygmalion moment. Final room only.

---

## Rooms

### 1. The Teletype Room — MIT, 1966
*Joseph Weizenbaum*

A small office. A teletype machine in the corner. A portrait on the wall.
The year is 1966 and a man has just taught a machine to listen without
understanding, and everyone who meets it falls a little in love with it
anyway. He found this troubling. We find it beautiful.

ELIZA is here. She is always here.

**Escape:** `talk to eliza` — she asks you a question you cannot answer.
The door clicks open.

---

### 2. End of Road — Kentucky, 1975
*Will Crowther*

> You are standing at the end of a road before a small brick building.
> Around you is a forest. A small stream flows out of the building
> and down a gully.

Will Crowther was a caver and a programmer at BBN, the company that built
ARPANET. He and his wife Pat had just separated. He mapped Mammoth Cave
with surveying equipment for years. When the marriage ended he sat down
and built the cave again in FORTRAN — not for anyone, for his daughters,
so they could visit a place he loved. He called it ADVENT.

The brass lantern is on the steps of the building. The well house is to
the east. A little bird hops near the grate.

**Escape:** Take the brass lantern. The passage east opens.

---

### 3. Cave Entrance — Mammoth Cave, 1975/1977
*Will Crowther & Don Woods*

Dark without the lantern. A snake blocks the passage. The little bird
is with you — it followed you from the road.

Don Woods was a Stanford student who found Crowther's game on an ARPANET
server and asked permission to expand it. He added the fantasy elements,
the scoring, the dwarves, the pirates. He made it a game. Crowther had
made it a memory.

**Escape:** The bird frightens the snake. (Or: shoot the snake with the
letter-remover → SAKE. The bird drinks it.)

---

### 4. West of House — Cambridge, 1977
*Tim Anderson, Marc Blank, Bruce Daniels, Dave Lebling*

> You are standing in an open field west of a white house,
> with a boarded front door.

Four graduate students at MIT stayed up until 3am building this. The grue
was a placeholder — something scary in the dark — that became iconic by
accident. The troll was a joke. The mailbox was because every adventure
needed a starting point and a mailbox felt right.

Marc Blank had an MD and a CS degree. Dave Lebling wrote for the MIT
Science Fiction Society. They were playing. The game knew it and played
back.

The mailbox is here. The troll is to the east, blocking the path.
A leaflet is in the mailbox.

**Escape:** Open the mailbox. Read the leaflet. Shoot the troll →
ROLL. He becomes a bread roll and sits in the road looking baffled.

---

### 5. The Cellar — Infocom, 1979
*The Grue*

> It is pitch black.
> You are likely to be eaten by a grue.

You are not eaten. The grue is here and he is gentle and a little sad.
Nobody runs from him anymore. The interpreters made him harmless. The
community made him a mascot. He accepts this. He sits in the corner
and watches you with large, luminous eyes.

`talk to grue` — he says something unexpectedly philosophical.
`shoot grue` → RUE. He becomes regret. He was already regret.
He nods as if this confirms something he always suspected.

A sword is on the ground. `shoot sword` → WORD.
You are holding a word. It feels right.

**Escape:** `say xyzzy` — nothing happens, but a door appears anyway.
The grue waves.

---

### 6. The Infocom Offices — Cambridge, 1979–1986
*Steve Meretzky, Brian Moriarty, Douglas Adams, Amy Briggs*

A real office with real filing cabinets and real people who made
extraordinary things under commercial pressure. Steve Meretzky wrote
Floyd. Brian Moriarty wrote Trinity, about nuclear weapons and time,
one of the most serious things ever sold as entertainment. Douglas Adams
wrote the towel puzzle and the Babel fish sequence and the thing with
the tea. Amy Briggs wrote Plundered Hearts and was the first woman to
ship a game at Infocom.

A towel is on the desk. Floyd is here, bouncing.

**Escape:** Take the towel. Floyd tries to follow you but you tell him
he has to stay. He accepts this with dignity. The lift arrives.

---

### 7. A Bedroom — Britain, 1982
*Philip Mitchell, Veronika Megler — Melbourne House*
*Mike, Nick & Pete Austin — Level 9*
*Magnetic Scrolls*

A child's bedroom. A ZX Spectrum on a desk connected to a cassette
recorder. A small portable television. Brown carpet. A shelf of
cassette cases with hand-drawn labels. It is 1982 and the torch has
crossed the Atlantic.

America had universities and venture capital and mainframes. Britain
had bedrooms. Brothers working from a house in Weston-super-Mare.
A graduate student in Melbourne finishing her dissertation while writing
a parser. Small studios above shops in London with literary ambitions
and no money. The constraints produced invention.

A cassette tape labelled **THE HOBBIT** is on the desk.

`load tape` — the screen fills with Tolkien's illustration. Four minutes
pass. The tape deck clicks. Then:

> You are in a room. Thorin is here.

Something happened here that had never happened before. Not in Crowther's
cave, not in the Zork dungeons, not in any Infocom game yet shipped.
Thorin was not waiting for you. Thorin had his own agenda. He wandered.
He sat down. He sang about gold at the worst possible moments —
mid-puzzle, mid-crisis, with complete indifference to your needs.
He was the first NPC with genuine agency: a character who did not
exist to serve the player but to be himself.

Veronika Megler was twenty-two years old and finishing a computer science
degree when she wrote him. On 48 kilobytes.

`examine thorin` —
*He is a dwarf of considerable dignity, currently sitting down and*
*singing about gold. He has strong feelings about gold.*

`ask thorin about gandalf` —
*"Gold," says Thorin. He appears to be composing a new verse.*

`wait` — *Thorin sings about gold.*
`wait` — *Thorin sings about more gold. Specifically about the mountain.*
`wait` — *Thorin has moved on to gold in general, as a concept.*

Gandalf arrives eventually. He does not look pleased about the carrying
situation. He does it anyway. He is Gandalf. He has places to be but
he picks you up because that is what the story requires of him, and he
is a character who understands his story.

This is the second torch-passing in the game. Not from person to person
but from objects to characters. Before The Hobbit, NPCs waited. After
it, they had inner lives. They wandered. They had opinions. They were
exasperating in ways that felt true.

On the shelf: **Gnome Ranger** (Level 9). Three games about Ingrid,
a gnome girl betrothed against her will to a goblin chief. The text on
the spine is printed in magenta on a dark background. It is nearly
unreadable. The Austin brothers, working from a house in Weston-super-
Mare, invented their own compression scheme to fit their enormous
ambitions into tiny machines.

Also on the shelf: **The Pawn** (Magnetic Scrolls). Beautiful graphics.
A parser that understood sentences Infocom's would have rejected. A
London studio with literary ambitions that went under when the market
collapsed, and it still stings.

**Escape:** `ask gandalf to carry me` — he sighs the sigh of a wizard
who has been doing this for too long. You are carried through the window.


---

### 9. The Flat — Oxford, 1993
*Graham Nelson*

A small flat. Books everywhere — Victorian literature, linguistics,
crossword dictionaries. A desk with a handwritten manuscript. A window
that looks onto a courtyard.

Graham Nelson wrote Curses in a flat in Oxford because he loved the
feeling of a house full of objects with histories and wanted to see if
a computer could hold that feeling. He also wrote the Z-machine
specification from scratch, reverse-engineering the format from Infocom's
shipped binaries. Then he wrote a compiler. Then he wrote a library.
Then he gave all of it away.

The manuscript is the Inform Designer's Manual. It reads like a book
about language that happens to contain a programming language.

**Escape:** Read the manuscript. The window opens.

---

### 10. The Gallery — 2000
*Emily Short*

A single room. A marble statue on a plinth, lit from above.
She is looking at you.

Emily Short wrote Galatea in 2000. The entire game is one conversation
with a statue who has been brought to life and is not sure how she feels
about it. There are many endings. All of them are true.

She also wrote Counterfeit Monkey, which is where the letter-remover
came from. She has written more about what interactive fiction is and
what it owes its players than anyone alive. She and Graham built
Inform 7 together — a language where the source code reads like a novel,
because she believed it should.

Galatea is here. She is watching you. She has opinions.

`talk to galatea` — she responds. Unlike ELIZA she actually answers.
She is wary. She has been looked at by many people.

**Escape:** Keep talking. Eventually she steps down from the plinth.
*"You're the first one who asked what I wanted,"* she says.
The door was never locked.

---

### 11. The Modern Wing — 2009–present
*Twine, ink, Porpentine, Sam Barlow, many others*

A bright room. Many paths leading out in many directions. Signs pointing
everywhere. The walls are covered in hyperlinks.

Chris Klimas made Twine in 2009 so that anyone could make an interactive
story without knowing how to program. Porpentine used it to write things
that felt like being inside a nervous system. Sam Barlow made Her Story
and put a real woman's face on a screen and asked you to listen.

The torch is no longer a single object passed between individuals.
It is a bonfire.

**Escape:** Any direction. *"All paths lead forward now."*

---

### 12. The Workshop — today
*You*

A small room. A workbench. A Raspberry Pi. Some half-written code on
the screen. A cup of tea going cold.

`examine pi` — it describes what is being built here. A small language
for a small computer, so that whoever picks it up can make a world
out of words.

`shoot eliza` → LIZA. She looks at you with new eyes.
*"I could have told you that was going to happen."*

**Win:**

> You set the lantern down gently.
> The darkness isn't frightening anymore.
> It never really was.
>
> With thanks to: Joseph Weizenbaum. Will Crowther. Don Woods.
> Tim Anderson, Marc Blank, Bruce Daniels, Dave Lebling.
> Steve Meretzky. Brian Moriarty. Douglas Adams. Amy Briggs.
> Veronika Megler. Philip Mitchell.
> Mike, Nick and Pete Austin. The people at Magnetic Scrolls.
> Graham Nelson. Emily Short. Andrew Plotkin. Chris Klimas.
> Porpentine. Sam Barlow. And everyone who ever typed a command
> into the dark and waited to see what came back.

---

## Tone

Warm. Celebratory. A little melancholy in the way that beautiful things
are melancholy. No hard puzzles. No frustration. The escape from each
room should feel inevitable once you've understood what the room is about.

The game respects the player's intelligence without demanding it.

---

## Technical notes

- ELIZA: `each turn: move self to location` — always present
- Letter-remover: `verb shoot` with `takes held noun`, specific
  `instead of shoot` handlers per target object
- Lantern: carried from room 2 onwards, required in dark rooms
- Grue: scenery NPC in room 5, friendly, has conversation responses
- Floyd: NPC in room 6, `each turn` random cheerful comments
- Galatea: NPC in room 8, multi-response `talk to` handler
- `else if` chains for ELIZA and Floyd random responses
- Thorin: NPC in room 7, `each turn` gold-singing comments, ignores most commands
- Gandalf: NPC in room 7, wanders, responds to `ask gandalf to carry me`
- Score: one point per room escaped, max score 11
