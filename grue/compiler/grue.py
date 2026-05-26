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
# ---------------------------------------------------------------------------

def _parse_keywords(rest: str) -> tuple:
    """Parse 'keyword keyword, synonym "desc"' → (keywords, display, obj_id, inline_desc)."""
    if '"' in rest:
        idx         = rest.index('"')
        kw_part     = rest[:idx].strip()
        inline_desc = _extract_string(rest[idx:])
    else:
        kw_part     = rest
        inline_desc = ''
    keywords = [w.strip().strip(',') for w in kw_part.split() if w.strip().strip(',')]
    proper   = bool(keywords) and keywords[0][0].isupper()
    if ',' in kw_part and keywords:
        display = keywords[0] if proper else keywords[0].lower()
        obj_id  = _to_id(keywords[0])
    else:
        display = ' '.join(keywords) if proper else ' '.join(k.lower() for k in keywords) if keywords else ''
        obj_id  = '_'.join(k.lower() for k in keywords) if keywords else _to_id(inline_desc)
    return keywords, display, obj_id, inline_desc


def _append_stmt(stmts: list, stripped: str) -> None:
    if stripped.startswith('say '):
        stmts.append({'type': 'say', 'arg': _extract_string(stripped[4:])})
    elif stripped.startswith('go '):
        stmts.append({'type': 'go', 'arg': stripped[3:].strip().strip('"')})
    elif stripped.startswith('box '):
        stmts.append({'type': 'box', 'arg': _extract_string(stripped[4:])})
    else:
        word = stripped.rstrip('.')
        m = re.match(r'the\s+(\w+)\s+is\s+(not\s+)?(\w+)$', word)
        if m:
            subj     = m.group(1)
            neg_kw   = bool(m.group(2))
            raw_attr = m.group(3)
            attr     = _NEGATION.get(raw_attr, raw_attr)
            neg      = neg_kw or raw_attr in _NEGATION
            stmts.append({'type': 'give', 'subj': subj, 'attr': attr, 'neg': neg})
        elif re.match(r'not\s+\w+$', word):
            raw_attr = word.split(None, 1)[1]
            attr     = _NEGATION.get(raw_attr, raw_attr)
            stmts.append({'type': 'give', 'subj': 'self', 'attr': attr, 'neg': True})
        elif re.match(r'\w+$', word):
            raw_attr = word
            attr     = _NEGATION.get(raw_attr, raw_attr)
            neg      = raw_attr in _NEGATION
            stmts.append({'type': 'give', 'subj': 'self', 'attr': attr, 'neg': neg})


