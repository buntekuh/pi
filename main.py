#!/usr/bin/python3
import sys
from m56 import M56, USERRAM_START


def load_program(computer, path):
    if path.endswith('.asm'):
        from assembler import assemble
        with open(path) as f:
            source = f.read()
        code, _, _ = assemble(source, USERRAM_START)
    else:
        with open(path, 'rb') as f:
            code = f.read()
    computer.load(code, USERRAM_START)


def run_stdio(program_path=None, startup=True):
    from stdio_terminal import StdioTerminal
    terminal = StdioTerminal()
    computer = M56(terminal, startup=startup)
    terminal.connect(computer)
    if program_path:
        load_program(computer, program_path)
    computer.connect()
    # M56 runs in its own thread; main thread just waits for it to halt
    computer._thread.join()


def run_pygame(program_path=None, startup=True):
    from t46 import T46
    terminal = T46()
    computer = M56(terminal, startup=startup)
    terminal.connect(computer)
    if program_path:
        load_program(computer, program_path)
    computer.connect()
    while terminal.running:
        terminal.poll()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='M56 Mainframe')
    parser.add_argument('program', nargs='?', help='.asm or .bin file to run')
    parser.add_argument('--stdio', action='store_true',
                        help='use stdin/stdout instead of pygame window')
    parser.add_argument('--nostartup', action='store_true',
                        help='skip the boot sequence')
    args = parser.parse_args()

    startup = not args.nostartup
    if args.stdio:
        run_stdio(args.program, startup=startup)
    else:
        run_pygame(args.program, startup=startup)
