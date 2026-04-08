"""
grui — Grue interpreter
=======================
Loads a .grue source file and runs the game directly, with no compilation step.

Data flow
---------
                     .grue file
                         │
                      Lexer          tokenise() → flat list of Token objects
                         │
                      Parser         parse()    → World
                         │
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
grui only emits plain text with '\\n' line endings.

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

import sys
import textwrap
from pathlib import Path
from palette import PALETTE_DATA as _PAL


# ---------------------------------------------------------------------------
# Token types
# ---------------------------------------------------------------------------

TT_KEYWORD   = 'KEYWORD'    # room player kind on instead of go take examine talk to with turn say
TT_DIRECTION = 'DIRECTION'  # north south east west up down northeast northwest southeast southwest
TT_STRING    = 'STRING'     # "..." — stored without surrounding quotes
TT_NUMBER    = 'NUMBER'     # integer literal
TT_WORD      = 'WORD'       # any other identifier (NPC kinds, property names, …)
TT_COLON     = 'COLON'      # :
TT_EOF       = 'EOF'

_KEYWORDS = frozenset({
    'room', 'player', 'kind', 'color',
    'on', 'instead', 'of',
    'go', 'take', 'examine', 'talk', 'to', 'with', 'turn', 'say', 'end', 'draw',
})

# Full direction words.  Abbreviations (n, s, e, w, …) lex as TT_WORD;
# the parser checks them against the DIRECTIONS dict which includes abbrevs.
_DIRECTION_WORDS = frozenset({
    'north', 'south', 'east', 'west', 'up', 'down',
    'northeast', 'northwest', 'southeast', 'southwest',
})


class Token:
    """A single lexical token from a .grue source file."""
    __slots__ = ('type', 'value', 'line', 'col', 'indent')

    def __init__(self, type, value, line, col, indent=0):
        self.type   = type    # TT_* constant
        self.value  = value   # matched text (string content for TT_STRING, else raw text)
        self.line   = line    # 1-based line number in the source
        self.col    = col     # 1-based column of first character
        self.indent = indent  # leading space count of this line (0, 2, 4, …)

    def __repr__(self):
        return f'Token({self.type}, {self.value!r}, {self.line}:{self.col})'


# ---------------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------------

class Lexer:
    """
    Tokenise a pre-processed .grue source string into a flat list of Tokens.

    One pass, left-to-right, line by line.  The indent of the line is
    recorded on every token from that line — redundant but convenient for
    the parser and for syntax highlighters that work token by token.

    Blank lines and comment lines (# …) emit no tokens.
    The final token is always TT_EOF.

    Token type summary
    ------------------
      TT_KEYWORD   — reserved words: room player kind on instead of go take
                     examine talk to with turn say
      TT_DIRECTION — full direction names: north south east west up down
                     northeast northwest southeast southwest
      TT_STRING    — "..." — value is the content without quotes
      TT_NUMBER    — digit sequence
      TT_WORD      — any other identifier (NPC kinds, property names, …)
      TT_COLON     — the ':' character
      TT_EOF       — sentinel at end of token list
    """

    def tokenise(self, source: str) -> list:
        tokens = []
        lines  = source.splitlines()

        for line_no, raw in enumerate(lines, 1):
            stripped = raw.strip()
            if not stripped or stripped.startswith('#'):
                continue

            raw    = raw.expandtabs(2)
            indent = len(raw) - len(raw.lstrip(' '))
            pos    = indent
            n      = len(raw)

            while pos < n:
                ch = raw[pos]

                if ch == ' ':
                    pos += 1
                    continue

                # Comment — rest of line
                if ch == '#':
                    break

                col = pos + 1   # 1-based column

                # Quoted string — value is content without quotes
                if ch == '"':
                    end = raw.find('"', pos + 1)
                    if end == -1:
                        # Unclosed string: emit what we have and stop the line
                        tokens.append(Token(TT_WORD, raw[pos+1:], line_no, col, indent))
                        break
                    tokens.append(Token(TT_STRING, raw[pos+1:end], line_no, col, indent))
                    pos = end + 1
                    continue

                # Colon
                if ch == ':':
                    tokens.append(Token(TT_COLON, ':', line_no, col, indent))
                    pos += 1
                    continue

                # Word (identifier)
                if ch.isalpha() or ch == '_':
                    end = pos + 1
                    while end < n and (raw[end].isalnum() or raw[end] == '_'):
                        end += 1
                    word = raw[pos:end]
                    wl   = word.lower()
                    if wl in _KEYWORDS:
                        tt = TT_KEYWORD
                    elif wl in _DIRECTION_WORDS:
                        tt = TT_DIRECTION
                    else:
                        tt = TT_WORD
                    tokens.append(Token(tt, word, line_no, col, indent))
                    pos = end
                    continue

                # Number
                if ch.isdigit():
                    end = pos + 1
                    while end < n and raw[end].isdigit():
                        end += 1
                    tokens.append(Token(TT_NUMBER, raw[pos:end], line_no, col, indent))
                    pos = end
                    continue

                # Unrecognised character — skip silently
                pos += 1

        tokens.append(Token(TT_EOF, '', len(lines) + 1, 1, 0))
        return tokens


# ---------------------------------------------------------------------------
# Syntax highlighting
# ---------------------------------------------------------------------------

# Palette indices chosen for the T46 colour scheme.
_HL_COLOUR = {
    TT_KEYWORD:   _PAL[31],   # #4998A9  cool blue      — room, on, say …
    TT_DIRECTION: _PAL[30],   # #96C3C9  lighter blue   — north, east …
    TT_STRING:    _PAL[12],   # #E29D58  amber          — "quoted text"
    TT_NUMBER:    _PAL[16],   # #D8BA7B  warm gold      — turn numbers
    TT_WORD:      _PAL[19],   # #E6E9E2  near-white     — names / kinds
    TT_COLON:     _PAL[28],   # #BAD0D1  light blue-green — handler colon
}
_HL_COMMENT = _PAL[24]        # #98A6A1  grey-blue      — # comments
HL_DEFAULT  = _PAL[19]        # #E6E9E2  near-white     — unclassified (exported)


def highlight_line(raw_text):
    """Return syntax-highlight spans for one raw line of .grue source.

    Returns a list of (start_col, length, rgb_tuple) covering only the
    coloured tokens — gaps between spans use the caller's default colour.
    Cols are 0-based.
    """
    stripped = raw_text.strip()
    if not stripped:
        return []

    # Full-line comment
    if stripped.startswith('#'):
        return [(0, len(raw_text), _HL_COMMENT)]

    spans = []
    pos   = 0
    n     = len(raw_text)

    while pos < n:
        ch = raw_text[pos]

        if ch == ' ':
            pos += 1
            continue

        # Inline comment — colour rest of line and stop
        if ch == '#':
            spans.append((pos, n - pos, _HL_COMMENT))
            break

        start = pos

        # Quoted string
        if ch == '"':
            end = raw_text.find('"', pos + 1)
            if end == -1:
                end = n - 1
            spans.append((start, end - pos + 1, _HL_COLOUR[TT_STRING]))
            pos = end + 1
            continue

        # Colon
        if ch == ':':
            spans.append((start, 1, _HL_COLOUR[TT_COLON]))
            pos += 1
            continue

        # Word / keyword / direction
        if ch.isalpha() or ch == '_':
            end = pos + 1
            while end < n and (raw_text[end].isalnum() or raw_text[end] == '_'):
                end += 1
            word = raw_text[pos:end]
            wl   = word.lower()
            if wl in _KEYWORDS:
                rgb = _HL_COLOUR[TT_KEYWORD]
            elif wl in _DIRECTION_WORDS:
                rgb = _HL_COLOUR[TT_DIRECTION]
            else:
                rgb = _HL_COLOUR[TT_WORD]
            spans.append((start, end - pos, rgb))
            pos = end
            continue

        # Number
        if ch.isdigit():
            end = pos + 1
            while end < n and raw_text[end].isdigit():
                end += 1
            spans.append((start, end - pos, _HL_COLOUR[TT_NUMBER]))
            pos = end
            continue

        # Anything else (unrecognised char) — skip
        pos += 1

    return spans


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
        self.kinds          = {}   # kind-name → [value, ...] from 'kind X a b c'
        self.rooms          = {}   # normalised-name → room dict
        self.room_order     = []   # room keys in declaration order (first = start)
        self.objects        = []   # all object instances (rooms + inventory)
        self.player         = {}   # name, location, description, properties
        self.colors         = {}   # name → palette RGB tuple from 'color "name" N'
        self._next_obj_id   = 0

    def norm(self, name: str) -> str:
        """Normalise a room name for dict lookup (strip + lower-case)."""
        return name.strip().lower()

    def room_by_name(self, name: str):
        return self.rooms.get(self.norm(name))

    def current_room(self):
        return self.room_by_name(self.player['location'])

    def objects_in(self, location: str):
        loc = self.norm(location)
        return [o for o in self.objects if self.norm(o['location']) == loc]

    def objects_in_scope(self):
        """Objects in current room plus player inventory."""
        room = self.norm(self.player['location'])
        return [o for o in self.objects
                if self.norm(o['location']) == room
                or o['location'] == 'player']

    def add_object(self, kind: str, name: str, description: str, location: str):
        """
        Create a new object and add it to the world.
        'takeable' is False for living beings (declared under 'kind being:').
        'words' is the set used for noun matching.
        """
        living_kinds = {'woman', 'man', 'crow', 'fae', 'tree', 'stork', 'being'}
        fixed_kinds  = {'scenery'}
        living_from_kinds = set()
        if 'being' in self.kinds:
            living_from_kinds = set(self.kinds['being'])
        takeable = (kind not in living_kinds) and (kind not in living_from_kinds) and (kind not in fixed_kinds)
        words = set(name.lower().split()) | {kind.lower()}
        obj = {
            'id':          self._next_obj_id,
            'kind':        kind,
            'name':        name,
            'words':       words,
            'location':    location,
            'description': description,
            'takeable':    takeable,
        }
        self._next_obj_id += 1
        self.objects.append(obj)
        return obj


# ---------------------------------------------------------------------------
# Parser — tokenises source and builds a World
# ---------------------------------------------------------------------------

class Parser:
    """
    Parse a .grue source file into a World.

    The .grue format is indent-significant:

      indent 0   — top-level declarations:
                     kind being  tree fae crow woman man
                     player "name":
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

    Colon rule: colons are required only on handler headers ('on ...:',
    'instead of ...:').  Exit declarations use direction-word lookup;
    kind and player-property lines accept colons for backwards compatibility.

    The Parser drives the Lexer internally.  Call parse() to build a World,
    or check() to collect syntax and semantic issues without running the game.
    """

    # ---- multiline string preprocessor ----

    @staticmethod
    def _preprocess(source: str) -> str:
        """
        Join lines that contain an unclosed quoted string.
        A line with an odd number of '"' characters has an open quote; keep
        appending continuation lines until the count becomes even again.
        Comments and blank lines are passed through unchanged.
        This runs before the Lexer so that all strings fit on one line.
        """
        lines = source.splitlines()
        out   = []
        i     = 0
        while i < len(lines):
            line     = lines[i]
            stripped = line.strip()
            if stripped.startswith('#') or not stripped:
                out.append(line)
                i += 1
                continue
            if stripped.count('"') % 2 == 1:
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

    # ---- group flat token list into lines ----

    @staticmethod
    def _group_lines(tokens: list) -> list:
        """
        Group tokens by source line.
        Returns a list of (line_no, indent, [tokens]) tuples.
        TT_EOF is not included in any group.
        """
        groups = []
        i = 0
        while i < len(tokens) and tokens[i].type != TT_EOF:
            t       = tokens[i]
            line_no = t.line
            indent  = t.indent
            group   = []
            while i < len(tokens) and tokens[i].type != TT_EOF and tokens[i].line == line_no:
                group.append(tokens[i])
                i += 1
            if group:
                groups.append((line_no, indent, group))
        return groups

    # ---- handler header parser ----

    @staticmethod
    def _parse_handler_header(toks: list, line_no: int, error) -> dict:
        """
        Try to parse the token list as a handler header.

        Returns a handler dict on success, or None if the line is not a
        handler (i.e. does not start with 'on' or 'instead').
        Reports an error (via the error callback) if a handler keyword is
        present but the header is malformed (e.g. missing colon).
        """
        types  = [t.type  for t in toks]
        values = [t.value.lower() for t in toks]
        strs   = [t for t in toks if t.type == TT_STRING]

        # Only 'on' and 'instead' start handler headers.
        if not (types[0] == TT_KEYWORD and values[0] in ('on', 'instead')):
            return None

        # Handler headers must end with a colon.
        if types[-1] != TT_COLON:
            raw = ' '.join(t.value for t in toks)
            error(line_no, f'handler header must end with ":" — {raw!r}')
            # Return a dummy ignore handler so parsing can continue.
            return {'type': 'ignore', 'body': []}

        if values[0] == 'on':
            # on turn:
            if values[1:] == ['turn', ':']:
                return {'type': 'turn', 'body': []}

            # on turn N:
            if len(values) >= 3 and values[1] == 'turn' and types[2] == TT_NUMBER:
                return {'type': 'turn_n', 'n': int(toks[2].value), 'body': [], 'fired': False}

            # on talk to "X":
            if values[1] == 'talk' and strs:
                return {'type': 'talk', 'target': strs[0].value, 'body': []}

            # on take "X":
            if values[1] == 'take' and strs:
                return {'type': 'take', 'target': strs[0].value, 'body': []}

            # on examine "X":
            if values[1] == 'examine' and strs:
                return {'type': 'examine', 'target': strs[0].value, 'body': []}

            # on <anything else>: — unrecognised, consume body silently
            return {'type': 'ignore', 'body': []}

        if values[0] == 'instead':
            # instead of go:
            if 'go' in values:
                return {'type': 'instead_go', 'body': []}

            # instead of take "X":
            if 'take' in values and strs:
                return {'type': 'instead_take', 'target': strs[0].value, 'body': []}

            return {'type': 'ignore', 'body': []}

        return None   # unreachable

    # ---- core parse loop ----

    def _parse_tokens(self, tokens: list, issues: list = None) -> 'World':
        """
        Build a World from the token list.

        If 'issues' is a list, parse errors are appended to it as strings
        instead of raising GrueError — used by check().
        """
        def error(line_no, msg):
            text = f'line {line_no}: {msg}'
            if issues is not None:
                issues.append(text)
            else:
                raise GrueError(text)

        world                = World()
        groups               = self._group_lines(tokens)
        current_room         = None
        current_handler      = None
        current_sub_handler  = None   # body of a nested 'instead of go' inside turn_n

        for line_no, indent, toks in groups:
            types  = [t.type        for t in toks]
            values = [t.value       for t in toks]
            strs   = [t for t in toks if t.type == TT_STRING]

            # ---- indent 0: top-level declarations -----------------------
            if indent == 0:
                current_handler = None
                current_room    = None

                if types[0] == TT_KEYWORD and values[0] == 'color':
                    # color "name" N  — named palette colour for inline text markup
                    nums = [t for t in toks if t.type == TT_NUMBER]
                    if not strs or not nums:
                        error(line_no, "'color' needs a quoted name and a palette index, e.g.  color \"feeling\" 29")
                        continue
                    idx = int(nums[0].value)
                    from palette import PALETTE_DATA as _PAL
                    world.colors[strs[0].value.lower()] = _PAL[idx]

                elif types[0] == TT_KEYWORD and values[0] == 'kind':
                    # kind being  tree fae crow woman man
                    # Colon after the kind name is accepted but not required.
                    if len(toks) < 2:
                        error(line_no, "'kind' needs a name")
                        continue
                    kind_name = toks[1].value
                    rest = [t for t in toks[2:] if t.type != TT_COLON]
                    world.kinds[kind_name] = [t.value for t in rest]

                elif types[0] == TT_KEYWORD and values[0] == 'player':
                    # player "name":
                    #   property value
                    #   ...
                    if len(toks) > 1 and toks[1].type == TT_WORD and toks[1].value.lower() == 'has':
                        error(line_no,
                              "use block syntax: player \"name\":\\n  property value")
                        continue
                    if not strs:
                        error(line_no, "'player' needs a quoted name, e.g.  player \"me\":")
                        continue
                    world.player = {
                        'name':        strs[0].value,
                        'location':    '',
                        'description': '',
                        'properties':  {},
                    }

                elif types[0] == TT_KEYWORD and values[0] == 'room':
                    # room "Name"
                    if not strs:
                        error(line_no, "'room' needs a quoted name")
                        continue
                    rname        = strs[0].value
                    rkey         = world.norm(rname)
                    current_room = {
                        'name':         rname,
                        'desc':         '',
                        'exits':        {},
                        'handlers':     [],
                        'turn_counter': 0,
                    }
                    world.rooms[rkey] = current_room
                    world.room_order.append(rkey)
                    if not world.player.get('location'):
                        world.player['location'] = rname

                else:
                    error(line_no, f'unexpected {values[0]!r} at top level'
                          f' — expected room, player, or kind')

            # ---- indent 2: inside player block --------------------------
            elif indent == 2 and world.player and not current_room:
                if types[0] == TT_STRING:
                    # Player description string
                    world.player['description'] = toks[0].value
                else:
                    # Property line:  mood lost  /  being tree  /  treeness 0
                    rest = [t for t in toks[1:] if t.type != TT_COLON]
                    if rest:
                        world.player['properties'][values[0]] = rest[0].value

            # ---- indent 2: inside room ----------------------------------
            elif indent == 2 and current_room is not None:
                current_handler = None

                # Room description — a quoted string at indent 2.
                if types[0] == TT_STRING:
                    current_room['desc'] = toks[0].value
                    continue

                # Handler header — starts with 'on' or 'instead'.
                handler = self._parse_handler_header(toks, line_no, error)
                if handler is not None:
                    current_room['handlers'].append(handler)
                    current_handler = handler['body']
                    continue

                # Exit — direction word (or any word with a colon) + one string.
                # Direction word lookup includes abbreviations (n, s, e, w, …)
                # from the module-level DIRECTIONS dict.
                has_colon    = TT_COLON in types
                is_direction = (types[0] == TT_DIRECTION or values[0] in DIRECTIONS)
                if strs and len(strs) == 1 and (is_direction or has_colon):
                    current_room['exits'][values[0]] = strs[0].value
                    continue

                # Object declaration — three forms:
                #   kind "Name"               — takeable object, name quoted
                #   kind "Name" "Description" — takeable object, name + desc
                #   kind word "Description"   — scenery/NPC, name unquoted
                if strs:
                    if len(strs) == 1 and len(types) >= 2 and types[1] == TT_WORD:
                        # Unquoted name: kind word "Description"
                        world.add_object(values[0], values[1], strs[0].value,
                                         current_room['name'])
                    else:
                        # Quoted name: kind "Name" or kind "Name" "Description"
                        world.add_object(values[0], strs[0].value,
                                         strs[1].value if len(strs) > 1 else '',
                                         current_room['name'])
                    continue

                error(line_no, f'unrecognised line in room body: '
                      f'{" ".join(v for v in values if v != ":")!r}')

            # ---- indent 4: handler body ---------------------------------
            elif indent == 4 and current_handler is not None:
                current_sub_handler = None   # reset on each new indent-4 line

                # Nested 'instead of <action>:' inside a turn_n handler.
                if (types[0] == TT_KEYWORD and values[0] == 'instead'
                        and types[-1] == TT_COLON):
                    # Find the enclosing turn_n handler in the current room.
                    h_owner = None
                    if current_room:
                        for h in reversed(current_room['handlers']):
                            if h['body'] is current_handler:
                                h_owner = h
                                break
                    if h_owner and h_owner['type'] == 'turn_n':
                        # Key is 'instead_<action>' e.g. instead_go, instead_take
                        action_word = next((v for v in values[1:]
                                           if v not in ('of', ':')), 'go')
                        key = f'instead_{action_word}'
                        h_owner.setdefault(key, [])
                        current_sub_handler = h_owner[key]
                    else:
                        error(line_no, "'instead of ...' can only be nested inside 'on turn N:'")
                    continue

                if types[0] == TT_KEYWORD and values[0] == 'end':
                    current_handler.append(('end',))
                    continue

                if types[0] == TT_KEYWORD and values[0] == 'say':
                    if not strs:
                        error(line_no, "'say' needs a quoted string")
                        continue
                    current_handler.append(('say', strs[0].value))
                    continue

                # go "Room Name" — scripted movement to a named room
                if types[0] == TT_KEYWORD and values[0] == 'go' and strs:
                    current_handler.append(('go', strs[0].value))
                    continue

                if values[0] == 'draw' and strs:
                    current_handler.append(('draw', strs[0].value))
                    continue

                # Object creation in a handler body: kind "Name" "Description"
                if strs:
                    current_handler.append((
                        'create',
                        values[0],
                        strs[0].value,
                        strs[1].value if len(strs) > 1 else '',
                    ))
                    continue

                error(line_no, f'unrecognised handler body line: '
                      f'{" ".join(values)!r}')

            # ---- indent 6: nested sub-handler body ----------------------
            elif indent == 6 and current_sub_handler is not None:
                if types[0] == TT_KEYWORD and values[0] == 'say':
                    if not strs:
                        error(line_no, "'say' needs a quoted string")
                        continue
                    current_sub_handler.append(('say', strs[0].value))
                    continue
                if types[0] == TT_KEYWORD and values[0] == 'go' and strs:
                    current_sub_handler.append(('go', strs[0].value))
                    continue
                if types[0] == TT_KEYWORD and values[0] == 'end':
                    current_sub_handler.append(('end',))
                    continue
                error(line_no, f'unrecognised nested handler line: '
                      f'{" ".join(values)!r}')

            else:
                if indent not in (0, 2, 4, 6):
                    error(line_no, f'unexpected indent of {indent} spaces '
                          f'(valid indents are 0, 2, 4, 6)')

        return world

    # ---- public API ----

    def parse(self, source: str) -> 'World':
        """
        Parse 'source' and return a populated World.
        Raises GrueError with a 'line N: message' string on the first error.
        """
        source = self._preprocess(source)
        tokens = Lexer().tokenise(source)
        return self._parse_tokens(tokens)

    def check(self, source: str) -> list:
        """
        Run syntax and semantic checks on 'source'.
        Returns a list of issue strings ('line N: …' or 'warning: …').
        Does not raise GrueError.

        Semantic checks performed:
          — exit destinations: named room must exist
          — handler targets: named object must be statically declared
            (dynamically created objects cannot be checked statically;
             those produce a warning rather than an error)
        """
        issues = []
        source = self._preprocess(source)
        tokens = Lexer().tokenise(source)

        # Syntax pass — collect all errors, do not stop at first.
        world = self._parse_tokens(tokens, issues=issues)

        # Semantic pass — only runs if syntax was clean enough to build a World.
        for rkey, room in world.rooms.items():

            # Exit destinations must name a declared room.
            for direction, dest in room['exits'].items():
                if world.norm(dest) not in world.rooms:
                    issues.append(
                        f'room "{room["name"]}": '
                        f'exit {direction!r} leads to "{dest}" — room not defined')

            # Handler targets should be statically declared objects.
            static_names = {
                o['name'].lower()
                for o in world.objects
                if world.norm(o['location']) == rkey
            }
            for h in room['handlers']:
                if h['type'] in ('talk', 'take', 'examine', 'instead_take'):
                    t = h['target']
                    if t.lower() not in static_names:
                        issues.append(
                            f'warning: room "{room["name"]}": '
                            f'handler target "{t}" is not a statically declared '
                            f'object (it may be created dynamically)')

        if world.player and not world.rooms:
            issues.append('no rooms declared')

        return issues


# ---------------------------------------------------------------------------
# Input parser — player text -> action tuple
# ---------------------------------------------------------------------------

DIRECTIONS = {
    'north': 'north', 'south': 'south', 'east': 'east', 'west': 'west',
    'up': 'up', 'down': 'down',
    'northeast': 'northeast', 'northwest': 'northwest',
    'southeast': 'southeast', 'southwest': 'southwest',
    'n': 'north', 's': 'south', 'e': 'east', 'w': 'west',
    'u': 'up', 'd': 'down',
    'ne': 'northeast', 'nw': 'northwest', 'se': 'southeast', 'sw': 'southwest',
}

ARTICLES = {'a', 'an', 'the'}


class InputParser:
    """
    Translate a raw player input string into a typed action tuple.

    The returned tuple's first element is the action kind; subsequent
    elements are kind-specific data:

      ('go',         direction_str)
      ('go_where',)
      ('take',       noun_words)
      ('take_what',)
      ('drop',       noun_words)
      ('drop_what',)
      ('examine',    noun_words)
      ('examine_what',)
      ('talk',       noun_words)
      ('talk_to_what',)
      ('inventory',)
      ('wait',)
      ('look',)
      ('player_desc',)
      ('quit',)
      ('help',)
      ('empty',)
      ('unknown',    raw_string)
    """

    def _strip_articles(self, words):
        return [w for w in words if w not in ARTICLES]

    def parse(self, line: str):
        words = line.lower().split()
        if not words:
            return ('empty',)

        if words[0] in DIRECTIONS and len(words) == 1:
            return ('go', DIRECTIONS[words[0]])

        verb = words[0]
        rest = words[1:]

        if verb == 'go':
            if not rest:
                return ('go_where',)
            d = self._strip_articles(rest)
            if d and d[0] in DIRECTIONS:
                return ('go', DIRECTIONS[d[0]])
            return ('go_where',)

        if verb in ('take', 'get', 'grab'):
            noun = self._strip_articles(rest)
            return ('take', noun) if noun else ('take_what',)

        if verb == 'pick' and rest and rest[0] == 'up':
            noun = self._strip_articles(rest[1:])
            return ('take', noun) if noun else ('take_what',)

        if verb == 'drop':
            noun = self._strip_articles(rest)
            return ('drop', noun) if noun else ('drop_what',)

        if verb == 'put' and rest and rest[0] == 'down':
            noun = self._strip_articles(rest[1:])
            return ('drop', noun) if noun else ('drop_what',)

        if verb in ('examine', 'inspect', 'x'):
            noun = self._strip_articles(rest)
            if not noun:
                return ('examine_what',)
            if noun in (['me'], ['i']):
                return ('player_desc',)
            return ('examine', noun)

        if verb == 'look':
            if rest and rest[0] == 'at':
                noun = self._strip_articles(rest[1:])
                return ('examine', noun) if noun else ('look',)
            return ('look',)

        if verb == 'l' and not rest:
            return ('look',)

        if verb in ('talk', 'speak'):
            if rest and rest[0] in ('to', 'with'):
                noun = self._strip_articles(rest[1:])
            else:
                noun = self._strip_articles(rest)
            return ('talk', noun) if noun else ('talk_to_what',)

        if verb == 'ask':
            noun = self._strip_articles(rest)
            return ('talk', noun) if noun else ('talk_to_what',)

        if verb in ('inventory', 'i', 'inv') and not rest:
            return ('inventory',)

        if verb in ('wait', 'z') and not rest:
            return ('wait',)

        if verb in ('quit', 'q') and not rest:
            return ('quit',)

        if verb in ('help', '?') and not rest:
            return ('help',)

        return ('unknown', line.strip())


# ---------------------------------------------------------------------------
# Interpreter — game loop
# ---------------------------------------------------------------------------

class Interpreter:
    """
    Run the interactive game loop against a populated World.

    All I/O is injected at construction time:

      output    — callable(str): receives raw text with '\\n' line endings.
      input_fn  — callable(prompt) → str: returns one line of player input.
                  Raises EOFError (script done) or KeyboardInterrupt (Ctrl-Q).
      status_fn — callable(room_name, exits_list) | None: called after the
                  initial room display and after every successful 'go'.
    """

    WRAP = 72

    def __init__(self, world: World, output=None, input_fn=None, status_fn=None,
                 wait_key_fn=None, set_color_fn=None, say_pause=0.0, say_color=None,
                 draw_fn=None, src_dir=None):
        self.world        = world
        self._output      = output  or (lambda s: print(s, end=''))
        self._input       = input_fn or input
        self._wait_key    = wait_key_fn or (lambda: input())
        self._set_color   = set_color_fn  # fn(rgb_tuple|None) — None resets to default
        self._parser      = InputParser()
        self._status_fn   = status_fn
        self._running     = True
        self._say_pause   = say_pause   # seconds to sleep after each say line
        self._say_color   = say_color   # default RGB for untagged say text (None = terminal default)
        self._draw_fn     = draw_fn     # fn(name) — display a .spans image by stem name
        self._src_dir     = src_dir     # directory containing the .grue file

    def _say(self, text: str):
        import time, re
        if not text:
            self._output('\n')
            return
        # Optional leading [N] sets a per-line delay in tenths of a second.
        m = re.match(r'^\[(\d+)\]', text)
        if m:
            time.sleep(int(m.group(1)) / 10.0)
            text = text[m.end():]
        if not text:
            return
        # Parse inline color tags: [name]...[/name] or [name]... to end of string.
        # Segments: list of (text, rgb|None)
        segments = self._parse_color_tags(text)
        # Apply say_color to any untagged segment
        if self._say_color:
            segments = [(s, rgb if rgb is not None else self._say_color)
                        for s, rgb in segments]
        if len(segments) == 1 and segments[0][1] is None:
            # No color — plain wrap
            for line in textwrap.wrap(text, self.WRAP):
                self._output(line + '\n')
                if self._say_pause:
                    time.sleep(self._say_pause)
        else:
            # Colored output — wrap the plain text, then re-emit with colors.
            plain = ''.join(s for s, _ in segments)
            char_colors = [rgb for s, rgb in segments for _ in s]
            wrapped = textwrap.wrap(plain, self.WRAP)
            # Track position in plain so we skip spaces textwrap removed.
            pos = 0
            for line in wrapped:
                for ch in line:
                    while pos < len(plain) and plain[pos] != ch:
                        pos += 1
                    if self._set_color:
                        self._set_color(char_colors[pos] if pos < len(char_colors) else None)
                    self._output(ch)
                    pos += 1
                if self._set_color:
                    self._set_color(None)
                self._output('\n')
                if self._say_pause:
                    time.sleep(self._say_pause)

    def _parse_color_tags(self, text: str):
        """Split text into [(fragment, rgb|None)] segments using world.colors."""
        import re
        colors  = self.world.colors
        if not colors or '[' not in text:
            return [(text, None)]
        pattern = re.compile(r'\[(/?)(\w+)\]')
        segments  = []
        pos       = 0
        cur_color = None
        for m in pattern.finditer(text):
            if m.start() > pos:
                segments.append((text[pos:m.start()], cur_color))
            closing = m.group(1) == '/'
            name    = m.group(2).lower()
            if closing:
                cur_color = None
            elif name in colors:
                cur_color = colors[name]
            # unknown tag names are emitted as literal text
            else:
                segments.append((m.group(0), cur_color))
            pos = m.end()
        if pos < len(text):
            segments.append((text[pos:], cur_color))
        return segments or [(text, None)]

    def _print(self, text: str):
        self._output(text)

    def _match_objects(self, noun_words, candidates):
        noun_set = set(noun_words)
        return [o for o in candidates if noun_set <= o['words']]

    def _resolve_noun(self, noun_words, candidates):
        matches = self._match_objects(noun_words, candidates)
        if not matches:
            return None, "I don't see that here."
        if len(matches) == 1:
            return matches[0], None
        names = ', '.join(o['name'] for o in matches)
        return None, f'Please be more specific — {names}.'

    def _run_body(self, body):
        for stmt in body:
            if stmt[0] == 'say':
                self._say(stmt[1])
            elif stmt[0] == 'go':
                self._do_go_room(stmt[1])
            elif stmt[0] == 'draw':
                if self._draw_fn:
                    self._draw_fn(stmt[1])
            elif stmt[0] == 'end':
                self._output('\n')
                self._say('The neural engram ends here. Press any key.')
                self._wait_key()
                self._running = False
                return
            elif stmt[0] == 'create':
                _, kind, name, desc = stmt
                room = self.world.current_room()
                if room:
                    self.world.add_object(kind, name, desc, room['name'])

    def _find_handler(self, room, htype, target=None):
        for h in room['handlers']:
            if h['type'] != htype:
                continue
            if target is not None and h.get('target', '').lower() != target.lower():
                continue
            return h
        return None

    def _update_status(self):
        if self._status_fn is None:
            return
        room = self.world.current_room()
        if room:
            self._status_fn(room['name'], list(room['exits'].keys()))

    def _describe_room(self, room):
        room_color = self.world.colors.get('room')
        if room_color and self._set_color:
            self._set_color(room_color)
            self._output(room['name'] + '\n')
            self._set_color(None)
        else:
            self._say(room['name'])
        self._output('\n')
        if room['desc']:
            self._say(room['desc'])
        objs = [o for o in self.world.objects_in(room['name']) if o['takeable']]
        if objs:
            self._output('\n')
            for o in objs:
                self._say(f'There is a {o["name"]} here.')
        exits = list(room['exits'].keys())
        if exits:
            self._output('\n')
            self._say('Exits: ' + ', '.join(exits) + '.')
        else:
            self._output('\n')
            self._say('There are no obvious exits.')

    def _do_go(self, direction):
        room = self.world.current_room()
        if room is None:
            return False
        # Check for turn-scoped 'instead of go' (nested inside 'on turn N:').
        # Active when the player's next action would advance to turn N.
        counter = room['turn_counter']
        for h in room['handlers']:
            if (h['type'] == 'turn_n' and not h['fired']
                    and h['n'] == counter + 1 and 'instead_go' in h):
                self._run_body(h['instead_go'])
                return True   # counts as a turn action but player didn't move
        h = self._find_handler(room, 'instead_go')
        if h:
            self._run_body(h['body'])
            return True
        dest_name = room['exits'].get(direction)
        if dest_name is None:
            self._say("I can't go that way.")
            return False
        dest = self.world.room_by_name(dest_name)
        if dest is None:
            self._say(f"(Room '{dest_name}' not found — map error.)")
            return False
        self.world.player['location'] = dest_name
        dest['turn_counter'] = 0
        self._output('\n')
        self._describe_room(dest)
        self._update_status()
        self._fire_turn_zero(dest)
        return True

    def _do_go_room(self, room_name):
        dest = self.world.room_by_name(room_name)
        if dest is None:
            self._say(f"(Room '{room_name}' not found — map error.)")
            return
        self.world.player['location'] = dest['name']
        dest['turn_counter'] = 0
        self._output('\n')
        self._describe_room(dest)
        self._update_status()
        self._fire_turn_zero(dest)

    def _do_take(self, noun_words):
        scope = self.world.objects_in_scope()
        room  = self.world.current_room()
        candidates = [o for o in scope
                      if self.world.norm(o['location']) == self.world.norm(room['name'])]
        obj, err = self._resolve_noun(noun_words, candidates)
        if err:
            self._say(err)
            return False
        h_instead = self._find_handler(room, 'instead_take', obj['name'])
        if h_instead:
            self._run_body(h_instead['body'])
            return True
        if not obj['takeable']:
            self._say("You can't take that.")
            return False
        obj['location'] = 'player'
        self._say('Taken.')
        h = self._find_handler(room, 'take', obj['name'])
        if h:
            self._run_body(h['body'])
        return True

    def _do_drop(self, noun_words):
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
        scope = self.world.objects_in_scope()
        obj, err = self._resolve_noun(noun_words, scope)
        if err:
            self._say(err)
            return False
        desc = obj['description'] or 'You see nothing special about it.'
        self._say(desc)
        room = self.world.current_room()
        if room:
            h = self._find_handler(room, 'examine', obj['name'])
            if h:
                self._run_body(h['body'])
        return True

    def _do_talk(self, noun_words):
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
        inv = [o for o in self.world.objects if o['location'] == 'player']
        if not inv:
            self._say('You are carrying nothing.')
        else:
            self._say('You are carrying:')
            for o in inv:
                self._say(f'  {o["name"]}')
        return False

    def _do_look(self):
        room = self.world.current_room()
        if room:
            self._output('\n')
            self._describe_room(room)
        return True

    def _do_help(self):
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
        desc = self.world.player.get('description', '')
        if desc:
            self._say(desc)
        else:
            self._say(f'You are {self.world.player["name"]}.')
        return False

    def _fire_turn_zero(self, room):
        """Fire 'on turn 0:' handlers — runs once on first entry to a room."""
        for h in room['handlers']:
            if h['type'] == 'turn_n' and h['n'] == 0 and not h['fired']:
                self._run_body(h['body'])
                h['fired'] = True

    def _fire_turn_handlers(self):
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

    def run(self):
        """
        The main game loop.

        Sequence each iteration:
          1. Print blank line + '> ' prompt.
          2. Block on self._input('') — waits for player input.
             EOFError  → game ends (script exhausted, pipe closed).
             KeyboardInterrupt → game ends (Ctrl-Q in T46 terminal).
          3. Parse with InputParser and dispatch to _do_* methods.
          4. If the action advances the turn, increment turn_counter and
             fire turn handlers.
        """
        world = self.world

        start = world.current_room()
        if start:
            self._output('\n')
            self._describe_room(start)
            self._update_status()
            self._fire_turn_zero(start)

        while self._running:
            self._output('\n')
            self._print('> ')

            try:
                line = self._input('').strip() if callable(self._input) else input('').strip()
            except (EOFError, KeyboardInterrupt):
                self._output('\n')
                break

            if not line:
                continue

            action       = self._parser.parse(line)
            kind         = action[0]
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

            if advance_turn:
                room = world.current_room()
                if room is not None:
                    room['turn_counter'] += 1
                    self._fire_turn_handlers()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_and_run(source: str, output=None, input_fn=None, status_fn=None,
                 wait_key_fn=None, set_color_fn=None, say_pause=0.0, say_color=None,
                 draw_fn=None, src_dir=None):
    """Parse 'source' as a .grue file and run the game. Raises GrueError on error."""
    world  = Parser().parse(source)
    interp = Interpreter(world, output=output, input_fn=input_fn, status_fn=status_fn,
                         wait_key_fn=wait_key_fn, set_color_fn=set_color_fn,
                         say_pause=say_pause, say_color=say_color,
                         draw_fn=draw_fn, src_dir=src_dir)
    interp.run()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    args       = sys.argv[1:]
    check_mode = '--check' in args
    args       = [a for a in args if a != '--check']

    if not args:
        print('usage: grui.py [--check] <file.grue>', file=sys.stderr)
        sys.exit(1)

    src_path = Path(args[0])
    try:
        source = src_path.read_text()
    except OSError as e:
        print(f'grui: {e}', file=sys.stderr)
        sys.exit(1)

    if check_mode:
        issues = Parser().check(source)
        if not issues:
            print(f'{src_path}: ok')
        else:
            for issue in issues:
                print(f'{src_path}: {issue}', file=sys.stderr)
            sys.exit(1)
        return

    try:
        load_and_run(source)
    except GrueError as e:
        print(f'grui: {e}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
