#!/usr/bin/env python3
"""
grue test runner

Pipes test commands from a .gts file into frotz and checks that each
expected substring appears in the game output.

Usage:
    python3 runner.py <game.z5> [game.gts]
    python3 runner.py --debug <game.z5> [game.gts]   # dump raw output
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path


ANSI = re.compile(r'\x1b\[[^a-zA-Z]*[a-zA-Z]|\x1b[^[]')


def _clean(text: str) -> str:
    text = ANSI.sub('', text)
    text = text.replace('\r', '')
    return text


def run_test(z5: Path, test: dict, debug: bool = False) -> tuple[int, int]:
    cmds = [c['cmd'] for c in test['commands']]
    inp  = '\n'.join(cmds) + '\nquit\ny\n'

    result = subprocess.run(
        ['dfrotz', str(z5)],
        input=inp,
        text=True,
        capture_output=True,
    )

    output = _clean(result.stdout)

    if debug:
        print('--- raw output ---')
        print(repr(output))
        print('------------------')

    passed = failed = 0
    for cmd_info in test['commands']:
        expect = cmd_info.get('expect')
        if not expect:
            continue

        if expect in output:
            print(f'  pass  {cmd_info["cmd"]!r}')
            passed += 1
        else:
            print(f'  FAIL  {cmd_info["cmd"]!r}')
            print(f'        expected : {expect!r}')
            failed += 1

    return passed, failed


def main():
    debug = False
    args  = sys.argv[1:]
    if args and args[0] == '--debug':
        debug = True
        args  = args[1:]

    if not args:
        print('usage: runner.py [--debug] <game.z5> [game.gts]', file=sys.stderr)
        sys.exit(1)

    z5  = Path(args[0])
    gts = Path(args[1]) if len(args) > 1 else z5.with_suffix('.gts')

    if not z5.exists():
        print(f'runner: {z5} not found', file=sys.stderr)
        sys.exit(1)
    if not gts.exists():
        print(f'runner: {gts} not found', file=sys.stderr)
        sys.exit(1)

    tests      = json.loads(gts.read_text())
    total_pass = total_fail = 0

    for test in tests:
        print(f'\ntest: {test["name"]!r}')
        p, f = run_test(z5, test, debug=debug)
        total_pass += p
        total_fail += f

    print(f'\n{total_pass} passed, {total_fail} failed')
    sys.exit(1 if total_fail else 0)


if __name__ == '__main__':
    main()
