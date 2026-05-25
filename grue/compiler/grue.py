"""
grue — Grue to Inform 6 transpiler

Reads a .grue source file and emits an Inform 6 .inf file.
If test blocks are present a companion .gts (JSON) file is written.

Usage:
    python3 grue.py game.grue            # writes bin/game.inf (+ .gts if tests)
    python3 grue.py game.grue out.inf    # explicit output path
"""

import json
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class GrueError(Exception):
    pass


# ---------------------------------------------------------------------------
# Preprocessor — join multi-line quoted strings onto one line
# ---------------------------------------------------------------------------

def _preprocess(source: str) -> str:
    lines = source.splitlines()
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith('#') or not stripped:
            out.append(line)
            i += 1
            continue
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
    s = s.strip()
    m = re.match(r'"(.*)"', s)
    if m:
        return m.group(1)
    raise GrueError(f'expected quoted string, got: {s!r}')


# ---------------------------------------------------------------------------
# Parser — Python-style indentation
#
# Each block opener records the column it appeared on.  Any subsequent line
# at or before that column closes the block (exactly like Python's dedent).
# No hardcoded column numbers — purely relative indentation.
# Tabs are expanded to 4-space stops before measuring.
# ---------------------------------------------------------------------------

def parse(source: str) -> dict:
    """
    Returns:
    {
      uses:  [library_name, ...]
      rooms: [
        { id, name, desc, exits: {dir: room_name},
          objects: [{ id, keywords, name, desc, behaviours, properties, kind }],
          handlers: {key: [(verb, arg), ...]} }
      ]
      tests: [{ name, commands: [{ cmd, expect }] }]
    }
    """
    source = _preprocess(source)
    ast    = {'uses': [], 'rooms': [], 'tests': []}

    current_room    = None;  room_col    = -1
    current_object  = None;  obj_col     = -1
    current_handler = None;  handler_col = -1
    current_test    = None;  test_col    = -1

    for raw in source.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith('#'):
            continue

        col = len(raw.expandtabs(4)) - len(raw.expandtabs(4).lstrip())

        # Close inner blocks whose opener is at or after the current column
        if current_handler is not None and col <= handler_col:
            current_handler = None
        if current_object is not None and col <= obj_col:
            current_object = None
        if current_room is not None and col <= room_col:
            current_room = None
        if current_test is not None and col <= test_col:
            current_test = None

        # ---- dispatch on active context, innermost first -----------------

        if current_test is not None:
            dot = stripped.find('.')
            if dot >= 0:
                cmd    = stripped[:dot].strip()
                rest   = stripped[dot + 1:].strip()
                expect = _extract_string(rest) if rest.startswith('"') else None
            else:
                cmd    = stripped
                expect = None
            if cmd:
                current_test['commands'].append({'cmd': cmd, 'expect': expect})

        elif current_object is not None:
            if stripped.startswith('"'):
                current_object['desc'] = _extract_string(stripped)
            elif stripped.startswith('is '):
                current_object['behaviours'].append(stripped[3:].rstrip('.').strip())
            elif re.match(r'\w+:\s+\S', stripped):
                m = re.match(r'(\w+):\s+(.+)', stripped)
                if m:
                    current_object['properties'][m.group(1)] = m.group(2).rstrip('.')
            elif re.match(r'\w+\s*=\s*\w+', stripped):
                m = re.match(r'(\w+)\s*=\s*(\w+)', stripped)
                if m:
                    current_object['properties'][m.group(1)] = m.group(2)

        elif current_handler is not None:
            if stripped.startswith('say '):
                current_handler.append(('say', _extract_string(stripped[4:])))
            elif stripped.startswith('go '):
                current_handler.append(('go', stripped[3:].strip().strip('"')))

        elif current_room is not None:
            if stripped.startswith('"'):
                current_room['desc'] = _extract_string(stripped)

            elif re.match(r'(north|south|east|west|up|down|ne|nw|se|sw):?\s+"', stripped, re.I):
                m = re.match(r'(\w+):?\s+"([^"]*)"', stripped)
                if m:
                    current_room['exits'][m.group(1).lower()] = m.group(2)

            # exit via door object:  east blue_door  (unquoted identifier)
            elif re.match(r'(north|south|east|west|up|down|ne|nw|se|sw):?\s+\w+\s*$', stripped, re.I):
                m = re.match(r'(\w+):?\s+(\w+)', stripped)
                if m:
                    current_room['exits'][m.group(1).lower()] = m.group(2)

            elif re.match(r'(object|scenery|man|woman|robot|door)\s+', stripped):
                kind    = stripped.split()[0]
                rest    = stripped[len(kind):].strip()
                if '"' in rest:
                    idx     = rest.index('"')
                    kw_part = rest[:idx].strip()
                    display = _extract_string(rest[idx:])
                else:
                    kw_part = rest
                    display = ''
                keywords = [w.strip().strip(',') for w in kw_part.split() if w.strip().strip(',')]
                obj_id   = '_'.join(keywords) if keywords else _to_id(display)
                current_object = {
                    'id': obj_id, 'keywords': keywords, 'name': display,
                    'desc': '', 'behaviours': [], 'properties': {}, 'kind': kind,
                }
                obj_col = col
                current_room['objects'].append(current_object)

            elif re.match(r'(instead of|on|after)\s+', stripped):
                key = stripped.rstrip(':')
                current_handler = []
                handler_col = col
                current_room['handlers'][key] = current_handler

        else:
            # top level
            if stripped.startswith('uses '):
                ast['uses'].append(stripped[5:].rstrip('.').strip())

            elif stripped.startswith('room '):
                # room <id> "Name"  or  room "Name"  (id auto-derived)
                m = re.match(r'room\s+(\w+)\s+"([^"]*)"', stripped)
                if m:
                    rid, rname = m.group(1), m.group(2)
                else:
                    m2 = re.match(r'room\s+"([^"]*)"', stripped)
                    if not m2:
                        raise GrueError(f'bad room: {stripped!r}')
                    rname = m2.group(1)
                    rid   = _to_id(rname)
                current_room = {
                    'id': rid, 'name': rname, 'desc': '',
                    'exits': {}, 'objects': [], 'handlers': {},
                }
                room_col = col
                ast['rooms'].append(current_room)

            elif stripped.startswith('test '):
                m = re.match(r'test\s+"([^"]*)"', stripped)
                if m:
                    current_test = {'name': m.group(1), 'commands': []}
                    test_col = col
                    ast['tests'].append(current_test)

    return ast


