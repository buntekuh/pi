"""
grui — Grue interpreter
=======================
Loads a .grue source file and runs the game directly, with no compilation step.

Data flow
---------
                     .grue file
                         │
                      Parser
                         │  builds a World (rooms, objects, handlers)
                         ▼
                    Interpreter
                    ┌──────────────────────────────────────────────┐
   _input(prompt) ──┤  game loop  ──► InputParser ──► action verb  │
                    │                                               │
                    │  verb handler ──► _say / _print               │──► _output(text)
                    │                                               │
                    │  turn handlers (on turn: / on turn N:)        │
                    └──────────────────────────────────────────────┘

When running inside the M56 emulator (m56.sys_grui):
  _input   = lambda _: terminal.read_line()   # blocks until Enter
  _output  = terminal.receive({'type':'print','text':...})
  status_fn = terminal.receive({'type':'status', ...})

The T46 terminal handles all cursor movement, line-wrapping, and scrolling;
grui only emits plain text with '\n' line endings.

Sentence types supported
------------------------
  go <dir>          cardinal movement (north/south/east/west/up/down, abbrevs)
  take <thing>      pick up a takeable object
  drop <thing>      put down a carried object
  examine <thing>   read an object's description
  talk to <person>  fire that NPC's talk handler
  inventory         list carried objects
  wait              advance time one turn
  look              redescribe the current room
  help / ?          print the verb table
  quit / q          end the game
"""

import re
import sys
import textwrap
from pathlib import Path


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class GrueError(Exception):
    """Raised for .grue parse errors (bad syntax, missing rooms, etc.)."""
    pass


# ---------------------------------------------------------------------------
# World model
# ---------------------------------------------------------------------------

class World:
    """
    Live world state built by the Parser and mutated by the Interpreter.

    Rooms are stored in a dict keyed by normalised (lower-case) name so
    exit destinations in the .grue file are looked up case-insensitively.

    Objects are a flat list; each object carries a 'location' field that
    is either a room name or the string 'player' (in inventory).  This
    makes it trivial to enumerate scope: objects whose location matches
    the current room name, or equals 'player'.

    Handler structure stored on each room dict
    ------------------------------------------
    room['handlers'] is a list of handler dicts:

      turn        — fires every turn (the 'on turn:' block)
      turn_n      — fires once when turn_counter == n ('on turn N:')
      talk        — fires when the player talks to a named NPC
      take        — fires after the player successfully takes a named object
      examine     — fires when the player examines a named object
      instead_go  — intercepts ALL movement; normal go does not execute
      instead_take— intercepts take of a named object; normal take skipped
      ignore      — placeholder for unrecognised 'on ...:' headers

    Handler body statements:
      ('say',    text)             — print a line to the player
      ('create', kind, name, desc) — add a new object to the current room
    """

    def __init__(self):
        self.kinds          = {}   # kind-name → [value, ...] from 'kind X: a b c'
        self.rooms          = {}   # normalised-name → room dict
        self.room_order     = []   # room keys in declaration order (first = start)
        self.objects        = []   # all object instances (rooms + inventory)
        self.player         = {}   # name, location, description, properties
        self._next_obj_id   = 0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def norm(self, name: str) -> str:
        """Normalise a room name for dict lookup (strip + lower-case)."""
        return name.strip().lower()

    def room_by_name(self, name: str):
        """Return the room dict for 'name', or None if not found."""
        return self.rooms.get(self.norm(name))

    def current_room(self):
        """Return the room dict the player is currently in."""
        return self.room_by_name(self.player['location'])

    def objects_in(self, location: str):
        """All objects whose location matches 'location' (room name)."""
        loc = self.norm(location)
        return [o for o in self.objects if self.norm(o['location']) == loc]

    def objects_in_scope(self):
        """
        Objects visible to the player: current room + carried inventory.
        Used when resolving nouns for examine, talk, drop, etc.
        """
        room = self.norm(self.player['location'])
        return [o for o in self.objects
                if self.norm(o['location']) == room
                or o['location'] == 'player']

    def add_object(self, kind: str, name: str, description: str, location: str):
        """
        Create a new object and add it to the world.

        'takeable' is False for living beings (woman, man, crow, fae, tree,
        stork, being, and anything listed under 'kind being:').  Everything
        else is takeable.

        'words' is the set used for noun matching: all words in the object's
        name plus the kind itself (so 'shawl' matches any shawl by kind word).
        """
        living_kinds = {'woman', 'man', 'crow', 'fae', 'tree', 'stork', 'being'}
        # Also treat any value listed under 'kind being:' as a living kind.
        living_from_kinds = set()
        if 'being' in self.kinds:
            living_from_kinds = set(self.kinds['being'])
        takeable = (kind not in living_kinds) and (kind not in living_from_kinds)
        words = set(name.lower().split()) | {kind.lower()}
        obj = {
            'id':          self._next_obj_id,
            'kind':        kind,
            'name':        name,
            'words':       words,       # word set for noun matching
            'location':    location,    # room name or 'player'
            'description': description,
            'takeable':    takeable,
        }
        self._next_obj_id += 1
        self.objects.append(obj)
        return obj