def parse(source: str) -> dict:
    source = _preprocess(source)
    ast = {'uses': [], 'rooms': [], 'verbs': [], 'tests': []}

    current_room    = None;  room_col    = -1
    current_object  = None;  obj_col     = -1
    current_handler = None;  handler_col = -1
    current_if      = None;  if_col      = -1;  if_branch = 'then'
    current_test    = None;  test_col    = -1
    current_verb    = None;  verb_col    = -1

    for raw in source.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith('#'):
            continue

        col = len(raw.expandtabs(4)) - len(raw.expandtabs(4).lstrip())

        # ---- Close blocks innermost-first --------------------------------

        if current_if is not None and col <= if_col:
            if stripped == 'else:' and if_branch == 'then':
                current_if['else'] = []
                if_branch = 'else'
                continue
            if current_handler is not None:
                current_handler.append(current_if)
            current_if = None; if_col = -1; if_branch = 'then'

        if current_handler is not None and col <= handler_col:
            current_handler = None

        if current_object is not None and col <= obj_col:
            current_object = None

        if current_room is not None and col <= room_col:
            current_room = None

        if current_test is not None and col <= test_col:
            current_test = None

        if current_verb is not None and col <= verb_col:
            current_verb = None

        # ---- Dispatch on active context, innermost first -----------------

        if current_test is not None:
            dot = stripped.find('.')
            if dot >= 0:
                cmd    = stripped[:dot].strip()
                rest   = stripped[dot + 1:].strip()
                if rest.lower().startswith('not '):
                    expect = _extract_string(rest[4:])
                    negate = True
                elif rest.startswith('"'):
                    expect = _extract_string(rest)
                    negate = False
                else:
                    expect = None
                    negate = False
            else:
                cmd    = stripped
                expect = None
                negate = False
            if cmd:
                entry = {'cmd': cmd, 'expect': expect}
                if negate:
                    entry['negate'] = True
                current_test['commands'].append(entry)

        elif current_if is not None:
            branch = current_if[if_branch]
            if branch is None:
                branch = current_if['then']
            _append_stmt(branch, stripped)

        elif current_handler is not None:
            m = re.match(r'if\s+(not\s+)?(\w+)\s*:', stripped)
            if m:
                neg_kw   = bool(m.group(1))
                raw_attr = m.group(2)
                attr     = _NEGATION.get(raw_attr, raw_attr)
                neg      = neg_kw or raw_attr in _NEGATION
                current_if = {'type': 'if', 'attr': attr, 'neg': neg, 'then': [], 'else': None}
                if_col = col
                if_branch = 'then'
            else:
                _append_stmt(current_handler, stripped)

        elif current_object is not None:
            if re.match(r'(instead of|on|after|each)\s+', stripped):
                key = stripped.rstrip(':')
                current_handler = []
                handler_col = col
                current_object['handlers'][key] = current_handler
            elif stripped.startswith('"'):
                current_object['desc'] = _extract_string(stripped)
            elif stripped.startswith('is '):
                word = stripped[3:].rstrip('.').strip()
                if word in _BEHAVIOURS:
                    current_object['behaviours'].append(word)
                else:
                    attr = _NEGATION.get(word, word)
                    current_object['properties'][attr] = 'false' if word in _NEGATION else 'true'
            elif re.match(r'\w+:\s+\S', stripped):
                m = re.match(r'(\w+):\s+(.+)', stripped)
                if m:
                    current_object['properties'][m.group(1)] = m.group(2).rstrip('.')
            elif re.match(r'\w+\s*=\s*\w+', stripped):
                m = re.match(r'(\w+)\s*=\s*(\w+)', stripped)
                if m:
                    current_object['properties'][m.group(1)] = m.group(2)

        elif current_room is not None:
            if stripped.startswith('"'):
                current_room['desc'] = _extract_string(stripped)

            elif re.match(r'(north|south|east|west|up|down|ne|nw|se|sw):?\s+"', stripped, re.I):
                m = re.match(r'(\w+):?\s+"([^"]*)"', stripped)
                if m:
                    current_room['exits'][m.group(1).lower()] = m.group(2)

            elif re.match(r'(north|south|east|west|up|down|ne|nw|se|sw):?\s+\w+\s*$', stripped, re.I):
                m = re.match(r'(\w+):?\s+(\w+)', stripped)
                if m:
                    current_room['exits'][m.group(1).lower()] = m.group(2)

            elif re.match(r'(object|scenery|man|woman|robot|door)\s+', stripped):
                kind = stripped.split()[0]
                keywords, display, obj_id, inline_desc = _parse_keywords(stripped[len(kind):].strip())
                current_object = {
                    'id': obj_id, 'keywords': keywords, 'name': display,
                    'desc': inline_desc, 'behaviours': [], 'properties': {},
                    'kind': kind, 'handlers': {},
                }
                obj_col = col
                current_room['objects'].append(current_object)

            elif re.match(r'(instead of|on|after|each)\s+', stripped):
                key = stripped.rstrip(':')
                current_handler = []
                handler_col = col
                current_room['handlers'][key] = current_handler

        elif current_verb is not None:
            if stripped.startswith('*'):
                current_verb['grammar'].append(stripped)
            elif stripped.startswith('"'):
                current_verb['default'] = _extract_string(stripped)

        else:
            # top level
            if stripped.startswith('uses '):
                ast['uses'].append(stripped[5:].rstrip('.').strip())

            elif stripped.startswith('verb '):
                words_part = stripped[5:].rstrip('.')
                words = [w.strip().strip(',') for w in words_part.split() if w.strip().strip(',')]
                # Only comma-separated words are I6 synonyms; space-only extras are variant markers
                synonyms = [w.strip() for w in words_part.split(',') if w.strip()]
                synonyms = [synonyms[0].split()[0]] + [s.strip() for s in synonyms[1:]] if synonyms else words[:1]
                current_verb = {'words': words, 'synonyms': synonyms, 'grammar': [], 'default': ''}
                verb_col = col
                ast['verbs'].append(current_verb)

            elif stripped.startswith('room '):
                rest = stripped[5:]
                m = re.match(r'(.+)\s+"([^"]*)"$', rest.strip())
                if m:
                    rname = m.group(1).strip().strip('"')
                    desc  = m.group(2)
                else:
                    rname = rest.strip().strip('"')
                    desc  = ''
                rid = _to_id(rname)
                current_room = {
                    'id': rid, 'name': rname, 'desc': desc,
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

_OPPOSITE_DIR = {
    'north': 'south', 'south': 'north', 'east': 'west',  'west': 'east',
    'up':    'down',  'down':  'up',
    'ne': 'sw', 'sw': 'ne', 'nw': 'se', 'se': 'nw',
}

_STD_ACTIONS = {
    'open': 'Open', 'opening': 'Open',
    'close': 'Close', 'closing': 'Close',
    'take': 'Take', 'taking': 'Take',
    'drop': 'Drop', 'dropping': 'Drop',
    'examine': 'Examine', 'examining': 'Examine',
    'unlock': 'UnlockWith', 'unlocking': 'UnlockWith',
    'lock': 'LockWith', 'locking': 'LockWith',
    'insert': 'Insert', 'inserting': 'Insert',
    'put': 'PutOn', 'putting': 'PutOn',
    'push': 'Push', 'pushing': 'Push',
    'pull': 'Pull', 'pulling': 'Pull',
    'turn': 'Turn', 'turning': 'Turn',
    'attack': 'Attack', 'attacking': 'Attack',
}

# Known behaviour keywords — everything else after 'is' sets a boolean attribute.
_BEHAVIOURS = {'openable', 'lockable', 'container', 'supporter'}

# Friendly negation aliases: word → (canonical_attr, negated).
# 'closed' means hasnt open; 'unlocked' means hasnt locked; etc.
_NEGATION = {
    'close':    'open',
    'closed':   'open',
    'unlocked': 'locked',
    'off':      'on',
}


def _to_id(name: str) -> str:
    s = name.lower().replace("'", '')
    s = re.sub(r'[^a-z0-9]+', '_', s).strip('_')
    return ('o_' + s) if s and s[0].isdigit() else (s or 'unnamed')


def _i6str(s: str) -> str:
    s = s.replace('\\n', '^').replace('\\t', '@@9')
    s = re.sub(r'\s+', ' ', s).strip()
    return s.replace('"', '~')


def _i6box_line(s: str) -> str:
    """Encode one line of a box quotation — no newline translation."""
    s = s.replace('\\t', '@@9')
    s = re.sub(r'\s+', ' ', s).strip()
    return s.replace('"', '~')


def _degerund(word: str) -> str:
    if word.endswith('ying'):
        return word[:-4] + 'y'
    if word.endswith('ing'):
        stem = word[:-3]
        if len(stem) >= 2 and stem[-1] == stem[-2] and stem[-1] not in 'aeiou':
            return stem[:-1]
        return stem
    return word


def _verb_action_name(verb: dict) -> str:
    first = verb['words'][0].capitalize()
    for g in verb['grammar']:
        tokens = g.split()
        if 'held' in tokens or "'with'" in tokens:
            return first + 'With'
    return first


def _parse_handler_key(key: str, verb_action_map: dict) -> tuple:
    """Return (action_name, second_filter_id_or_None)."""
    rest = key
    for prefix in ('instead of ', 'on ', 'after '):
        if key.startswith(prefix):
            rest = key[len(prefix):]
            break

    words = rest.strip().split()
    if not words:
        return ('NoAction', None)

    base = _degerund(words[0])

    second = None
    if 'with' in words:
        wi = words.index('with')
        if wi + 1 < len(words):
            second = _to_id(words[wi + 1])

    has_with = 'with' in words
    if base in _STD_ACTIONS:
        action = _STD_ACTIONS.get(base + ':with' if has_with else base) or _STD_ACTIONS[base]
        return (action, second)
    with_key = base + ':with'
    if has_with and with_key in verb_action_map:
        return (verb_action_map[with_key], second)
    if base in verb_action_map:
        return (verb_action_map[base], second)
    return (base.capitalize(), second)


def _obj_attributes(obj: dict) -> str:
    attrs = []
    kind  = obj['kind']
    props = obj['properties']
    behs  = obj['behaviours']

    if kind == 'scenery':
        attrs.append('scenery')
    if kind in ('man', 'woman', 'robot'):
        attrs.append('animate')
        if obj.get('keywords') and obj['keywords'][0][0].isupper():
            attrs.append('proper')
    if kind == 'woman':
        attrs.append('female')
    if 'openable' in behs:
        attrs.append('openable')
    if 'lockable' in behs:
        attrs.append('lockable')
    if 'container' in behs:
        attrs.append('container')
    if 'supporter' in behs:
        attrs.append('supporter')

    for key, val in props.items():
        if val == 'true':
            attrs.append(key)

    return ' '.join(attrs)


# ---------------------------------------------------------------------------
# Statement and handler emitters
# ---------------------------------------------------------------------------

_PROP   = '         '    # 9 spaces — aligns with 'description', 'name', etc.
_ACTION = '             '  # 13 spaces
_STMT0  = '                 '  # 17 spaces

_INTERP_RE = re.compile(r'\{([^}]+)\}')

# Inform 6 runtime variables that hold object references
_I6_OBJ_VARS = {'noun', 'second', 'self', 'actor', 'location'}


def _emit_say(w, text: str, prefix: str, known_ids: set) -> None:
    """Emit a print statement, resolving {identifier} interpolations."""
    parts = []
    last = 0
    for m in _INTERP_RE.finditer(text):
        if m.start() > last:
            parts.append(('lit', text[last:m.start()]))
        parts.append(('var', m.group(1).strip()))
        last = m.end()
    if last < len(text):
        parts.append(('lit', text[last:]))
    if not parts:
        parts = [('lit', '')]

    def _after_stop(idx):
        """True if position idx follows a sentence-ending period."""
        if idx == 0:
            return False
        prev_kind, prev_val = parts[idx - 1]
        return prev_kind == 'lit' and prev_val.rstrip().endswith('.')

    items = []
    for i, (kind, val) in enumerate(parts):
        is_last = (i == len(parts) - 1)
        if kind == 'lit':
            escaped = re.sub(r'\s+', ' ', val.replace('\\n', '^').replace('\\t', '@@9')).replace('"', '~')
            items.append('"' + escaped + ('^' if is_last else '') + '"')
        else:
            article, _, ident = val.partition(' ')
            obj_ids = known_ids | _I6_OBJ_VARS
            if article == 's' and ident:
                items.append(f'(Grue_s) {ident}')
            elif article in ('the', 'a') and ident in obj_ids:
                cap = _after_stop(i)
                items.append(f'({article.capitalize() if cap else article}) {ident}')
            elif val in obj_ids:
                items.append(f'(name) {val}')
            else:
                items.append(val)
            if is_last:
                items.append('"^"')

    w(f'{prefix}print {", ".join(items)};')


def _emit_stmts(w, stmts: list, prefix: str, known_ids: set) -> None:
    """Emit statements. Caller is responsible for adding a trailing rtrue."""
    for stmt in stmts:
        t = stmt['type']
        if t == 'say':
            _emit_say(w, stmt['arg'], prefix, known_ids)
        elif t == 'give':
            tilde = '~' if stmt['neg'] else ''
            w(f'{prefix}give {stmt["subj"]} {tilde}{stmt["attr"]};')
        elif t == 'go':
            w(f'{prefix}PlayerTo({_to_id(stmt["arg"])});')
        elif t == 'box':
            raw_lines = stmt['arg'].split('\\n')
            encoded = [_i6box_line(l) for l in raw_lines]
            if len(encoded) == 1:
                w(f'{prefix}box "{encoded[0]}";')
            else:
                w(f'{prefix}box "{encoded[0]}"')
                for line in encoded[1:-1]:
                    w(f'{prefix}    "{line}"')
                w(f'{prefix}    "{encoded[-1]}";')
        elif t == 'if':
            inner = prefix + '    '
            has_or_hasnt = 'hasnt' if stmt['neg'] else 'has'
            cond_expr = f'self {has_or_hasnt} {stmt["attr"]}'
            w(f'{prefix}if ({cond_expr}) {{')
            _emit_stmts(w, stmt['then'], inner, known_ids)
            w(f'{inner}rtrue;')
            if stmt.get('else'):
                w(f'{prefix}}} else {{')
                _emit_stmts(w, stmt['else'], inner, known_ids)
                w(f'{inner}rtrue;')
            w(f'{prefix}}}')


_ON_TURN_RE = re.compile(r'^on turn (\d+)$')


def _emit_handlers(w, handlers: dict, verb_action_map: dict, known_ids: set) -> None:
    if not handlers:
        return

    turn_h   = {k: v for k, v in handlers.items() if _ON_TURN_RE.match(k)}
    each_h   = {k: v for k, v in handlers.items() if k == 'each turn'}
    before_h = {k: v for k, v in handlers.items()
                if not k.startswith('after ') and k not in turn_h and k not in each_h}
    after_h  = {k: v for k, v in handlers.items() if k.startswith('after ')}

    # each_turn property: fires every turn when location matches
    if turn_h or each_h:
        w(f'{_PROP}each_turn [;')
        for key, stmts in each_h.items():
            _emit_stmts(w, stmts, _ACTION, known_ids)
        for key, stmts in turn_h.items():
            n = _ON_TURN_RE.match(key).group(1)
            w(f'{_ACTION}if (turns == {n}) {{')
            _emit_stmts(w, stmts, _STMT0, known_ids)
            w(f'{_ACTION}}}')
        w(f'{_PROP}],')

    for prop, hmap in (('before', before_h), ('after', after_h)):
        if not hmap:
            continue
        w(f'{_PROP}{prop} [;')
        for key, stmts in hmap.items():
            action, second_filter = _parse_handler_key(key, verb_action_map)
            w(f'{_ACTION}{action}:')
            if second_filter:
                w(f'{_STMT0}if (second ~= {second_filter}) rfalse;')
            _emit_stmts(w, stmts, _STMT0, known_ids)
            if not (stmts and stmts[-1]['type'] == 'if' and stmts[-1].get('else')):
                w(f'{_STMT0}rtrue;')
        w(f'{_PROP}],')


# ---------------------------------------------------------------------------
# Inform 6 object emitters
# ---------------------------------------------------------------------------

def _emit_object(w, obj: dict, parent: str, verb_action_map: dict, known_ids: set):
    oid   = obj['id']
    attrs = _obj_attributes(obj)
    kws   = ' '.join(f"'{k}'" for k in obj['keywords']) if obj['keywords'] else ''
    loc   = obj['properties'].get('inside', parent)

    w(f'Object {oid} "{_i6str(obj["name"])}" {loc}')
    if kws:
        w(f'    with name {kws},')
        w(f'         description "{_i6str(obj["desc"])}",')
    else:
        w(f'    with description "{_i6str(obj["desc"])}",')
    if 'key' in obj['properties']:
        w(f'         with_key {obj["properties"]["key"]},')
    _emit_handlers(w, obj.get('handlers', {}), verb_action_map, known_ids)
    w(f'    has {attrs};' if attrs else '    has ;')
    w('')


def _emit_door(w, obj: dict, parent_rid: str, door_dir: str, dest_rid: str,
               verb_action_map: dict, known_ids: set):
    oid  = obj['id']
    kws  = ' '.join(f"'{k}'" for k in obj['keywords']) if obj['keywords'] else ''

    attr_list = ['door']
    if 'openable' in obj['behaviours']:
        attr_list.append('openable')
    if 'lockable' in obj['behaviours']:
        attr_list.append('lockable')
    for key, val in obj['properties'].items():
        if val == 'true':
            attr_list.append(key)
    attrs = ' '.join(attr_list)

    w(f'Object {oid} "{_i6str(obj["name"])}" {parent_rid}')
    if kws:
        w(f'    with name {kws},')
        w(f'         description "{_i6str(obj["desc"])}",')
    else:
        w(f'    with description "{_i6str(obj["desc"])}",')
    w(f'         door_dir {_DIR_MAP[door_dir]},')
    w(f'         door_to [; return {dest_rid}; ],')
    if 'key' in obj['properties']:
        w(f'         with_key {obj["properties"]["key"]},')
    _emit_handlers(w, obj.get('handlers', {}), verb_action_map, known_ids)
    w(f'    has {attrs};')
    w('')


# ---------------------------------------------------------------------------
# Inform 6 emitter
# ---------------------------------------------------------------------------

# I6 standard library attributes — no Attribute declaration needed for these.
_I6_BUILTIN_ATTRS = {
    'open', 'locked', 'openable', 'lockable', 'container', 'supporter',
    'light', 'animate', 'female', 'proper', 'scenery', 'static', 'absent',
    'concealed', 'worn', 'clothing', 'edible', 'talkable', 'switchable', 'on',
    'door', 'enterable', 'visited', 'general', 'transparent', 'described',
    'reactive', 'untouchable', 'moved',
}


def _collect_user_attributes(ast: dict) -> set:
    """Return all attribute names used in give/if/properties that need Attribute declarations."""
    attrs = set()

    def _scan_stmts(stmts):
        for s in stmts:
            if s['type'] == 'give':
                attrs.add(s['attr'])
            elif s['type'] == 'if':
                attrs.add(s['attr'])
                _scan_stmts(s['then'])
                _scan_stmts(s.get('else') or [])

    for room in ast.get('rooms', []):
        for stmts in room.get('handlers', {}).values():
            _scan_stmts(stmts)
        for obj in room.get('objects', []):
            for key, val in obj.get('properties', {}).items():
                if val == 'true':
                    attrs.add(key)
            for stmts in obj.get('handlers', {}).values():
                _scan_stmts(stmts)

    return attrs - _I6_BUILTIN_ATTRS


def _uses_plural_s(ast: dict) -> bool:
    """Return True if any say string in the AST uses {s ...} interpolation."""
    def _scan_stmts(stmts):
        for s in stmts:
            if s['type'] == 'say' and re.search(r'\{s\s+', s['arg']):
                return True
            if s['type'] == 'if':
                if _scan_stmts(s['then']): return True
                if _scan_stmts(s.get('else') or []): return True
        return False
    for room in ast.get('rooms', []):
        for stmts in room.get('handlers', {}).values():
            if _scan_stmts(stmts): return True
        for obj in room.get('objects', []):
            for stmts in obj.get('handlers', {}).values():
                if _scan_stmts(stmts): return True
    return False


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
    if _uses_plural_s(ast):
        w('[ Grue_s n; if (n ~= 1) print "s"; ];')
        w('')
    for attr in sorted(_collect_user_attributes(ast)):
        w(f'Attribute {attr};')
    if _collect_user_attributes(ast):
        w('')

    # Build verb_action_map: base_word → action_name
    # verb_action_map: plain key → plain action, key+':with' → with-action
    verb_action_map = {}
    for verb in ast.get('verbs', []):
        action     = _verb_action_name(verb)
        base_word  = verb['words'][0].lower()
        if action.endswith('With'):
            verb_action_map[base_word + ':with'] = action
        else:
            for word in verb['words']:
                verb_action_map[word.lower()] = action

    # Emit custom verb stubs and Verb declarations
    declared_verb_words: set = set()
    for verb in ast.get('verbs', []):
        action   = _verb_action_name(verb)
        sub_name = action + 'Sub'
        default  = verb.get('default', '')
        w(f'[ {sub_name};')
        if default:
            w(f'    "{_i6str(default)}";')
        w('];')
        w('')
        synonyms   = verb.get('synonyms', verb['words'][:1])
        base_word  = synonyms[0].lower()
        if base_word in declared_verb_words:
            w(f"Extend '{base_word}'")
        else:
            verb_words = ' '.join(f"'{s}'" for s in synonyms)
            w(f'Verb {verb_words}')
            declared_verb_words.update(s.lower() for s in synonyms)
        for grammar_line in verb['grammar']:
            w(f'    {grammar_line} -> {action};')
        w('')

    # Normalize any room reference to the canonical Inform 6 id.
    room_by_norm = {}
    for r in rooms:
        room_by_norm[_to_id(r['name'])]        = r['id']
        room_by_norm[r['id']]                  = r['id']
        room_by_norm[r['id'].replace('_', '')] = r['id']

    def _resolve_room(ref: str) -> str:
        return room_by_norm.get(ref) or room_by_norm.get(_to_id(ref)) or _to_id(ref)

    # door_id → (obj, parent_room_id, door_direction, dest_room_id)
    door_info = {}
    for room in rooms:
        for obj in room['objects']:
            if obj['kind'] == 'door':
                for prop_key in obj['properties']:
                    if prop_key in _DIR_MAP:
                        dest_id = _resolve_room(obj['properties'][prop_key])
                        door_info[obj['id']] = (obj, room['id'], prop_key, dest_id)
                        break

    # Directions already covered in each room (explicit exits + in-room door exits)
    room_covered_dirs = {}
    for room in rooms:
        covered = set(room['exits'].keys())
        for obj in room['objects']:
            if obj['kind'] == 'door' and obj['id'] in door_info:
                covered.add(door_info[obj['id']][2])
        room_covered_dirs[room['id']] = covered

    # Auto-inject plain reverse exits for in-room doors
    reverse_exits = {}  # dest_room_id → {opp_dir: parent_room_id}
    for did, (obj, parent_rid, door_dir, dest_rid) in door_info.items():
        opp = _OPPOSITE_DIR.get(door_dir)
        if opp and opp not in room_covered_dirs.get(dest_rid, set()):
            reverse_exits.setdefault(dest_rid, {})[opp] = parent_rid

    # IDs of all named game objects — used to resolve {interpolations} in say
    known_ids: set = set()
    for r in rooms:
        known_ids.add(r['id'])
        for obj in r['objects']:
            known_ids.add(obj['id'])

    for room in rooms:
        rid = room['id']
        w(f'Object {rid} "{_i6str(room["name"])}"')
        w( '    with description')
        w(f'        "{_i6str(room["desc"])}",')
        for direction, dest in room['exits'].items():
            i6dir = _DIR_MAP.get(direction, direction + '_to')
            w(f'         {i6dir} {_resolve_room(dest)},')
        for obj in room['objects']:
            if obj['kind'] == 'door' and obj['id'] in door_info:
                _, _, door_dir, _ = door_info[obj['id']]
                i6dir = _DIR_MAP[door_dir]
                w(f'         {i6dir} {obj["id"]},')
        for direction, dest_rid in reverse_exits.get(rid, {}).items():
            i6dir = _DIR_MAP.get(direction, direction + '_to')
            w(f'         {i6dir} {dest_rid},')
        _emit_handlers(w, room.get('handlers', {}), verb_action_map, known_ids)
        w( '    has light;')
        w('')

        for obj in room['objects']:
            if obj['kind'] == 'door' and obj['id'] in door_info:
                _, _, door_dir, dest_rid = door_info[obj['id']]
                _emit_door(w, obj, rid, door_dir, dest_rid, verb_action_map, known_ids)
            elif obj['kind'] != 'door':
                _emit_object(w, obj, rid, verb_action_map, known_ids)

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
