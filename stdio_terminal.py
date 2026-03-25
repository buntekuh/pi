"""
Stdio terminal — drop-in replacement for T46 during development.

Implements the same interface as T46 (receive, io_write, io_read,
register_on_bus) but uses stdin/stdout instead of pygame.
No windowing, no threads, no palette. Just text.
"""

import sys


class StdioTerminal:

    def __init__(self):
        self.running = True

    def connect(self, m56):
        pass

    def register_on_bus(self, io_bus):
        from m56 import (PORT_T46_CMD, PORT_T46_ARG0, PORT_T46_ARG1,
                         PORT_T46_ARG2, PORT_T46_ARG3, PORT_T46_KEY)
        for port in (PORT_T46_CMD, PORT_T46_ARG0, PORT_T46_ARG1,
                     PORT_T46_ARG2, PORT_T46_ARG3, PORT_T46_KEY):
            io_bus.register(port, self)

    # ------------------------------------------------------------------
    # I/O bus device interface
    # ------------------------------------------------------------------

    def io_write(self, port, value):
        from m56 import (PORT_T46_CMD,  PORT_T46_ARG0, PORT_T46_ARG1,
                         PORT_T46_ARG2, PORT_T46_ARG3,
                         T46_CMD_CLS, T46_CMD_PRINT, T46_CMD_PEN,
                         T46_CMD_PLOT, T46_CMD_LINE,  T46_CMD_FILL,
                         T46_CMD_RECT, T46_CMD_MODE)
        if port == PORT_T46_ARG0:
            self._io_args[0] = value
        elif port == PORT_T46_ARG1:
            self._io_args[1] = value
        elif port == PORT_T46_ARG2:
            self._io_args[2] = value
        elif port == PORT_T46_ARG3:
            self._io_args[3] = value
        elif port == PORT_T46_CMD:
            a = self._io_args
            if value == T46_CMD_CLS:
                print("\033[2J\033[H", end="", flush=True)
            elif value == T46_CMD_PRINT:
                ch = chr(a[0] & 0xFF)
                sys.stdout.write(ch)
                sys.stdout.flush()
            # Graphics commands are silently ignored in stdio mode

    def io_read(self, port):
        from m56 import PORT_T46_KEY
        if port == PORT_T46_KEY:
            try:
                ch = self._stdin_buf.pop(0)
                return ord(ch)
            except IndexError:
                line = sys.stdin.readline()
                if not line:          # EOF
                    self.running = False
                    return 0
                self._stdin_buf = list(line)  # includes '\n'
                return ord(self._stdin_buf.pop(0))
        return 0

    # ------------------------------------------------------------------
    # Compatibility with code that calls receive() directly
    # ------------------------------------------------------------------

    def receive(self, command):
        t = command.get("type")
        if t == "print":
            sys.stdout.write(command["text"])
            sys.stdout.flush()
        elif t == "cls":
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.flush()
        elif t == "goto":
            sys.stdout.write(f"\033[{command['row']+1};{command['col']+1}H")
            sys.stdout.flush()
        elif t == "scroll_region":
            # ANSI CSI Ps ; Ps r — set top/bottom margins (1-based)
            bottom = command["bottom"] + 1
            sys.stdout.write(f"\033[1;{bottom}r")
            sys.stdout.flush()

    def read_line(self):
        """Block until the user presses Enter. Returns the line without newline."""
        line = sys.stdin.readline()
        if not line:
            self.running = False
            return ""
        return line.rstrip("\n")

    def set_raw(self, raw):
        self._raw_mode = raw

    def read_key(self):
        """Read one raw keypress. Supports arrow keys via ANSI escape sequences."""
        import tty
        import termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                seq = sys.stdin.read(2)
                _ESC = {"[A": "UP", "[B": "DOWN", "[C": "RIGHT", "[D": "LEFT",
                        "[H": "HOME", "[F": "END"}
                if seq in _ESC:
                    return _ESC[seq]
                if seq in ("[5", "[6"):
                    sys.stdin.read(1)   # consume trailing '~'
                    return "PGUP" if seq == "[5" else "PGDN"
                return ch
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    def poll(self):
        pass   # no event loop needed

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    _io_args    = [0, 0, 0, 0]
    _stdin_buf  = []