# ---------------------------------------------------------------------------
# Parser — populates a World from .grue source
# ---------------------------------------------------------------------------

class Parser:
    """
    Parse a .grue source file into a World.

    The .grue format is indent-significant:

      indent 0   — top-level declarations:
                     kind being  tree fae crow woman man
                     player "Name"
                     room "Name"

      indent 2   — room body:
                     "Room description"
                     north "Side Street"        -- exit (direction word, no colon needed)
                     climb: "Tower"             -- non-standard exit (colon required)
                     object "red Apple"
                     woman "Merchant" "desc"
                     on turn:                   -- handler header (colon required)
                     on talk to "Merchant":

      indent 4   — handler body:
                     say "text"
                     crow "Norbert" "desc"      -- dynamic object creation

    Colons are required only on handler headers ('on ...:').
    Exit declarations use direction-word lookup instead of a colon.
    kind and player property lines accept colons for backwards compatibility
    but do not require them.

    Comments start with '--' and are stripped during parsing.
    Multi-line quoted strings (odd number of '"' on a line) are joined by
    the preprocessor before the main parse loop runs.
    """

    # ---- preprocess: collapse multiline quoted strings ----

    @staticmethod
    def _preprocess(source: str) -> str:
        """
        Join lines that contain an unclosed quoted string.
        A line with an odd number of '"' characters has an open quote; keep
        appending continuation lines until the count becomes even again.
        Comments and blank lines are passed through unchanged.
        """
        lines = source.splitlines()
        out   = []
        i     = 0
        while i < len(lines):
            line     = lines[i]
            stripped = line.strip()
            if stripped.startswith('--') or not stripped:
                out.append(line)
                i += 1
                continue
            if stripped.count('"') % 2 == 1:
                # Open quote — accumulate continuation lines.
                joined = line.rstrip()
                i += 1
                while i < len(lines):
                    cont   = lines[i].strip()
                    joined += ' ' + cont
                    i     += 1
                    if joined.count('"') % 2 == 0:
                        break
                out.append(joined)
            else:
                out.append(line)
                i += 1
        return '\n'.join(out)

    @staticmethod
    def _extract_string(s: str) -> str:
        """Extract the content of the outermost "..." pair."""
        s = s.strip()
        m = re.match(r'"(.*)"', s)
        if m:
            return m.group(1)
        raise GrueError(f'expected quoted string, got: {s!r}')

    # ---- handler header patterns ----
    # Each pattern matches one of the supported 'on ...:' header forms.
    _RE_ON_TURN_N   = re.compile(r'on\s+turn\s+(\d+)\s*:')
    _RE_ON_TURN     = re.compile(r'on\s+turn\s*:')
    _RE_ON_TALK     = re.compile(r'on\s+talk\s+to\s+"([^"]+)"\s*:')
    _RE_ON_TAKE     = re.compile(r'on\s+take\s+"([^"]+)"\s*:')
    _RE_ON_EXAMINE  = re.compile(r'on\s+examine\s+"([^"]+)"\s*:')
    _RE_INSTEAD_GO  = re.compile(r'instead\s+of\s+go\s*:')
    _RE_INSTEAD_TAKE= re.compile(r'instead\s+of\s+take\s+"([^"]+)"\s*:')
    _RE_ON_OTHER    = re.compile(r'on\s+.+:')   # catch-all: unrecognised headers

    def parse(self, source: str) -> World:
        """
        Parse 'source' and return a populated World.
        The first 'room' declaration in the file becomes the player's start room.
        """
        world  = World()
        source = self._preprocess(source)
        lines  = source.splitlines()

        current_room    = None   # room dict currently being parsed
        current_handler = None   # body list of the handler currently being parsed

        for raw in lines:
            stripped = raw.strip()
            indent   = len(raw) - len(raw.lstrip())

            if not stripped or stripped.startswith('--'):
                continue

            # ---- indent 0: top-level declarations -----------------------
            if indent == 0:
                # Leaving any room or handler context.
                current_handler = None
                current_room    = None

                if stripped.startswith('kind '):
                    # 'kind mood lost curious bold' → kinds['mood'] = ['lost','curious','bold']
                    # Colon after the kind name is accepted but not required.
                    m = re.match(r'kind\s+(\w+):?\s*(.*)', stripped)
                    if m:
                        world.kinds[m.group(1)] = m.group(2).split()

                elif stripped.startswith('player '):
                    # 'player "Newcomer"' — sets player name; properties follow at indent 2.
                    m = re.match(r'player\s+"([^"]+)"', stripped)
                    if m:
                        world.player = {
                            'name':        m.group(1),
                            'location':    '',   # set when first room is parsed
                            'description': '',
                            'properties':  {},
                        }

                elif stripped.startswith('room '):
                    # 'room "Market Square"' — create a new room dict.
                    m = re.match(r'room\s+"([^"]+)"', stripped)
                    if not m:
                        raise GrueError(f'bad room header: {stripped!r}')
                    rname = m.group(1)
                    rkey  = world.norm(rname)
                    current_room = {
                        'name':         rname,
                        'desc':         '',
                        'exits':        {},       # direction → room name
                        'handlers':     [],
                        'turn_counter': 0,        # incremented each turn player spends here
                    }
                    world.rooms[rkey] = current_room
                    world.room_order.append(rkey)
                    # The first room declared is where the player starts.
                    if not world.player.get('location'):
                        world.player['location'] = rname

            # ---- indent 2: inside player block --------------------------
            elif indent == 2 and world.player and not current_room:
                # Player properties: 'being tree' or 'being: tree' (colon optional).
                # A quoted string at this indent is the player description.
                if stripped.startswith('"'):
                    world.player['description'] = self._extract_string(stripped)
                else:
                    m = re.match(r'(\w+):?\s*(\S+)', stripped)
                    if m:
                        world.player['properties'][m.group(1)] = m.group(2)

            # ---- indent 2: inside room ----------------------------------
            elif indent == 2 and current_room is not None:
                current_handler = None   # handler context resets for each room-level line

                # Room description (quoted string at indent 2).
                if stripped.startswith('"'):
                    current_room['desc'] = self._extract_string(stripped)
                    continue

                # Exit declaration: 'north "Side Street"' or 'north: "Side Street"'
                # A line with a single quoted string at the end is an exit if the
                # first word is a known direction, or if it has a colon (for
                # non-standard exits like 'climb: "Tower"').
                # The '\s*$' anchor prevents matching object declarations that
                # have a second quoted string (e.g. 'woman "Merchant" "desc"').
                m = re.match(r'(\w+)\s*:?\s*"([^"]+)"\s*$', stripped)
                if m:
                    word = m.group(1)
                    has_colon = bool(re.match(r'\w+\s*:', stripped))
                    if word in DIRECTIONS or has_colon:
                        current_room['exits'][word] = m.group(2)
                        continue

                # Handler headers — each opens a new handler body list.
                m = self._RE_ON_TURN_N.match(stripped)
                if m:
                    h = {'type': 'turn_n', 'n': int(m.group(1)), 'body': [], 'fired': False}
                    current_room['handlers'].append(h)
                    current_handler = h['body']
                    continue

                if self._RE_ON_TURN.match(stripped):
                    h = {'type': 'turn', 'body': []}
                    current_room['handlers'].append(h)
                    current_handler = h['body']
                    continue

                m = self._RE_ON_TALK.match(stripped)
                if m:
                    h = {'type': 'talk', 'target': m.group(1), 'body': []}
                    current_room['handlers'].append(h)
                    current_handler = h['body']
                    continue

                m = self._RE_ON_TAKE.match(stripped)
                if m:
                    h = {'type': 'take', 'target': m.group(1), 'body': []}
                    current_room['handlers'].append(h)
                    current_handler = h['body']
                    continue

                m = self._RE_ON_EXAMINE.match(stripped)
                if m:
                    h = {'type': 'examine', 'target': m.group(1), 'body': []}
                    current_room['handlers'].append(h)
                    current_handler = h['body']
                    continue

                if self._RE_INSTEAD_GO.match(stripped):
                    h = {'type': 'instead_go', 'body': []}
                    current_room['handlers'].append(h)
                    current_handler = h['body']
                    continue

                m = self._RE_INSTEAD_TAKE.match(stripped)
                if m:
                    h = {'type': 'instead_take', 'target': m.group(1), 'body': []}
                    current_room['handlers'].append(h)
                    current_handler = h['body']
                    continue

                if self._RE_ON_OTHER.match(stripped):
                    # Unrecognised handler — parse body silently and discard it.
                    h = {'type': 'ignore', 'body': []}
                    current_room['handlers'].append(h)
                    current_handler = h['body']
                    continue

                # Object declarations: '<kind> "Name"' or '<kind> "Name" "Description"'
                # e.g. 'woman "Merchant" "A sharp-eyed fae woman."'
                m = re.match(r'(\w+)\s+"([^"]+)"(?:\s+"([^"]*)")?', stripped)
                if m:
                    kind = m.group(1)
                    name = m.group(2)
                    desc = m.group(3) or ''
                    world.add_object(kind, name, desc, current_room['name'])
                    continue

            # ---- indent 4: handler body ---------------------------------
            elif indent == 4 and current_handler is not None:
                # Handler body lines: 'say "text"' or '<kind> "Name" "Description"'.
                if stripped.startswith('say '):
                    text = self._extract_string(stripped[4:])
                    current_handler.append(('say', text))
                    continue

                # Object creation inside a handler (e.g. 'crow "Norbert" "..."').
                m = re.match(r'(\w+)\s+"([^"]+)"\s+"([^"]*)"', stripped)
                if m:
                    kind = m.group(1)
                    if re.match(r'^[a-z]\w*$', kind) and kind != 'say':
                        current_handler.append(('create', kind, m.group(2), m.group(3)))
                        continue

                # Bare object creation with no description.
                m = re.match(r'(\w+)\s+"([^"]+)"', stripped)
                if m and re.match(r'^[a-z]\w*$', m.group(1)) and m.group(1) != 'say':
                    current_handler.append(('create', m.group(1), m.group(2), ''))
                    continue

        return world