# ---------------------------------------------------------------------------
# Inform 6 helpers
# ---------------------------------------------------------------------------

_DIR_MAP = {
    'north': 'n_to', 'south': 's_to', 'east':  'e_to', 'west':  'w_to',
    'up':    'u_to', 'down':  'd_to',
    'ne': 'ne_to',   'nw': 'nw_to',   'se': 'se_to',   'sw': 'sw_to',
}

def _to_id(name: str) -> str:
    s = name.lower().replace("'", '')
    s = re.sub(r'[^a-z0-9]+', '_', s).strip('_')
    return ('o_' + s) if s and s[0].isdigit() else (s or 'unnamed')

def _i6str(s: str) -> str:
    s = re.sub(r'\s+', ' ', s).strip()
    return s.replace('"', '~')

def _obj_attributes(obj: dict) -> str:
    attrs = []
    kind  = obj['kind']
    props = obj['properties']
    behs  = obj['behaviours']

    if kind == 'scenery':
        attrs.append('scenery')
    if kind in ('man', 'woman', 'robot'):
        attrs.append('animate')
    if kind == 'woman':
        attrs.append('female')
    if 'openable' in behs:
        attrs.append('openable')
        if props.get('containment') == 'open':
            attrs.append('open')
    if 'lockable' in behs:
        attrs.append('lockable')
        if props.get('security') == 'locked':
            attrs.append('locked')
    if 'container' in behs:
        attrs.append('container')
    if 'supporter' in behs:
        attrs.append('supporter')

    return ' '.join(attrs)


# ---------------------------------------------------------------------------
# Inform 6 object emitters
# ---------------------------------------------------------------------------

def _emit_object(w, obj: dict, parent: str):
    oid   = obj['id']
    attrs = _obj_attributes(obj)
    kws   = ' '.join(f"'{k}'" for k in obj['keywords']) if obj['keywords'] else ''
    loc   = obj['properties'].get('inside', parent)

    w(f'Object {oid} "{_i6str(obj["name"])}" {loc}')
    if kws:
        w(f'    with name {kws},')
    w(f'         description "{_i6str(obj["desc"])}",')
    if 'key' in obj['properties']:
        w(f'         with_key {obj["properties"]["key"]},')
    w(f'    has {attrs};' if attrs else '    has ;')
    w('')


