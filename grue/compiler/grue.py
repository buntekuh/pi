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
    def __init__(self, msg, line=None, code=None):
        super().__init__(msg)
        self.line = line
        self.code = code


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


def _append_stmt(stmts: list, stripped: str, lineno: int) -> None:
    if stripped.startswith('say '):
        stmts.append({'type': 'say', 'arg': _extract_string(stripped[4:]), 'line': lineno})
    elif stripped.startswith('go '):
        stmts.append({'type': 'go', 'arg': stripped[3:].strip().strip('"'), 'line': lineno})
    elif stripped.startswith('box '):
        stmts.append({'type': 'box', 'arg': _extract_string(stripped[4:]), 'line': lineno})
    else:
        word = stripped.rstrip('.')
        m  = re.match(r'the\s+(\w+)\s+is\s+(not\s+)?(\w+)$', word)
        mn = re.match(r'(\w+)\s+(\w+)\s+=\s+(\d+)$', word)
        mk = re.match(r'(\w+)\s+(\w+)\s+(?:=|is)\s+([a-zA-Z_]\w*)$', word)
        if m:
            subj     = m.group(1)
            neg_kw   = bool(m.group(2))
            raw_attr = m.group(3)
            attr     = _NEGATION.get(raw_attr, raw_attr)
            neg      = neg_kw or raw_attr in _NEGATION
            stmts.append({'type': 'give', 'subj': subj, 'attr': attr, 'neg': neg, 'line': lineno})
        elif mn:
            stmts.append({'type': 'prop_assign',
                          'obj':  mn.group(1).lower(),
                          'prop': mn.group(2).lower(),
                          'num':  int(mn.group(3)),
                          'line': lineno})
        elif mk:
            stmts.append({'type': 'kind_assign',
                          'obj':  mk.group(1).lower(),
                          'kind': mk.group(2).lower(),
                          'val':  mk.group(3).lower(),
                          'line': lineno})
        elif re.match(r'\w+\s*=\s*.+', word):
            mg = re.match(r'(\w+)\s*=\s*(.+)$', word)
            stmts.append({'type': 'var_assign',
                          'var':  mg.group(1),
                          'expr': mg.group(2).strip(),
                          'line': lineno})
        elif re.match(r'not\s+\w+$', word):
            raw_attr = word.split(None, 1)[1]
            attr     = _NEGATION.get(raw_attr, raw_attr)
            stmts.append({'type': 'give', 'subj': 'self', 'attr': attr, 'neg': True, 'line': lineno})
        elif re.match(r'\w+$', word):
            raw_attr = word
            attr     = _NEGATION.get(raw_attr, raw_attr)
            neg      = raw_attr in _NEGATION
            stmts.append({'type': 'give', 'subj': 'self', 'attr': attr, 'neg': neg, 'line': lineno})


_OBJ_TYPES    = {'object', 'scenery', 'man', 'woman', 'robot', 'door'}
_ROOM_KEYWORDS = {'is', 'instead', 'on', 'after', 'each'}


