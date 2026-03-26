"""
grue — Grue compiler

Reads a .grue source file and emits a .pi file that implements the game
using the Pi interpreter runtime.

Usage:
    python3 grue.py game.grue            # writes /tmp/game.pi
    python3 grue.py game.grue out.pi     # explicit output path
"""

import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class GrueError(Exception):
    pass


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _preprocess(source: str) -> str:
    """Join multi-line quoted strings onto a single line."""
    lines = source.splitlines()
    out   = []
    i     = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith('--') or not stripped:
            out.append(line)
            i += 1
            continue
        # Count quotes: odd count means an unclosed string spans to the next line.
        if stripped.count('"') % 2 == 1:
            joined = line.rstrip()
            i += 1
            while i < len(lines):
                cont = lines[i].strip()
                joined += ' ' + cont
                i += 1
                if joined.count('"') % 2 == 0:
                    break
            out.append(joined)
        else:
            out.append(line)
            i += 1
    return '\n'.join(out)


def _extract_string(s: str) -> str:
    """Pull the contents out of a "quoted string"."""
    s = s.strip()
    m = re.match(r'"(.*)"', s)
    if m:
        return m.group(1)
    raise GrueError(f'expected quoted string, got: {s!r}')


def parse(source: str) -> dict:
    """
    Parse Grue source into an AST dict:
      {
        kinds:  { name: [values] },
        player: { prop: value },
        rooms:  [ { id, name, desc, exits, objects, handlers } ]
      }
    handlers keys: 'arrive', 'turn', 'instead_go'
    handler values: list of action tuples ('say', text), ('go', dest), ('set', prop, val)
    """
    source = _preprocess(source)
    lines  = source.splitlines()
    ast    = {'kinds': {}, 'player': {}, 'rooms': []}

    current_room    = None
    current_handler = None   # list being built, or None

    for raw in lines:
        stripped = raw.strip()
        indent   = len(raw) - len(raw.lstrip())

        if not stripped or stripped.startswith('--'):
            continue

        # ---- top level (indent 0) ------------------------------------
        if indent == 0:
            current_handler = None
            current_room    = None

            if stripped.startswith('kind '):
                m = re.match(r'kind\s+(\w+):\s*(.*)', stripped)
                if m:
                    ast['kinds'][m.group(1)] = m.group(2).split()

            elif stripped.startswith('player has '):
                m = re.match(r'player has ([\w-]+):\s*(\S+)', stripped)
                if m:
                    prop, val = m.group(1), m.group(2)
                    try:
                        ast['player'][prop] = int(val)
                    except ValueError:
                        ast['player'][prop] = val

            elif stripped.startswith('room '):
                m = re.match(r'room\s+([\w-]+)\s+"([^"]*)"', stripped)
                if not m:
                    raise GrueError(f'bad room header: {stripped!r}')
                current_room = {
                    'id':       m.group(1),
                    'name':     m.group(2),
                    'desc':     '',
                    'exits':    {},
                    'objects':  [],
                    'handlers': {},
                }
                ast['rooms'].append(current_room)

        # ---- room level (indent 2) ------------------------------------
        elif indent == 2 and current_room is not None:
            current_handler = None

            # Description
            if stripped.startswith('"'):
                current_room['desc'] = _extract_string(stripped)

            # Exits:  north: open-space
            elif re.match(r'[\w-]+:\s+[\w-]+$', stripped):
                m = re.match(r'([\w-]+):\s+([\w-]+)', stripped)
                if m:
                    current_room['exits'][m.group(1)] = m.group(2)

            # Objects:  object id "desc" [scenery]
            elif stripped.startswith('object '):
                m = re.match(r'object\s+([\w-]+)\s+"([^"]*)"(\s+scenery)?', stripped)
                if m:
                    current_room['objects'].append({
                        'id':      m.group(1),
                        'desc':    m.group(2),
                        'scenery': bool(m.group(3)),
                    })

            # Handler declarations
            elif stripped == 'on arrive:':
                current_handler = []
                current_room['handlers']['arrive'] = current_handler
            elif stripped == 'on turn:':
                current_handler = []
                current_room['handlers']['turn'] = current_handler
            elif stripped == 'instead of go:':
                current_handler = []
                current_room['handlers']['instead_go'] = current_handler

        # ---- handler body (indent 4) ----------------------------------
        elif indent == 4 and current_handler is not None:
            if stripped.startswith('say '):
                current_handler.append(('say', _extract_string(stripped[4:])))
            elif stripped.startswith('go '):
                current_handler.append(('go', stripped[3:].strip()))
            elif stripped.startswith('set player '):
                m = re.match(r'set player ([\w-]+):\s*([\w-]+)', stripped)
                if m:
                    current_handler.append(('set', m.group(1), m.group(2)))

    return ast


