"""
test_grui.py — regression tests for the Grue interpreter.

Each test is a list of (command, expected_substring) steps.
After each command the output produced up to the next prompt is checked
for the expected substring (case-insensitive).  Use None to skip the
assertion for a step that is only there to advance the game state.

Usage:
    python3 test_grui.py
"""

import sys
from pathlib import Path
from grui import load_and_run

GRUE_FILE = Path(__file__).parent / 'uplink' / 'grue' / 'test.grue'


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

class GameTest:
    """
    Feed a fixed sequence of inputs to the interpreter and record the
    output produced between consecutive prompts.
    """

    def __init__(self, steps):
        self._steps         = list(steps)
        self._idx           = 0
        self._chunk         = []
        self._results       = []   # list of (cmd, output, expected, passed)
        self._last_recorded = -1   # index of the last step already stored

    def _output(self, s):
        self._chunk.append(s)

    def _input(self, _prompt):
        # Flush the output accumulated since the previous call.
        chunk_text = ''.join(self._chunk)
        self._chunk = []

        # Associate it with the previous step.
        prev = self._idx - 1
        if 0 <= prev < len(self._steps):
            cmd, expected = self._steps[prev]
            passed = (expected is None) or (expected.lower() in chunk_text.lower())
            self._results.append((cmd, chunk_text, expected, passed))
            self._last_recorded = prev

        if self._idx >= len(self._steps):
            raise EOFError

        cmd = self._steps[self._idx][0]
        self._idx += 1
        return cmd

    def run(self, source):
        try:
            load_and_run(source, output=self._output, input_fn=self._input)
        except (EOFError, SystemExit, KeyboardInterrupt):
            pass

        # Flush output from the final step — only if _input didn't already do it
        # (which happens when _input raises EOFError after recording).
        chunk_text = ''.join(self._chunk)
        prev = self._idx - 1
        if 0 <= prev < len(self._steps) and prev > self._last_recorded:
            cmd, expected = self._steps[prev]
            passed = (expected is None) or (expected.lower() in chunk_text.lower())
            self._results.append((cmd, chunk_text, expected, passed))

        return self._results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_suite(name, steps, source):
    """Run one named test suite; return number of failures."""
    runner  = GameTest(steps)
    results = runner.run(source)
    failures = 0

    for cmd, output, expected, ok in results:
        if expected is None:
            continue
        if not ok:
            failures += 1
            print(f'  FAIL  [{cmd!r}]')
            print(f'        expected: {expected!r}')
            print(f'        got:      {output.strip()!r}')

    checked = sum(1 for _, _, e, _ in results if e is not None)
    passed  = checked - failures
    status  = 'ok' if not failures else f'{failures} FAILED'
    print(f'  {name}: {passed}/{checked}  [{status}]')
    return failures


# ---------------------------------------------------------------------------
# Test suites
# ---------------------------------------------------------------------------

SUITES = [

    ('player description', [
        ('x me', 'young tree'),
    ]),

    ('examine object', [
        ('x green shawl',  'forest green'),
        ('x red shawl',    'crimson'),
        ('x blue shawl',   'indigo'),
        ('x red apple',    None),            # no description → generic response
    ]),

    ('ambiguous noun asks to be more specific', [
        ('take shawl',      'more specific'),
        ('take red',        'more specific'),   # red Apple and Red Shawl both match
    ]),

    ('full name resolves directly', [
        ('take red shawl',  'taken'),
        ('i',               'red shawl'),
        ('take green apple', 'taken'),
        ('i',               'green apple'),
    ]),

    ('take and drop', [
        ('take green apple', 'taken'),
        ('i',                'green apple'),
        ('drop green apple', 'dropped'),
        ('i',                'nothing'),
    ]),

    ('cannot take living beings', [
        ('take merchant', "can't take"),
        ('take herbert',  "can't take"),
        ('take crow',     "can't take"),
    ]),

    ('object not present gives sensible error', [
        ('take sword',    "don't see"),
        ('x sword',       "don't see"),
        ('talk to sword', "don't see"),
    ]),

    ('look lists exits and takeable objects', [
        ('look', 'exits'),
        ('look', 'red apple'),
        ('look', 'green apple'),
        ('look', 'red shawl'),
    ]),

    ('talk to NPC', [
        ('talk to merchant', 'newcomer'),
        ('talk to herbert',  'caw'),
    ]),

    ('invalid direction', [
        ('go south', "can't go"),
        ('go up',    "can't go"),
        ('go west',  "can't go"),
    ]),

    ('wait advances turn, on turn fires every time', [
        ('wait', 'crowd shifts'),
        ('wait', 'crowd shifts'),
        ('wait', 'crowd shifts'),
    ]),

    ('on turn N fires once, dynamic object created', [
        ('wait', None),          # turn 1 — Norbert not yet here
        ('wait', None),          # turn 2 — Norbert created silently
        ('x norbert', 'squawk'), # he exists
        ('wait', None),          # turn 3 — no duplicate
        ('x norbert', 'squawk'), # still one Norbert
    ]),

    # on turn 1: in Fountain Plaza fires the same turn we arrive
    ('on turn 1 fires on room entry', [
        ('e', 'quieter here'),   # move east → counter resets to 0, then → 1
        ('wait', None),          # turn 2, handler already consumed
        ('wait', None),          # turn 3
    ]),

    # leaving and returning resets the turn counter:
    # on turn: (repeating) fires again in Market Square after re-entry
    ('turn counter resets on re-entry', [
        ('e', None),              # go to Fountain Plaza
        ('w', 'crowd shifts'),    # back to Market Square — on turn fires immediately
        ('e', None),              # go to Fountain Plaza again
        ('w', 'crowd shifts'),    # back again — fires again, counter was reset
    ]),

    ('help lists verbs and does not advance turn', [
        ('help',  'examine'),
        ('help',  'inventory'),
        ('wait',  'crowd shifts'),   # turn 1 — help didn't consume a turn
    ]),

    ('movement shows destination room', [
        ('e', 'fountain plaza'),
        ('w', 'market square'),
        ('n', 'side street'),
        ('s', 'market square'),
    ]),

    ('inventory persists across rooms', [
        ('take red apple',  'taken'),
        ('e',               None),        # move to Fountain Plaza
        ('i',               'red apple'), # still carrying it
        ('w',               None),        # back to Market Square
        ('drop red apple',  'dropped'),
        ('i',               'nothing'),
    ]),

]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    try:
        source = GRUE_FILE.read_text()
    except OSError as e:
        print(f'test_grui: cannot read {GRUE_FILE}: {e}', file=sys.stderr)
        sys.exit(1)

    print(f'Running {len(SUITES)} test suites against {GRUE_FILE.name}\n')

    total_failures = 0
    for name, steps in SUITES:
        total_failures += run_suite(name, steps, source)

    print()
    if total_failures:
        print(f'{total_failures} failure(s).')
        sys.exit(1)
    else:
        print('All tests passed.')


if __name__ == '__main__':
    main()