def parse(source: str) -> dict:
    source = _preprocess(source)
    ast = {'uses': [], 'kinds': [], 'values': [], 'vars': [], 'rooms': [], 'verbs': [], 'tests': []}

    current_room    = None;  room_col    = -1
    current_object  = None;  obj_col     = -1
    current_handler = None;  handler_col = -1
    current_if      = None;  if_col      = -1;  if_branch = 'then'
    current_test    = None;  test_col    = -1
    current_verb    = None;  verb_col    = -1

    kind_val_map = {}   # value_name → kind_name that claimed it

    for lineno, raw in enumerate(source.splitlines(), 1):
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
            _append_stmt(branch, stripped, lineno)

        elif current_handler is not None:
            ms_has  = re.match(r'if\s+(\w+)\s+has\s+(not\s+)?(\w+)\s*:', stripped)
            ms_isn  = re.match(r'if\s+(\w+)\s+is\s+not\s+(\w+)\s*:', stripped)
            mk      = re.match(r'if\s+(\w+)\s+(==?|is|<=?|>=?)\s+(\w+)\s*:', stripped)
            m       = re.match(r'if\s+(not\s+)?(\w+)\s*:', stripped)
            if ms_has:
                current_if = {'type': 'if',
                               'subj': ms_has.group(1), 'contains': ms_has.group(3),
                               'neg': bool(ms_has.group(2)),
                               'then': [], 'else': None, 'line': lineno}
                if_col = col; if_branch = 'then'
            elif ms_isn:
                current_if = {'type': 'if',
                               'kind': ms_isn.group(1).lower(), 'val': ms_isn.group(2).lower(),
                               'neg': True, 'op': 'is',
                               'then': [], 'else': None, 'line': lineno}
                if_col = col; if_branch = 'then'
            elif mk:
                op      = mk.group(2)
                val_str = mk.group(3)
                if op in ('is', '='):
                    op = '=='
                if val_str.isdigit():
                    current_if = {'type': 'if', 'prop': mk.group(1).lower(),
                                   'op': op, 'num': int(val_str),
                                   'then': [], 'else': None, 'line': lineno}
                else:
                    current_if = {'type': 'if', 'kind': mk.group(1).lower(),
                                   'neg': False, 'op': op, 'val': val_str.lower(),
                                   'then': [], 'else': None, 'line': lineno}
                if_col = col; if_branch = 'then'
            elif m:
                neg_kw   = bool(m.group(1))
                raw_attr = m.group(2)
                attr     = _NEGATION.get(raw_attr, raw_attr)
                neg      = neg_kw or raw_attr in _NEGATION
                current_if = {'type': 'if', 'attr': attr, 'neg': neg,
                               'then': [], 'else': None, 'line': lineno}
                if_col = col; if_branch = 'then'
            else:
                _append_stmt(current_handler, stripped, lineno)

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
                    d = m.group(1).lower()
                    current_room['exits'][d]      = m.group(2)
                    current_room['exit_lines'][d] = lineno

            elif re.match(r'(north|south|east|west|up|down|ne|nw|se|sw):?\s+\w+\s*$', stripped, re.I):
                m = re.match(r'(\w+):?\s+(\w+)', stripped)
                if m:
                    d = m.group(1).lower()
                    current_room['exits'][d]      = m.group(2)
                    current_room['exit_lines'][d] = lineno

            elif re.match(r'(object|scenery|man|woman|robot|door)\s+', stripped):
                kind = stripped.split()[0]
                keywords, display, obj_id, inline_desc = _parse_keywords(stripped[len(kind):].strip())
                current_object = {
                    'id': obj_id, 'keywords': keywords, 'name': display,
                    'desc': inline_desc, 'behaviours': [], 'properties': {},
                    'kind': kind, 'handlers': {}, 'line': lineno,
                }
                obj_col = col
                current_room['objects'].append(current_object)

            elif re.match(r'(instead of|on|after|each)\s+', stripped):
                key = stripped.rstrip(':')
                current_handler = []
                handler_col = col
                current_room['handlers'][key] = current_handler

            else:
                # Unknown line in room context — catch likely misspelled object types.
                first_word = stripped.split()[0] if stripped.split() else ''
                if (first_word and
                        first_word.lower() not in _OBJ_TYPES and
                        first_word.lower() not in _ROOM_KEYWORDS and
                        first_word.lower() not in _DIR_MAP and
                        '"' in stripped):
                    raise GrueError(
                        f"unknown object type '{first_word}'"
                        f" — use object, scenery, man, woman, robot, or door",
                        lineno, 'E020')

        elif current_verb is not None:
            if stripped.startswith('*') or stripped.startswith('takes '):
                current_verb['grammar'].append(_translate_grammar(stripped.rstrip('.')))
            elif stripped.startswith('"'):
                current_verb['default'] = _extract_string(stripped)

        else:
            # top level
            if stripped.startswith('uses '):
                ast['uses'].append(stripped[5:].rstrip('.').strip())

            elif stripped.startswith('kind '):
                rest = stripped[5:].rstrip('.')
                if ':' in rest:
                    name_part, vals_part = rest.split(':', 1)
                    kind_name = name_part.strip()
                    k_id      = '_'.join(k.lower() for k in kind_name.split())
                    values    = [v.strip().lower() for v in vals_part.split(',') if v.strip()]
                    if len(values) < 2:
                        raise GrueError(
                            f"kind '{kind_name}': at least two values required",
                            lineno, 'E002')
                    if 'true' in values or 'false' in values:
                        raise GrueError(
                            f"kind '{kind_name}': values 'true' and 'false' are reserved"
                            f" — use 'is X.' for boolean attributes",
                            lineno, 'E030')
                    if k_id in {k['id'] for k in ast['kinds']}:
                        raise GrueError(
                            f"kind '{kind_name}' already declared",
                            lineno, 'E032')
                    if k_id in {v['id'] for v in ast['values']}:
                        raise GrueError(
                            f"'{kind_name}' already declared as a value",
                            lineno, 'E034')
                    for val in values:
                        if val in kind_val_map:
                            raise GrueError(
                                f"kind value '{val}' already claimed by kind '{kind_val_map[val]}'",
                                lineno, 'E031')
                        kind_val_map[val] = kind_name
                    ast['kinds'].append(
                        {'name': kind_name, 'id': k_id, 'values': values, 'line': lineno})

            elif stripped.startswith('value '):
                val_name = stripped[6:].rstrip('.')
                v_id = '_'.join(k.lower() for k in val_name.split())
                if v_id in {v['id'] for v in ast['values']}:
                    raise GrueError(
                        f"value '{val_name}' already declared",
                        lineno, 'E033')
                if v_id in {k['id'] for k in ast['kinds']}:
                    raise GrueError(
                        f"'{val_name}' already declared as a kind",
                        lineno, 'E034')
                ast['values'].append({'name': val_name, 'id': v_id, 'line': lineno})

            elif stripped.startswith('var '):
                var_name = stripped[4:].rstrip('.')
                v_id = _to_id(var_name)
                if v_id in {v['id'] for v in ast['vars']}:
                    raise GrueError(
                        f"var '{var_name}' already declared",
                        lineno, 'E060')
                if v_id in {k['id'] for k in ast['kinds']}:
                    raise GrueError(
                        f"'{var_name}' already declared as a kind",
                        lineno, 'E061')
                if v_id in {v['id'] for v in ast['values']}:
                    raise GrueError(
                        f"'{var_name}' already declared as a value",
                        lineno, 'E061')
                ast['vars'].append({'name': var_name, 'id': v_id, 'line': lineno})

            elif stripped.startswith('verb '):
                words_part = stripped[5:].rstrip('.')
                words = [w.strip().strip(',') for w in words_part.split() if w.strip().strip(',')]
                synonyms = [w.strip() for w in words_part.split(',') if w.strip()]
                synonyms = [synonyms[0].split()[0]] + [s.strip() for s in synonyms[1:]] if synonyms else words[:1]
                current_verb = {'words': words, 'synonyms': synonyms,
                                'grammar': [], 'default': '', 'line': lineno}
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
                    'exits': {}, 'exit_lines': {}, 'objects': [], 'handlers': {},
                    'line': lineno,
                }
                room_col = col
                ast['rooms'].append(current_room)

            elif stripped.startswith('test '):
                m = re.match(r'test\s+"([^"]*)"', stripped)
                if m:
                    current_test = {'name': m.group(1), 'commands': []}
                    test_col = col
                    ast['tests'].append(current_test)

    # Flush a trailing if block never closed by an outdented line.
    if current_if is not None and current_handler is not None:
        current_handler.append(current_if)

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