# ---------------------------------------------------------------------------
# Input parser — player text -> action tuple
# ---------------------------------------------------------------------------

DIRECTIONS = {
    # Full names
    'north': 'north', 'south': 'south', 'east': 'east', 'west': 'west',
    'up': 'up', 'down': 'down',
    'northeast': 'northeast', 'northwest': 'northwest',
    'southeast': 'southeast', 'southwest': 'southwest',
    # One-letter abbreviations
    'n': 'north', 's': 'south', 'e': 'east', 'w': 'west',
    'u': 'up', 'd': 'down',
    # Two-letter diagonal abbreviations
    'ne': 'northeast', 'nw': 'northwest', 'se': 'southeast', 'sw': 'southwest',
}

# Articles stripped before noun matching so 'take the apple' = 'take apple'.
ARTICLES = {'a', 'an', 'the'}


class InputParser:
    """
    Translate a raw player input string into a typed action tuple.

    The returned tuple's first element is the action kind; subsequent
    elements are kind-specific data:

      ('go',         direction_str)    — canonical direction name
      ('go_where',)                    — 'go' with no/unknown direction
      ('take',       noun_words)       — list of noun words (articles removed)
      ('take_what',)                   — 'take' with no noun
      ('drop',       noun_words)
      ('drop_what',)
      ('examine',    noun_words)
      ('examine_what',)
      ('talk',       noun_words)       — NPC name words
      ('talk_to_what',)
      ('inventory',)
      ('wait',)
      ('look',)
      ('player_desc',)                 — 'x me' / 'x i'
      ('quit',)
      ('help',)
      ('empty',)                       — blank input
      ('unknown',    raw_string)       — not understood
    """

    def _strip_articles(self, words):
        """Remove articles from a word list."""
        return [w for w in words if w not in ARTICLES]

    def parse(self, line: str):
        words = line.lower().split()
        if not words:
            return ('empty',)

        # A bare direction word is shorthand for 'go <direction>'.
        if words[0] in DIRECTIONS and len(words) == 1:
            return ('go', DIRECTIONS[words[0]])

        verb = words[0]
        rest = words[1:]

        # 'go north' / 'go n' etc.
        if verb == 'go':
            if not rest:
                return ('go_where',)
            d = self._strip_articles(rest)
            if d and d[0] in DIRECTIONS:
                return ('go', DIRECTIONS[d[0]])
            return ('go_where',)

        # 'take' / 'get' / 'grab' — synonyms for picking something up.
        if verb in ('take', 'get', 'grab'):
            noun = self._strip_articles(rest)
            if not noun:
                return ('take_what',)
            return ('take', noun)

        # 'pick up <noun>'
        if verb == 'pick' and rest and rest[0] == 'up':
            noun = self._strip_articles(rest[1:])
            if not noun:
                return ('take_what',)
            return ('take', noun)

        # 'drop' / 'put down'
        if verb == 'drop':
            noun = self._strip_articles(rest)
            if not noun:
                return ('drop_what',)
            return ('drop', noun)

        if verb == 'put' and rest and rest[0] == 'down':
            noun = self._strip_articles(rest[1:])
            if not noun:
                return ('drop_what',)
            return ('drop', noun)

        # 'examine' / 'x' / 'inspect' / 'look at'
        if verb in ('examine', 'inspect', 'x'):
            noun = self._strip_articles(rest)
            if not noun:
                return ('examine_what',)
            # 'x me' / 'x i' → show the player's own description.
            if noun in (['me'], ['i']):
                return ('player_desc',)
            return ('examine', noun)

        if verb == 'look':
            if rest and rest[0] == 'at':
                noun = self._strip_articles(rest[1:])
                if not noun:
                    return ('look',)
                return ('examine', noun)
            return ('look',)

        if verb == 'l' and not rest:
            return ('look',)

        # 'talk to X' / 'speak with X' / 'ask X'
        if verb in ('talk', 'speak'):
            if rest and rest[0] in ('to', 'with'):
                noun = self._strip_articles(rest[1:])
            else:
                noun = self._strip_articles(rest)
            if not noun:
                return ('talk_to_what',)
            return ('talk', noun)

        if verb == 'ask':
            noun = self._strip_articles(rest)
            if not noun:
                return ('talk_to_what',)
            return ('talk', noun)

        # 'inventory' / 'i' / 'inv'
        if verb in ('inventory', 'i', 'inv') and not rest:
            return ('inventory',)

        # 'wait' / 'z'
        if verb in ('wait', 'z') and not rest:
            return ('wait',)

        # 'quit' / 'q'
        if verb in ('quit', 'q') and not rest:
            return ('quit',)

        # 'help' / '?'
        if verb in ('help', '?') and not rest:
            return ('help',)

        return ('unknown', line.strip())