# ---------------------------------------------------------------------------
# Code generator
# ---------------------------------------------------------------------------

def emit(ast: dict) -> str:
    kinds   = ast['kinds']
    player  = ast['player']
    rooms   = ast['rooms']
    room_ids = [r['id'] for r in rooms]

    lines = []
    w = lines.append

    def q(s):
        """Emit a Pi quoted string literal."""
        return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'

    def room_const(rid):
        return 'R-' + rid

    def emit_actions(actions, indent='  '):
        for act in actions:
            if act[0] == 'say':
                w(f'{indent}{q(act[1])} println')
            elif act[0] == 'go':
                dest = act[1]
                if dest in room_ids:
                    w(f'{indent}{room_const(dest)} auto-go')
                else:
                    w(f'{indent}// unresolved: go {dest}')
            elif act[0] == 'set':
                _, prop, val = act
                # Resolve enum value to integer
                resolved = False
                for kname, kvals in kinds.items():
                    if kname == prop and val in kvals:
                        w(f'{indent}{kvals.index(val)} player-{prop} !')
                        resolved = True
                        break
                if not resolved:
                    try:
                        w(f'{indent}{int(val)} player-{prop} !')
                    except ValueError:
                        w(f'{indent}// unresolved: set player {prop}: {val}')

    def emit_turn_actions(actions, indent='  '):
        """Turn handler emission: go first (clears screen), then say, then show-room."""
        goes = [a for a in actions if a[0] == 'go']
        says = [a for a in actions if a[0] == 'say']
        rest = [a for a in actions if a[0] not in ('go', 'say')]
        for act in goes:
            dest = act[1]
            if dest in room_ids:
                w(f'{indent}{room_const(dest)} auto-go')
            else:
                w(f'{indent}// unresolved: go {dest}')
        for act in says:
            w(f'{indent}{q(act[1])} println')
        emit_actions(rest, indent)
        if goes:
            w(f'{indent}"" println')
            w(f'{indent}show-room')

    def room_dispatch(word_name, handler_key, extra_body=None):
        """Emit an if/elsif/end dispatch word over all rooms that have handler_key."""
        w(f': {word_name}')
        first   = True
        has_any = False
        for room in rooms:
            if handler_key not in room['handlers']:
                continue
            kw = 'if' if first else 'elsif'
            first = False
            has_any = True
            w(f'  {kw} current-room @ {room_const(room["id"])} ==:')
            emit_actions(room['handlers'][handler_key], indent='    ')
            if extra_body:
                for line in extra_body:
                    w(f'    {line}')
        if has_any:
            w('  end')
        w(';')
        w('')

    # ---- header ----
    w('// Generated by gruc.  Do not edit by hand.')
    w('')

    # Kind enums as comments
    for kname, kvals in kinds.items():
        enum = '  '.join(f'{v}={i}' for i, v in enumerate(kvals))
        w(f'// {kname}: {enum}')
    w('')

    # Room constants
    for i, room in enumerate(rooms):
        w(f'{i} constant {room_const(room["id"])}')
    w('')

    # Player state variables
    for prop in player:
        w(f'variable player-{prop}')
    w('variable current-room')
    w('variable game-running')
    w('')

    # game-init
    w(': game-init')
    w(f'  {room_const(rooms[0]["id"])} current-room !')
    w('  1 game-running !')
    for prop, val in player.items():
        if isinstance(val, int):
            w(f'  {val} player-{prop} !')
        else:
            resolved = False
            for kname, kvals in kinds.items():
                if kname == prop and val in kvals:
                    w(f'  {kvals.index(val)} player-{prop} !')
                    resolved = True
                    break
            if not resolved:
                w(f'  0 player-{prop} !')
    w(';')
    w('')

    # room-name  ( -- str )
    w(': room-name')
    for i, room in enumerate(rooms):
        kw = 'if' if i == 0 else 'elsif'
        w(f'  {kw} current-room @ {room_const(room["id"])} ==:')
        w(f'    {q(room["name"])}')
    w('  else:')
    w('    "Unknown Room"')
    w('  end')
    w(';')
    w('')

    # room-desc  ( -- )
    w(': room-desc')
    for i, room in enumerate(rooms):
        kw = 'if' if i == 0 else 'elsif'
        w(f'  {kw} current-room @ {room_const(room["id"])} ==:')
        w(f'    {q(room["desc"])} println')
    w('  end')
    w(';')
    w('')

    # try-exit  ( dir-str -- dest|-1 )
    w(': try-exit')
    for i, room in enumerate(rooms):
        kw = 'if' if i == 0 else 'elsif'
        w(f'  {kw} current-room @ {room_const(room["id"])} ==:')
        exits = list(room['exits'].items())
        if exits:
            for j, (direction, dest) in enumerate(exits):
                ew = 'if' if j == 0 else 'elsif'
                w(f'    {ew} dup {q(direction)} ==:')
                w(f'      drop {room_const(dest)}')
            w('    else:')
            w('      drop -1')
            w('    end')
        else:
            w('    drop -1')
    w('  else:')
    w('    drop -1')
    w('  end')
    w(';')
    w('')

    # do-arrive  ( -- )
    room_dispatch('do-arrive', 'arrive')

    # do-turn  ( -- )
    w(': do-turn')
    first   = True
    has_any = False
    for room in rooms:
        if 'turn' not in room['handlers']:
            continue
        kw = 'if' if first else 'elsif'
        first = False
        has_any = True
        w(f'  {kw} current-room @ {room_const(room["id"])} ==:')
        emit_turn_actions(room['handlers']['turn'], indent='    ')
    if has_any:
        w('  end')
    w(';')
    w('')

    # player-go  ( dir -- )
    # Rooms with instead_go block movement; others do actual exit lookup.
    w(': player-go')
    first = True
    for room in rooms:
        if 'instead_go' not in room['handlers']:
            continue
        kw = 'if' if first else 'elsif'
        first = False
        w(f'  {kw} current-room @ {room_const(room["id"])} ==:')
        emit_actions(room['handlers']['instead_go'], indent='    ')
    w('  else:')
    w('    try-exit')
    w('    if dup -1 ==:')
    w('      drop "You can\'t go that way." println')
    w('    else:')
    w('      auto-go')
    w('      show-room')
    w('    end')
    w('  end')
    w(';')
    w('')

    # do-examine  ( obj-str -- )
    w(': do-examine')
    for i, room in enumerate(rooms):
        kw = 'if' if i == 0 else 'elsif'
        w(f'  {kw} current-room @ {room_const(room["id"])} ==:')
        objs = room['objects']
        if objs:
            for j, obj in enumerate(objs):
                ow = 'if' if j == 0 else 'elsif'
                w(f'    {ow} dup {q(obj["id"])} ==:')
                w(f'      drop {q(obj["desc"])} println')
            w('    else:')
            w('      drop "You see nothing special." println')
            w('    end')
        else:
            w('    drop "You see nothing special." println')
    w('  else:')
    w('    drop "You see nothing special." println')
    w('  end')
    w(';')
    w('')

    # list-exits  ( -- )
    w(': list-exits')
    for i, room in enumerate(rooms):
        kw = 'if' if i == 0 else 'elsif'
        w(f'  {kw} current-room @ {room_const(room["id"])} ==:')
        exits = list(room['exits'].keys())
        if exits:
            w(f'    "Exits: " print')
            for ex in exits:
                w(f'    "{ex}  " print')
        else:
            w(f'    "No obvious exits." print')
    w('  end')
    w('  "" println')
    w(';')
    w('')

    # list-exits-inline  ( -- )  — compact exits for status bar, no newline
    _T46_COLS = 79
    _SEP      = '-' * _T46_COLS
    _BLANK    = ' ' * _T46_COLS
    w(': list-exits-inline')
    for i, room in enumerate(rooms):
        kw = 'if' if i == 0 else 'elsif'
        w(f'  {kw} current-room @ {room_const(room["id"])} ==:')
        exits = list(room['exits'].keys())
        if exits:
            for ex in exits:
                w(f'    "{ex}  " print')
        else:
            w(f'    "none" print')
    w('  end')
    w(';')
    w('')

    # t-draw-fixed  ( -- )  — (re)draw separator + status bar; cursor ends at row 24
    w(': t-draw-fixed')
    w(f'  23 0 t46-goto')
    w(f'  {q(_SEP)} print')
    w(f'  24 0 t46-goto')
    w(f'  {q(_BLANK)} print')
    w(f'  24 0 t46-goto')
    w(f'  "  " print  room-name print  "   exits: " print  list-exits-inline')
    w(';')
    w('')

    # t-setup  ( -- )  — clear screen, set scroll region, draw fixed bars, home cursor
    w(': t-setup')
    w('  t46-cls')
    w('  22 t46-scroll')
    w('  t-draw-fixed')
    w('  0 0 t46-goto')
    w(';')
    w('')

    # t-restore  ( -- )  — return terminal to normal on exit
    w(': t-restore')
    w('  24 t46-scroll')
    w('  t46-cls')
    w(';')
    w('')

    # auto-go  ( dest -- )  — transition only: store room, clear, redraw status, home cursor
    w(': auto-go')
    w('  current-room !')
    w('  t46-cls')
    w('  t-draw-fixed')
    w('  0 0 t46-goto')
    w(';')
    w('')

    # show-room  ( -- )  — print room name, desc, and arrive text
    w(': show-room')
    w('  "" println')
    w('  room-name println')
    w('  "" println')
    w('  room-desc')
    w('  "" println')
    w('  do-arrive')
    w(';')
    w('')

    # do-look  ( -- )
    w(': do-look')
    w('  "You are in the " print  room-name print  "." println')
    w('  "" println')
    w('  room-desc')
    w('  "" println')
    w('  list-exits')
    w(';')
    w('')

    # handle-input  ( str -- )
    w(': handle-input')
    w('  words')
    w('  if dup length 0 ==:')
    w('    drop')
    w('  else:')
    w('    dup 0 nth')
    # direction shortcuts → player-go
    dirs = [('n','north'),('s','south'),('e','east'),('w','west'),
            ('ne','northeast'),('nw','northwest'),('se','southeast'),('sw','southwest'),
            ('u','up'),('d','down')]
    first = True
    for short, full in dirs:
        kw = 'if' if first else 'elsif'
        first = False
        w(f'    {kw} dup {q(short)} ==:')
        w(f'      drop drop {q(full)} player-go')
    w(f'    elsif dup "z" ==:')
    w(f'      drop drop "You wait." println')
    w(f'    elsif dup "wait" ==:')
    w(f'      drop drop "You wait." println')
    w(f'    elsif dup "l" ==:')
    w(f'      drop drop do-look')
    w(f'    elsif dup "look" ==:')
    w(f'      drop drop do-look')
    w(f'    elsif dup "go" ==:')
    w(f'      drop')
    w(f'      if dup length 1 >:')
    w(f'        1 nth player-go')
    w(f'      else:')
    w(f'        drop "Go where?" println')
    w(f'      end')
    w(f'    elsif dup "x" ==:')
    w(f'      drop')
    w(f'      if dup length 1 >:')
    w(f'        1 nth do-examine')
    w(f'      else:')
    w(f'        drop "Examine what?" println')
    w(f'      end')
    w(f'    elsif dup "examine" ==:')
    w(f'      drop')
    w(f'      if dup length 1 >:')
    w(f'        1 nth do-examine')
    w(f'      else:')
    w(f'        drop "Examine what?" println')
    w(f'      end')
    w(f'    elsif dup "quit" ==:')
    w(f'      drop drop t-restore 0 game-running !')
    w(f'    elsif dup "q" ==:')
    w(f'      drop drop t-restore 0 game-running !')
    w(f'    else:')
    w(f'      drop drop "I don\'t understand that." println')
    w(f'    end')
    w('  end')
    w(';')
    w('')

    # game loop
    w(': game')
    w('  game-init')
    w('  t-setup')
    w('  show-room')
    w('  while game-running @:')
    w('    "" println')
    w('    "> " print')
    w('    readline')
    w('    handle-input')
    w('    do-turn')
    w('  end')
    w(';')
    w('')
    w('game')

    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print('usage: grue.py <file.grue> [output.pi]', file=sys.stderr)
        sys.exit(1)

    src_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path('/tmp') / src_path.with_suffix('.pi').name

    try:
        source = src_path.read_text()
    except OSError as e:
        print(f'grue: {e}', file=sys.stderr)
        sys.exit(1)

    try:
        ast = parse(source)
        pi  = emit(ast)
    except GrueError as e:
        print(f'grue: {e}', file=sys.stderr)
        sys.exit(1)

    out_path.write_text(pi)
    rooms = len(ast['rooms'])
    print(f'compiled {src_path.name} → {out_path}  ({rooms} rooms)')


if __name__ == '__main__':
    main()