# Friendly negation aliases: word → canonical_attr (negated).
_NEGATION = {
    'close':    'open',
    'closed':   'open',
    'unlocked': 'locked',
    'off':      'on',
}


_GRAMMAR_QUALIFIERS = {'held', 'creature', 'visible'}


def _parse_noun_slot(tokens: list) -> tuple:
    """Consume [qualifier] (noun|multi) from tokens; return (i6_token, remaining)."""
    if not tokens:
        return 'noun', []
    if tokens[0] in _GRAMMAR_QUALIFIERS:
        qual, rest = tokens[0], tokens[1:]
        target = rest[0] if rest else 'noun'
        rest   = rest[1:] if rest else []
        if qual == 'visible':
            return target, rest
        if target == 'multi':
            return {'held': 'multiheld'}.get(qual, target), rest
        return qual, rest        # held noun → held, creature noun → creature
    return tokens[0], tokens[1:]


def _translate_grammar(line: str) -> str:
    """Translate 'takes ...' to I6 '* ...' form; pass through raw '* ...' unchanged."""
    if line.startswith('*') or not line.startswith('takes '):
        return line
    tokens = line[6:].strip().split()
    first, tokens = _parse_noun_slot(tokens)
    if not tokens:
        return f'* {first}'
    prep   = tokens[0]
    second, _ = _parse_noun_slot(tokens[1:])
    return f"* {first} '{prep}' {second}"