# ---------------------------------------------------------------------------
# Interpreter — game loop
# ---------------------------------------------------------------------------

class Interpreter:
    """
    Run the interactive game loop against a populated World.

    All I/O is injected at construction time so the interpreter is
    testable without a terminal:

      output    — callable(str): receives raw text with '\n' line endings.
                  In the M56 emulator this is terminal.receive({'type':'print',...}).
                  In tests / plain CLI this is sys.stdout.write.

      input_fn  — callable(prompt) → str: returns one line of player input
                  (without the trailing newline).
                  In the M56 emulator this blocks until the user presses Enter
                  (T46.read_line).  Raises EOFError or KeyboardInterrupt to stop
                  the game (EOF = script ended, KeyboardInterrupt = Ctrl-Q).

      status_fn — callable(room_name, exits_list) | None: called after the
                  initial room display and after every successful 'go'.
                  In the M56 emulator this sends a {'type':'status',...} command
                  to T46, which draws the two-row status bar at rows 23-24
                  without disturbing the scroll region.
    """

    # Maximum line width for word-wrapped output.
    WRAP = 72

    def __init__(self, world: World,
                 output=None, input_fn=None, status_fn=None):
        self.world      = world
        self._output    = output  or (lambda s: print(s, end=''))
        self._input     = input_fn or input
        self._parser    = InputParser()
        self._status_fn = status_fn
        self._running   = True

    # ------------------------------------------------------------------
    # Output helpers
    # ------------------------------------------------------------------

    def _say(self, text: str):
        """
        Print a game message to the player.
        Empty text emits a blank line.  Non-empty text is word-wrapped at
        WRAP columns; each wrapped line is followed by '\n'.
        All output goes through self._output.
        """
        if not text:
            self._output('\n')
            return
        for line in textwrap.wrap(text, self.WRAP):
            self._output(line + '\n')

    def _print(self, text: str):
        """Raw output — no wrapping, no added newline.  Used for the '> ' prompt."""
        self._output(text)

    # ------------------------------------------------------------------
    # Noun matching
    # ------------------------------------------------------------------

    def _match_objects(self, noun_words, candidates):
        """
        Return every object in 'candidates' whose word set is a superset of
        'noun_words'.  Both noun and object words are already lower-case.

        Examples:
          noun_words=['red','apple'] matches only the red apple (exact subset).
          noun_words=['apple']       matches red apple AND green apple
                                     → disambiguation needed.
          noun_words=['shawl']       matches all shawls by kind word.
        """
        noun_set = set(noun_words)
        return [o for o in candidates if noun_set <= o['words']]

    def _resolve_noun(self, noun_words, candidates):
        """
        Resolve noun_words to a single object from candidates.

        Returns (object, None) on success.
        Returns (None, error_string) on failure:
          — no match → "You don't see that here."
          — multiple matches → "Please be more specific — Apple, Apple." listing names.

        Disambiguation does NOT loop back for more input; the player must
        re-enter the full command with a more specific noun.
        """
        matches = self._match_objects(noun_words, candidates)
        if not matches:
            return None, "You don't see that here."
        if len(matches) == 1:
            return matches[0], None
        names = ', '.join(o['name'] for o in matches)
        return None, f'Please be more specific — {names}.'

    # ------------------------------------------------------------------
    # Handler execution
    # ------------------------------------------------------------------

    def _run_body(self, body):
        """
        Execute a handler body: a list of ('say', text) and
        ('create', kind, name, desc) statements.
        'create' adds the object to the current room.
        """
        for stmt in body:
            if stmt[0] == 'say':
                self._say(stmt[1])
            elif stmt[0] == 'create':
                _, kind, name, desc = stmt
                room = self.world.current_room()
                if room:
                    self.world.add_object(kind, name, desc, room['name'])

    def _find_handler(self, room, htype, target=None):
        """
        Find the first handler of type 'htype' in 'room'.
        If 'target' is given, also match on h['target'] (case-insensitive).
        Returns the handler dict, or None if not found.
        """
        for h in room['handlers']:
            if h['type'] != htype:
                continue
            if target is not None:
                if h.get('target', '').lower() != target.lower():
                    continue
            return h
        return None

    # ------------------------------------------------------------------
    # Status bar
    # ------------------------------------------------------------------

    def _update_status(self):
        """
        Push current room name and exits to the status_fn.
        Called after the initial room display and after every successful go.
        Does nothing if no status_fn was provided (plain CLI mode).
        In M56/T46 mode, status_fn enqueues a {'type':'status',...} command;
        T46 draws rows 23-24 in the main thread without touching the scroll region.
        """
        if self._status_fn is None:
            return
        room = self.world.current_room()
        if room:
            self._status_fn(room['name'], list(room['exits'].keys()))

    # ------------------------------------------------------------------
    # Room display
    # ------------------------------------------------------------------

    def _describe_room(self, room):
        """
        Print the full room description block:
          Room Name
          (blank line)
          Room description (word-wrapped).
          (blank line)
          'There is a X here.' for each takeable object present.
          (blank line)
          'Exits: north, east.'
        """
        self._say(room['name'])
        self._output('\n')
        if room['desc']:
            self._say(room['desc'])
        # List takeable objects (living beings are not listed).
        objs = [o for o in self.world.objects_in(room['name']) if o['takeable']]
        if objs:
            self._output('\n')
            for o in objs:
                self._say(f'There is a {o["name"]} here.')
        # List exits.
        exits = list(room['exits'].keys())
        if exits:
            self._output('\n')
            self._say('Exits: ' + ', '.join(exits) + '.')
        else:
            self._output('\n')
            self._say('There are no obvious exits.')

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _do_go(self, direction):
        """
        Move the player in 'direction'.

        If an 'instead_go' handler is present, it runs instead and movement
        does not happen (but the turn still advances).

        On success, the destination room's turn_counter is reset to 0,
        the room is described, and the status bar is updated.

        Returns True to advance the turn, False if movement failed.
        """
        room = self.world.current_room()
        if room is None:
            return False

        # 'instead of go:' intercepts all movement in this room.
        h = self._find_handler(room, 'instead_go')
        if h:
            self._run_body(h['body'])
            return True

        dest_name = room['exits'].get(direction)
        if dest_name is None:
            self._say("You can't go that way.")
            return False

        dest = self.world.room_by_name(dest_name)
        if dest is None:
            self._say(f"(Room '{dest_name}' not found — map error.)")
            return False

        self.world.player['location'] = dest_name
        dest['turn_counter'] = 0   # reset turn counter for the new room
        self._output('\n')
        self._describe_room(dest)
        self._update_status()
        return True

    def _do_take(self, noun_words):
        """
        Pick up an object from the current room.
        Checks for 'instead_of_take' handler first; if present, runs it instead.
        Then checks takeable flag.  On success, moves object to 'player' location
        and fires any 'on take' handler.
        """
        scope = self.world.objects_in_scope()
        room  = self.world.current_room()
        # Only objects in the room (not already in inventory) are candidates.
        candidates = [o for o in scope
                      if self.world.norm(o['location']) == self.world.norm(room['name'])]
        obj, err = self._resolve_noun(noun_words, candidates)
        if err:
            self._say(err)
            return False

        # 'instead of take "X":' intercepts this specific take.
        h_instead = self._find_handler(room, 'instead_take', obj['name'])
        if h_instead:
            self._run_body(h_instead['body'])
            return True

        if not obj['takeable']:
            self._say("You can't take that.")
            return False

        obj['location'] = 'player'
        self._say('Taken.')

        # 'on take "X":' fires after a successful take.
        h = self._find_handler(room, 'take', obj['name'])
        if h:
            self._run_body(h['body'])

        return True

    def _do_drop(self, noun_words):
        """
        Put down a carried object into the current room.
        Only searches the player's inventory (not the room).
        """
        inv = [o for o in self.world.objects if o['location'] == 'player']
        obj, err = self._resolve_noun(noun_words, inv)
        if err:
            self._say(err)
            return False

        room = self.world.current_room()
        obj['location'] = room['name']
        self._say('Dropped.')
        return True

    def _do_examine(self, noun_words):
        """
        Describe an object in scope (room + inventory).
        Fires any 'on examine "X":' handler after printing the description.
        """
        scope = self.world.objects_in_scope()
        obj, err = self._resolve_noun(noun_words, scope)
        if err:
            self._say(err)
            return False

        desc = obj['description'] or 'You see nothing special about it.'
        self._say(desc)

        # 'on examine "X":' fires after showing the description.
        room = self.world.current_room()
        if room:
            h = self._find_handler(room, 'examine', obj['name'])
            if h:
                self._run_body(h['body'])

        return True

    def _do_talk(self, noun_words):
        """
        Talk to an NPC in scope.  Fires the 'on talk to "X":' handler.
        If no handler exists, prints 'No response.'
        """
        scope = self.world.objects_in_scope()
        obj, err = self._resolve_noun(noun_words, scope)
        if err:
            self._say(err)
            return False

        room = self.world.current_room()
        if room:
            h = self._find_handler(room, 'talk', obj['name'])
            if h:
                self._run_body(h['body'])
                return True

        self._say('No response.')
        return True

    def _do_inventory(self):
        """
        List everything the player is carrying.
        Does not advance the turn (looking at your own pockets is free).
        """
        inv = [o for o in self.world.objects if o['location'] == 'player']
        if not inv:
            self._say('You are carrying nothing.')
        else:
            self._say('You are carrying:')
            for o in inv:
                self._say(f'  {o["name"]}')
        return False

    def _do_look(self):
        """Redescribe the current room.  Advances the turn."""
        room = self.world.current_room()
        if room:
            self._output('\n')
            self._describe_room(room)
        return True

    def _do_help(self):
        """
        Print a short introduction and the verb table.
        Does not advance the turn.
        """
        self._say(
            'You are playing a piece of interactive fiction. '
            'Type what you want to do and press Enter. '
            'The world responds to simple commands — '
            'you do not need to type full sentences.'
        )
        self._output('\n')
        self._say('Available commands:')
        self._output('\n')
        verbs = [
            ('go <direction>',       'move — or just type the direction alone'),
            ('n  s  e  w',           'shorthand for north, south, east, west'),
            ('look  (l)',            'describe your surroundings'),
            ('examine <thing>  (x)', 'look closely at something'),
            ('take <thing>',         'pick something up'),
            ('drop <thing>',         'put something down'),
            ('inventory  (i)',       'list what you are carrying'),
            ('talk to <person>',     'speak with someone'),
            ('wait  (z)',            'let time pass'),
            ('quit  (q)',            'end the game'),
            ('help  (?)',            'show this message'),
        ]
        col = max(len(v) for v, _ in verbs) + 2
        for verb, desc in verbs:
            self._output(f'  {verb:<{col}}{desc}\n')
        return False

    def _do_player_desc(self):
        """Print the player's own description ('x me').  Does not advance turn."""
        desc = self.world.player.get('description', '')
        if desc:
            self._say(desc)
        else:
            self._say(f'You are {self.world.player["name"]}.')
        return False

    # ------------------------------------------------------------------
    # Turn handlers
    # ------------------------------------------------------------------

    def _fire_turn_handlers(self):
        """
        Run all turn handlers for the current room that are due to fire.

        'turn'   handlers fire every turn.
        'turn_n' handlers fire once, exactly when turn_counter == n.
                 They set 'fired' = True so they never fire again.

        Note: turn_counter has already been incremented before this is called
        (see run() below), so 'on turn 1:' fires after the first action.
        """
        room = self.world.current_room()
        if room is None:
            return

        counter = room['turn_counter']

        for h in room['handlers']:
            if h['type'] == 'turn':
                self._run_body(h['body'])
            elif h['type'] == 'turn_n':
                if not h['fired'] and h['n'] == counter:
                    self._run_body(h['body'])
                    h['fired'] = True

    # ------------------------------------------------------------------
    # Main game loop
    # ------------------------------------------------------------------

    def run(self):
        """
        The main game loop.

        Sequence each iteration:
          1. Print blank line + '> ' prompt.
          2. Block on self._input('') — waits for player input.
             EOFError  → game ends (e.g. script exhausted, pipe closed).
             KeyboardInterrupt → game ends (e.g. Ctrl-Q in T46 terminal).
          3. Parse the input with InputParser.
          4. Dispatch to the appropriate _do_* method.
          5. If the action advances the turn, increment turn_counter and
             fire turn handlers for the current room.
        """
        world = self.world

        # Show starting room and update the status bar.
        start = world.current_room()
        if start:
            self._output('\n')
            self._describe_room(start)
            self._update_status()

        while self._running:
            # Blank line before the prompt so responses are visually separated.
            self._output('\n')
            self._print('> ')

            # --- user input -----------------------------------------------
            # self._input is injected at construction time.
            # In M56/T46 mode: lambda _: terminal.read_line()
            #   — blocks in the game thread until the user presses Enter;
            #     the T46 main thread echoes each character as it is typed.
            # Raises EOFError (script done) or KeyboardInterrupt (Ctrl-Q).
            try:
                line = self._input('').strip() if callable(self._input) else input('').strip()
            except (EOFError, KeyboardInterrupt):
                self._output('\n')
                break

            if not line:
                continue

            # --- dispatch -------------------------------------------------
            action = self._parser.parse(line)
            kind   = action[0]
            advance_turn = False

            if kind == 'empty':
                pass

            elif kind == 'quit':
                self._say('Goodbye.')
                break

            elif kind == 'go':
                advance_turn = self._do_go(action[1])

            elif kind == 'go_where':
                self._say('Go where?')

            elif kind == 'take':
                advance_turn = self._do_take(action[1])

            elif kind == 'take_what':
                self._say('Take what?')

            elif kind == 'drop':
                advance_turn = self._do_drop(action[1])

            elif kind == 'drop_what':
                self._say('Drop what?')

            elif kind == 'examine':
                advance_turn = self._do_examine(action[1])

            elif kind == 'examine_what':
                self._say('Examine what?')

            elif kind == 'talk':
                advance_turn = self._do_talk(action[1])

            elif kind == 'talk_to_what':
                self._say('Talk to whom?')

            elif kind == 'inventory':
                self._do_inventory()

            elif kind == 'wait':
                self._say('Time passes.')
                advance_turn = True

            elif kind == 'look':
                advance_turn = self._do_look()

            elif kind == 'player_desc':
                self._do_player_desc()

            elif kind == 'help':
                self._do_help()

            elif kind == 'unknown':
                self._say("I don't understand that.")

            # --- turn advance ---------------------------------------------
            # Increment the counter for the room the player is now in
            # (may differ from room before 'go'), then fire turn handlers.
            if advance_turn:
                room = world.current_room()
                if room is not None:
                    room['turn_counter'] += 1
                    self._fire_turn_handlers()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_and_run(source: str, output=None, input_fn=None, status_fn=None):
    """
    Parse 'source' as a .grue file and run the game.

    output    — see Interpreter docstring.
    input_fn  — see Interpreter docstring.
    status_fn — see Interpreter docstring.

    Raises GrueError on parse failure.
    """
    world = Parser().parse(source)
    interp = Interpreter(world, output=output, input_fn=input_fn, status_fn=status_fn)
    interp.run()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print('usage: grui.py <file.grue>', file=sys.stderr)
        sys.exit(1)

    src_path = Path(sys.argv[1])
    try:
        source = src_path.read_text()
    except OSError as e:
        print(f'grui: {e}', file=sys.stderr)
        sys.exit(1)

    try:
        load_and_run(source)
    except GrueError as e:
        print(f'grui: {e}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