def _emit_door(w, obj: dict, parent_rid: str, door_map: dict):
    oid  = obj['id']
    kws  = ' '.join(f"'{k}'" for k in obj['keywords']) if obj['keywords'] else ''
    _, _, dest_rid = door_map[oid]

    attrs = 'door openable'
    if 'lockable' in obj['behaviours']:
        attrs += ' lockable'
        if obj['properties'].get('security') == 'locked':
            attrs += ' locked'

    w(f'Object {oid} "{_i6str(obj["name"])}" {parent_rid}')
    if kws:
        w(f'    with name {kws},')
    w(f'         description "{_i6str(obj["desc"])}",')
    w(f'         door_to [; if (location == {parent_rid}) return {dest_rid};')
    w(f'                    return {parent_rid}; ],')
    if 'key' in obj['properties']:
        w(f'         with_key {obj["properties"]["key"]},')
    w(f'    has {attrs};')
    w('')


# ---------------------------------------------------------------------------
# Inform 6 emitter
# ---------------------------------------------------------------------------

def emit_i6(ast: dict) -> str:
    rooms = ast['rooms']
    if not rooms:
        raise GrueError('no rooms defined')

    lines = []
    w     = lines.append

    title = rooms[0]['name']

    w(f'Constant Story "{_i6str(title)}";')
    w( 'Constant Headline "^An Interactive Fiction^";')
    w( 'Constant MAX_SCORE 0;')
    w('')
    w('Include "Parser";')
    w('Include "VerbLib";')
    w('')

    # Both name→id and id→id so exits resolve whether the author
    # wrote  north "Display Name"  or  north "room_id"
    room_by_name = {r['name']: r['id'] for r in rooms}
    room_by_id   = {r['id']:   r['id'] for r in rooms}

    # door_id → (door_obj, parent_room_id, dest_room_id)
    door_map = {}
    for room in rooms:
        for obj in room['objects']:
            if obj['kind'] == 'door':
                dest_name = obj['properties'].get('leads', '')
                dest_id   = (room_by_name.get(dest_name)
                             or room_by_id.get(dest_name)
                             or _to_id(dest_name))
                door_map[obj['id']] = (obj, room['id'], dest_id)

    for room in rooms:
        rid = room['id']
        w(f'Object {rid} "{_i6str(room["name"])}"')
        w( '    with description')
        w(f'        "{_i6str(room["desc"])}",')
        for direction, dest in room['exits'].items():
            i6dir = _DIR_MAP.get(direction, direction + '_to')
            if dest in door_map:
                w(f'         {i6dir} {dest},')
            else:
                dest_id = room_by_name.get(dest) or room_by_id.get(dest) or _to_id(dest)
                w(f'         {i6dir} {dest_id},')
        w( '    has light;')
        w('')

        for obj in room['objects']:
            if obj['kind'] == 'door':
                _emit_door(w, obj, rid, door_map)
            else:
                _emit_object(w, obj, rid)

    w('Include "Grammar";')
    w('')
    w('[ Initialise;')
    w(f'    location = {rooms[0]["id"]};')
    w(f'    print "^^{_i6str(title)}^^^";')
    w('];')

    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print('usage: grue.py <file.grue> [output.inf]', file=sys.stderr)
        sys.exit(1)

    src_path = Path(sys.argv[1])
    out_path = (Path(sys.argv[2]) if len(sys.argv) > 2
                else Path('/tmp') / src_path.with_suffix('.inf').name)

    try:
        source = src_path.read_text()
    except OSError as e:
        print(f'grue: {e}', file=sys.stderr)
        sys.exit(1)

    try:
        ast = parse(source)
        inf = emit_i6(ast)
    except GrueError as e:
        print(f'grue: {e}', file=sys.stderr)
        sys.exit(1)

    out_path.write_text(inf)

    tests = ast['tests']
    if tests:
        gts_path = out_path.with_suffix('.gts')
        gts_path.write_text(json.dumps(tests, indent=2))
        print(f'compiled {src_path.name} → {out_path}  '
              f'({len(ast["rooms"])} rooms, {len(tests)} tests → {gts_path.name})')
    else:
        print(f'compiled {src_path.name} → {out_path}  ({len(ast["rooms"])} rooms)')


if __name__ == '__main__':
    main()