def _to_id(name: str) -> str:
    s = name.lower().replace("'", '')
    s = re.sub(r'[^a-z0-9]+', '_', s).strip('_')
    return ('o_' + s) if s and s[0].isdigit() else (s or 'unnamed')


def _i6str(s: str) -> str:
    s = s.replace('\\n', '^').replace('\\t', '@@9')
    s = re.sub(r'\s+', ' ', s).strip()
    return s.replace('"', '~')


def _i6box_line(s: str) -> str:
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

_PROP   = '         '    # 9 spaces
_ACTION = '             '  # 13 spaces
_STMT0  = '                 '  # 17 spaces

_INTERP_RE = re.compile(r'\{([^}]+)\}')

_I6_OBJ_VARS = {'noun', 'second', 'self', 'actor', 'location'}


def _emit_say(w, text: str, prefix: str, known_ids: set) -> None:
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


def _emit_stmts(w, stmts: list, prefix: str, known_ids: set, kinds_ctx) -> None:
    kinds_by_id, values_set, vars_set = kinds_ctx
    for stmt in stmts:
        t    = stmt['type']
        line = stmt.get('line')
        if t == 'say':
            _emit_say(w, stmt['arg'], prefix, known_ids)
        elif t == 'give':
            tilde = '~' if stmt['neg'] else ''
            w(f'{prefix}give {stmt["subj"]} {tilde}{stmt["attr"]};')
        elif t == 'var_assign':
            if stmt['var'] not in vars_set:
                raise GrueError(
                    f"unknown variable '{stmt['var']}' — declare with 'var {stmt['var']}'",
                    line, 'E063')
            w(f'{prefix}{stmt["var"]} = {stmt["expr"]};')
        elif t == 'prop_assign':
            if stmt['prop'] not in values_set:
                raise GrueError(
                    f"unknown value property '{stmt['prop']}'"
                    f" — declare with 'value {stmt['prop']}'",
                    line, 'E051')
            w(f'{prefix}{stmt["obj"]}.{stmt["prop"]} = {stmt["num"]};')
        elif t == 'kind_assign':
            kind_id = _to_id(stmt['kind'])
            kd = kinds_by_id.get(kind_id)
            if kd is None:
                if stmt['kind'] in values_set:
                    raise GrueError(
                        f"'{stmt['kind']}' is a numeric value property"
                        f" — assign with a number: {stmt['obj']} {stmt['kind']} = 5.",
                        line, 'E041')
                raise GrueError(f"unknown kind '{stmt['kind']}'", line, 'E036')
            val = stmt['val']
            if val not in kd['values']:
                raise GrueError(
                    f"unknown value '{val}' for kind '{stmt['kind']}'", line, 'E037')
            obj_ref = stmt['obj']
            if len(kd['values']) == 2:
                attr_name = kd['values'][1]
                tilde = '' if val == attr_name else '~'
                w(f'{prefix}give {obj_ref} {tilde}{attr_name};')
            else:
                w(f'{prefix}{obj_ref}.{kind_id} = {val.upper()};')
        elif t == 'go':
            w(f'{prefix}PlayerTo({_to_id(stmt["arg"])});')
        elif t == 'box':
            raw_lines = stmt['arg'].split('\\n')
            encoded = [_i6box_line(l) for l in raw_lines]
            if len(encoded) == 1:
                w(f'{prefix}box "{encoded[0]}";')
            else:
                w(f'{prefix}box "{encoded[0]}"')
                for ln in encoded[1:-1]:
                    w(f'{prefix}    "{ln}"')
                w(f'{prefix}    "{encoded[-1]}";')
        elif t == 'if':
            inner = prefix + '    '
            if 'contains' in stmt:
                obj_ref   = stmt['contains']
                container = stmt['subj']
                cond_expr = (f'~~({obj_ref} in {container})' if stmt['neg']
                             else f'{obj_ref} in {container}')
            elif 'prop' in stmt:
                prop = stmt['prop']
                if prop in vars_set:
                    cond_expr = f'{prop} {stmt["op"]} {stmt["num"]}'
                elif prop not in values_set:
                    raise GrueError(
                        f"unknown value property '{prop}'"
                        f" — declare with 'value {prop}' or 'var {prop}'",
                        line, 'E052')
                else:
                    cond_expr = f'self.{prop} {stmt["op"]} {stmt["num"]}'
            elif 'kind' in stmt:
                kind_id = _to_id(stmt['kind'])
                kd      = kinds_by_id.get(kind_id)
                neg     = stmt.get('neg', False)
                if kd is not None:
                    # Self's kind property check: if wetness is wet:
                    val = stmt['val']
                    if val not in kd['values']:
                        raise GrueError(
                            f"unknown value '{val}' for kind '{stmt['kind']}'", line, 'E039')
                    op = stmt['op']
                    if len(kd['values']) == 2:
                        attr_name = kd['values'][1]
                        if op in ('==', 'is'):
                            effective_has = (val == attr_name) ^ neg
                            cond_expr = (f'self has {attr_name}' if effective_has
                                         else f'self hasnt {attr_name}')
                        else:
                            raise GrueError(
                                f"operator '{op}' not valid for two-value kind '{stmt['kind']}'",
                                line, 'E040')
                    else:
                        cond_expr = f'self.{kind_id} {stmt["op"]} {stmt["val"].upper()}'
                else:
                    # Subject-qualified: if murderer is wet: / if robot is low:
                    if stmt['kind'] in values_set:
                        raise GrueError(
                            f"'{stmt['kind']}' is a numeric value property"
                            f" — use a numeric comparison: if {stmt['kind']} > 0:",
                            line, 'E042')
                    subj = stmt['kind']
                    word = stmt['val']
                    val_to_kind = {v: kd2 for kd2 in kinds_by_id.values()
                                   for v in kd2['values']}
                    if word in val_to_kind:
                        kd2 = val_to_kind[word]
                        if len(kd2['values']) == 2:
                            attr_name     = kd2['values'][1]
                            effective_has = (word == attr_name) ^ neg
                            cond_expr = (f'{subj} has {attr_name}' if effective_has
                                         else f'{subj} hasnt {attr_name}')
                        else:
                            op2 = '~=' if neg else '=='
                            cond_expr = f'{subj}.{kd2["id"]} {op2} {word.upper()}'
                    else:
                        attr  = _NEGATION.get(word, word)
                        is_neg = neg ^ (word in _NEGATION)
                        cond_expr = f'{subj} {"hasnt" if is_neg else "has"} {attr}'
            else:
                has_or_hasnt = 'hasnt' if stmt['neg'] else 'has'
                cond_expr = f'self {has_or_hasnt} {stmt["attr"]}'
            w(f'{prefix}if ({cond_expr}) {{')
            _emit_stmts(w, stmt['then'], inner, known_ids, kinds_ctx)
            w(f'{inner}rtrue;')
            if stmt.get('else'):
                w(f'{prefix}}} else {{')
                _emit_stmts(w, stmt['else'], inner, known_ids, kinds_ctx)
                w(f'{inner}rtrue;')
            w(f'{prefix}}}')


_ON_TURN_RE = re.compile(r'^on turn (\d+)$')


def _emit_handlers(w, handlers: dict, verb_action_map: dict, known_ids: set,
                   kinds_ctx) -> None:
    if not handlers:
        return

    turn_h   = {k: v for k, v in handlers.items() if _ON_TURN_RE.match(k)}
    each_h   = {k: v for k, v in handlers.items() if k == 'each turn'}
    before_h = {k: v for k, v in handlers.items()
                if not k.startswith('after ') and k not in turn_h and k not in each_h}
    after_h  = {k: v for k, v in handlers.items() if k.startswith('after ')}

    if turn_h or each_h:
        w(f'{_PROP}each_turn [;')
        for key, stmts in each_h.items():
            _emit_stmts(w, stmts, _ACTION, known_ids, kinds_ctx)
        for key, stmts in turn_h.items():
            n = _ON_TURN_RE.match(key).group(1)
            w(f'{_ACTION}if (turns == {n}) {{')
            _emit_stmts(w, stmts, _STMT0, known_ids, kinds_ctx)
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
            _emit_stmts(w, stmts, _STMT0, known_ids, kinds_ctx)
            if not (stmts and stmts[-1]['type'] == 'if' and stmts[-1].get('else')):
                w(f'{_STMT0}rtrue;')
        w(f'{_PROP}],')


# ---------------------------------------------------------------------------
# Inform 6 object emitters
# ---------------------------------------------------------------------------

def _emit_object(w, obj: dict, parent: str, verb_action_map: dict, known_ids: set,
                 kinds_ctx):
    kinds_by_id, values_set, vars_set = kinds_ctx
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
    for prop_key, prop_val in obj['properties'].items():
        if prop_key in ('key', 'inside'):
            continue
        prop_kind_id = _to_id(prop_key)
        if prop_kind_id in kinds_by_id:
            kd = kinds_by_id[prop_kind_id]
            if len(kd['values']) == 2:
                if prop_val == 'true':
                    continue  # set via 'is X.' — handled by the has clause
                raise GrueError(
                    f"kind '{prop_key}' has two values"
                    f" — set with 'is {kd['values'][1]}.' or leave unset for '{kd['values'][0]}'",
                    obj.get('line'), 'E035')
            val = prop_val.lower()
            if val not in kd['values']:
                raise GrueError(
                    f"unknown value '{prop_val}' for kind '{prop_key}' on '{obj['id']}'",
                    obj.get('line'), 'E037')
            w(f'         {prop_kind_id} {val.upper()},')
        elif prop_val.isdigit():
            if prop_key not in values_set:
                raise GrueError(
                    f"undeclared numeric property '{prop_key}' on '{obj['id']}'"
                    f" — declare with 'value {prop_key}'",
                    obj.get('line'), 'E050')
            w(f'         {prop_key} {prop_val},')
        elif prop_val in ('true', 'false'):
            # 'is X.' where X is a kind value (not the kind name itself)
            for kd in kinds_by_id.values():
                if prop_key not in kd['values']:
                    continue
                idx = kd['values'].index(prop_key)
                if len(kd['values']) == 2 and idx == 1:
                    break  # correct: 'is X.' sets the attribute of a two-value kind
                if len(kd['values']) == 2:
                    raise GrueError(
                        f"'{prop_key}' is the default state of kind '{kd['name']}'"
                        f" — leave unset, or use 'is {kd['values'][1]}.' to set it",
                        obj.get('line'), 'E035')
                raise GrueError(
                    f"'{prop_key}' is a value of kind '{kd['name']}'"
                    f" — use '{kd['id']}: {prop_key}.' to set an initial value",
                    obj.get('line'), 'E035')
    _emit_handlers(w, obj.get('handlers', {}), verb_action_map, known_ids, kinds_ctx)
    w(f'    has {attrs};' if attrs else '    has ;')
    w('')


def _emit_door(w, obj: dict, parent_rid: str, door_dir: str, dest_rid: str,
               verb_action_map: dict, known_ids: set, kinds_ctx):
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
    _emit_handlers(w, obj.get('handlers', {}), verb_action_map, known_ids, kinds_ctx)
    w(f'    has {attrs};')
    w('')


# ---------------------------------------------------------------------------
# Inform 6 emitter
# ---------------------------------------------------------------------------

_I6_BUILTIN_ATTRS = {
    'open', 'locked', 'openable', 'lockable', 'container', 'supporter',
    'light', 'animate', 'female', 'proper', 'scenery', 'static', 'absent',
    'concealed', 'worn', 'clothing', 'edible', 'talkable', 'switchable', 'on',
    'door', 'enterable', 'visited', 'general', 'transparent', 'described',
    'reactive', 'untouchable', 'moved',
}


def _collect_user_attributes(ast: dict) -> set:
    attrs = set()

    def _scan_stmts(stmts):
        for s in stmts:
            if s['type'] == 'give':
                attrs.add(s['attr'])
            elif s['type'] == 'if':
                if 'attr' in s:
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
        raise GrueError('no rooms defined', code='E001')

    # Duplicate room names
    seen_room_ids = set()
    for r in rooms:
        if r['id'] in seen_room_ids:
            raise GrueError(
                f"duplicate room name '{r['name']}'", r.get('line'), 'E011')
        seen_room_ids.add(r['id'])

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

    # Build kind, value, and var registries
    kinds_by_id = {kd['id']: kd for kd in ast.get('kinds', [])}
    values_set  = {vd['id'] for vd in ast.get('values', [])}
    vars_set    = {vd['id'] for vd in ast.get('vars',   [])}
    kinds_ctx   = (kinds_by_id, values_set, vars_set)

    kind_declared_attrs = set()
    for kd in ast.get('kinds', []):
        if len(kd['values']) == 2:
            kind_declared_attrs.add(kd['values'][1])

    for kd in ast.get('kinds', []):
        if len(kd['values']) == 2:
            attr_name = kd['values'][1]
            if attr_name not in _I6_BUILTIN_ATTRS:
                w(f'Attribute {attr_name};')
        else:
            for i, val in enumerate(kd['values']):
                w(f'Constant {val.upper()} {i};')
            w(f'Property {kd["id"]} {kd["values"][0].upper()};')
    for vd in ast.get('values', []):
        w(f'Property {vd["id"]} 0;')
    for vd in ast.get('vars', []):
        w(f'Global {vd["id"]} 0;')
    if ast.get('kinds') or ast.get('values') or ast.get('vars'):
        w('')

    user_attrs = _collect_user_attributes(ast) - kind_declared_attrs
    for attr in sorted(user_attrs):
        w(f'Attribute {attr};')
    if user_attrs:
        w('')

    verb_action_map = {}
    for verb in ast.get('verbs', []):
        action    = _verb_action_name(verb)
        base_word = verb['words'][0].lower()
        if action.endswith('With'):
            verb_action_map[base_word + ':with'] = action
        else:
            for word in verb['words']:
                verb_action_map[word.lower()] = action

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
        synonyms  = verb.get('synonyms', verb['words'][:1])
        base_word = synonyms[0].lower()
        if base_word in declared_verb_words:
            w(f"Extend '{base_word}'")
        else:
            verb_words = ' '.join(f"'{s}'" for s in synonyms)
            w(f'Verb {verb_words}')
            declared_verb_words.update(s.lower() for s in synonyms)
        for grammar_line in verb['grammar']:
            w(f'    {grammar_line} -> {action};')
        w('')

    # Normalize room references to canonical I6 ids
    room_by_norm = {}
    for r in rooms:
        room_by_norm[_to_id(r['name'])]        = r['id']
        room_by_norm[r['id']]                  = r['id']
        room_by_norm[r['id'].replace('_', '')] = r['id']

    def _resolve_room(ref: str, line=None) -> str:
        result = room_by_norm.get(ref) or room_by_norm.get(_to_id(ref))
        if result is None:
            raise GrueError(
                f"exit leads to unknown room '{ref}'", line, 'E010')
        return result

    # Validate and collect door info
    door_info = {}
    for room in rooms:
        for obj in room['objects']:
            if obj['kind'] == 'door':
                found_dir = False
                for prop_key in obj['properties']:
                    if prop_key in _DIR_MAP:
                        dest_ref = obj['properties'][prop_key]
                        dest_id  = _resolve_room(dest_ref, obj.get('line'))
                        door_info[obj['id']] = (obj, room['id'], prop_key, dest_id)
                        found_dir = True
                        break
                if not found_dir:
                    raise GrueError(
                        f"door '{obj['id']}' has no direction property",
                        obj.get('line'), 'E021')

    room_covered_dirs = {}
    for room in rooms:
        covered = set(room['exits'].keys())
        for obj in room['objects']:
            if obj['kind'] == 'door' and obj['id'] in door_info:
                covered.add(door_info[obj['id']][2])
        room_covered_dirs[room['id']] = covered

    reverse_exits = {}
    for did, (obj, parent_rid, door_dir, dest_rid) in door_info.items():
        opp = _OPPOSITE_DIR.get(door_dir)
        if opp and opp not in room_covered_dirs.get(dest_rid, set()):
            reverse_exits.setdefault(dest_rid, {})[opp] = parent_rid

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
            i6dir  = _DIR_MAP.get(direction, direction + '_to')
            eline  = room.get('exit_lines', {}).get(direction)
            w(f'         {i6dir} {_resolve_room(dest, eline)},')
        for obj in room['objects']:
            if obj['kind'] == 'door' and obj['id'] in door_info:
                _, _, door_dir, _ = door_info[obj['id']]
                i6dir = _DIR_MAP[door_dir]
                w(f'         {i6dir} {obj["id"]},')
        for direction, dest_rid in reverse_exits.get(rid, {}).items():
            i6dir = _DIR_MAP.get(direction, direction + '_to')
            w(f'         {i6dir} {dest_rid},')
        _emit_handlers(w, room.get('handlers', {}), verb_action_map, known_ids, kinds_ctx)
        w( '    has light;')
        w('')

        for obj in room['objects']:
            if obj['kind'] == 'door' and obj['id'] in door_info:
                _, _, door_dir, dest_rid = door_info[obj['id']]
                _emit_door(w, obj, rid, door_dir, dest_rid, verb_action_map, known_ids,
                           kinds_ctx)
            elif obj['kind'] != 'door':
                _emit_object(w, obj, rid, verb_action_map, known_ids, kinds_ctx)

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
        loc      = f'{src_path.name}:{e.line}: ' if e.line else f'{src_path.name}: '
        code_str = f'[{e.code}] ' if e.code else ''
        print(f'{loc}{code_str}{e}', file=sys.stderr)
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
