"""
M56 Mainframe

Virtual fantasy computer. Contains:
  - Memory (flat bytearray, memory-mapped layout from spec)
  - CPU (fetch/decode/execute — stubbed for now)
  - OS (syscall layer — handles input from T46, sends output back)
  - Filesystem (nested dicts)

The M56 runs in its own thread. The T46 pushes input via m56.input().
The M56 pushes display commands via terminal.receive().
"""

import threading


# ---------------------------------------------------------------------------
# Memory map
# ---------------------------------------------------------------------------
#
# 0x00000             Reset vector (3 bytes: LDI + jump to OS init)
# 0x00003 - 0x0003F   OS scratch (61 bytes)
# 0x00040 - 0x000FF   CPU state (registers, flags, etc.)
# 0x00100 - 0x003FF   Kernel call table
# 0x00400 - ...       ROM (OS, Pi interpreter, Zero interpreter)
# Above ROM           User RAM

RAM_SIZE        = 0x10000   # 64 KB user-visible
SYSTEM_SIZE     = 0x06000   # 24 KB system
TOTAL_MEM       = RAM_SIZE + SYSTEM_SIZE

ROM_START       = 0x00400
USERRAM_START   = 0x08000   # above ROM

CPU_STATE_BASE  = 0x00040
CALL_TABLE_BASE = 0x00100


# CPU state offsets within CPU_STATE_BASE (each register = 2 bytes, 16-bit)
_REG_OFFSETS = {
    "R0": 0, "R1": 2, "R2": 4, "R3": 6,
    "R4": 8, "R5": 10, "R6": 12, "R7": 14,
    "FLAGS": 16,
    "CPG": 18,   # 1 byte used
    "DPG": 19,   # 1 byte used
    "SP": 20,
    "PC": 22,    # 20-bit, stored in 3 bytes
}

FLAGS_ZERO      = 0x01
FLAGS_CARRY     = 0x02
FLAGS_OVERFLOW  = 0x04
FLAGS_NEGATIVE  = 0x08

# ---------------------------------------------------------------------------
# Opcodes
# ---------------------------------------------------------------------------

OP_LOAD = 0;  OP_ADD  = 1;  OP_SUB  = 2;  OP_AND  = 3
OP_OR   = 4;  OP_XOR  = 5;  OP_NOT  = 6;  OP_SFT  = 7
OP_SAR  = 8;  OP_MUL  = 9;  OP_DIV  = 10; OP_SWP  = 11
OP_JMP  = 12; OP_CAL  = 13; OP_RET  = 14; OP_PUSH = 15
OP_POP  = 16; OP_NOP  = 17; OP_HALT = 18
OP_OUT  = 19; OP_IN   = 20

# I/O port assignments
PORT_T46_CMD  = 0x01   # write: execute terminal command
PORT_T46_ARG0 = 0x02   # write: argument 0
PORT_T46_ARG1 = 0x03   # write: argument 1
PORT_T46_ARG2 = 0x04   # write: argument 2
PORT_T46_ARG3 = 0x05   # write: argument 3
PORT_T46_KEY  = 0x06   # read:  next keycode (blocks until available)

# T46 command codes
T46_CMD_CLS   = 0x01
T46_CMD_PRINT = 0x02   # arg0 = char code
T46_CMD_PEN   = 0x03   # arg0 = colour index
T46_CMD_PLOT  = 0x04   # arg0=x, arg1=y
T46_CMD_LINE  = 0x05   # arg0=x1, arg1=y1, arg2=x2, arg3=y2
T46_CMD_FILL  = 0x06   # arg0=x, arg1=y
T46_CMD_RECT  = 0x07   # arg0=x, arg1=y, arg2=w, arg3=h
T46_CMD_MODE  = 0x08   # arg0=0(text) or 1(graphics)

# LOAD addressing modes (encoded in rs field)
LOAD_IMM    = 0   # LOAD #imm13, Rd
LOAD_RR     = 1   # LOAD Rs, Rd          (source reg in imm[2:0])
LOAD_IND_R  = 2   # LOAD [Rs], Rd        (addr reg in imm[2:0])
LOAD_IND_W  = 3   # LOAD Rd, [Rs]        (addr reg in imm[2:0])
LOAD_IDX_R  = 4   # LOAD [Rs+off], Rd    (base in imm[12:10], off in imm[9:0])
LOAD_IDX_W  = 5   # LOAD Rd, [Rs+off]    (base in imm[12:10], off in imm[9:0])
LOAD_PCREL  = 6   # LOAD [PC+off], Rd

# Condition codes (used in rs field of JMP/CAL/RET)
COND_Z  = 0; COND_NZ = 1; COND_C  = 2; COND_NC = 3
COND_N  = 4; COND_NN = 5; COND_V  = 6; COND_AL = 7


class IOBus:
    """
    I/O bus. Devices register port ranges and handle read/write.
    OUT is synchronous. IN blocks until the device has data.
    """

    def __init__(self):
        self._devices = {}   # port -> device

    def register(self, port, device):
        self._devices[port] = device

    def write(self, port, value):
        dev = self._devices.get(port)
        if dev:
            dev.io_write(port, value)

    def read(self, port):
        dev = self._devices.get(port)
        if dev:
            return dev.io_read(port)
        return 0


class Memory:
    def __init__(self, size=TOTAL_MEM):
        self._mem = bytearray(size)
        self.size = size

    def read8(self, addr):
        return self._mem[addr % self.size]

    def write8(self, addr, val):
        self._mem[addr % self.size] = val & 0xFF

    def read16(self, addr):
        lo = self._mem[addr % self.size]
        hi = self._mem[(addr + 1) % self.size]
        return lo | (hi << 8)

    def write16(self, addr, val):
        val &= 0xFFFF
        self._mem[addr % self.size]       = val & 0xFF
        self._mem[(addr + 1) % self.size] = (val >> 8) & 0xFF

    def read_bytes(self, addr, count):
        return bytes(self._mem[addr:addr + count])

    def write_bytes(self, addr, data):
        self._mem[addr:addr + len(data)] = data


class CPU:
    """
    M56 CPU — 8 x 16-bit registers, 20-bit address space via page registers.
    Registers are memory-mapped at CPU_STATE_BASE.
    """

    def __init__(self, memory, io_bus=None):
        self.mem    = memory
        self.io_bus = io_bus
        self.halted = False

    # Register access via memory map
    def get_reg(self, name):
        off = _REG_OFFSETS[name]
        return self.mem.read16(CPU_STATE_BASE + off)

    def set_reg(self, name, val):
        off = _REG_OFFSETS[name]
        self.mem.write16(CPU_STATE_BASE + off, val)

    @property
    def pc(self):
        # PC is 20-bit: stored as 3 bytes little-endian
        base = CPU_STATE_BASE + _REG_OFFSETS["PC"]
        b0 = self.mem.read8(base)
        b1 = self.mem.read8(base + 1)
        b2 = self.mem.read8(base + 2)
        return b0 | (b1 << 8) | ((b2 & 0x0F) << 16)

    @pc.setter
    def pc(self, val):
        val &= 0xFFFFF
        base = CPU_STATE_BASE + _REG_OFFSETS["PC"]
        self.mem.write8(base,     val & 0xFF)
        self.mem.write8(base + 1, (val >> 8) & 0xFF)
        self.mem.write8(base + 2, (val >> 16) & 0x0F)

    @property
    def sp(self):
        return self.mem.read16(CPU_STATE_BASE + _REG_OFFSETS["SP"])

    @sp.setter
    def sp(self, val):
        self.mem.write16(CPU_STATE_BASE + _REG_OFFSETS["SP"], val)

    @property
    def flags(self):
        return self.mem.read16(CPU_STATE_BASE + _REG_OFFSETS["FLAGS"])

    @flags.setter
    def flags(self, val):
        self.mem.write16(CPU_STATE_BASE + _REG_OFFSETS["FLAGS"], val)

    def flag(self, f):
        return bool(self.flags & f)

    def set_flag(self, f, val):
        if val:
            self.flags |= f
        else:
            self.flags &= ~f

    def fetch(self):
        """Fetch one 24-bit instruction from PC, advance PC by 3."""
        addr = self.pc
        b0 = self.mem.read8(addr)
        b1 = self.mem.read8(addr + 1)
        b2 = self.mem.read8(addr + 2)
        self.pc = addr + 3
        return b0 | (b1 << 8) | (b2 << 16)

    def decode(self, instr):
        """
        Instruction format (24-bit):
          23..19  opcode  (5 bits)
          18..16  rs      (3 bits)
          15..13  rd      (3 bits)
          12..0   imm13   (13 bits)
        """
        opcode = (instr >> 19) & 0x1F
        rs     = (instr >> 16) & 0x07
        rd     = (instr >> 13) & 0x07
        imm13  = instr & 0x1FFF
        return opcode, rs, rd, imm13

    def step(self):
        """Fetch, decode, execute one instruction. Returns False if halted."""
        if self.halted:
            return False
        instr = self.fetch()
        opcode, rs, rd, imm13 = self.decode(instr)
        self._execute(opcode, rs, rd, imm13)
        return True

    # ------------------------------------------------------------------
    # Condition check
    # ------------------------------------------------------------------

    def _cond(self, c):
        if c == COND_Z:  return self.flag(FLAGS_ZERO)
        if c == COND_NZ: return not self.flag(FLAGS_ZERO)
        if c == COND_C:  return self.flag(FLAGS_CARRY)
        if c == COND_NC: return not self.flag(FLAGS_CARRY)
        if c == COND_N:  return self.flag(FLAGS_NEGATIVE)
        if c == COND_NN: return not self.flag(FLAGS_NEGATIVE)
        if c == COND_V:  return self.flag(FLAGS_OVERFLOW)
        return True  # COND_AL

    # ------------------------------------------------------------------
    # Stack
    # ------------------------------------------------------------------

    def _push16(self, val):
        self.sp = (self.sp - 2) & 0xFFFF
        self.mem.write16(self.sp, val)

    def _pop16(self):
        val = self.mem.read16(self.sp)
        self.sp = (self.sp + 2) & 0xFFFF
        return val

    # ------------------------------------------------------------------
    # Flag update after arithmetic
    # ------------------------------------------------------------------

    def _set_arith_flags(self, result, carry=False, overflow=False):
        r16 = result & 0xFFFF
        self.set_flag(FLAGS_ZERO,     r16 == 0)
        self.set_flag(FLAGS_NEGATIVE, bool(r16 & 0x8000))
        self.set_flag(FLAGS_CARRY,    carry)
        self.set_flag(FLAGS_OVERFLOW, overflow)
        return r16

    # ------------------------------------------------------------------
    # Register helpers
    # ------------------------------------------------------------------

    def _rn(self, n):
        return self.get_reg(f"R{n}")

    def _setrn(self, n, val):
        self.set_reg(f"R{n}", val)

    # ------------------------------------------------------------------
    # Execute one decoded instruction
    # ------------------------------------------------------------------

    def _execute(self, opcode, rs, rd, imm13):
        if opcode == OP_NOP:
            return

        if opcode == OP_HALT:
            self.halted = True
            return

        # ---- I/O bus ----
        # OUT #port, Rs  — rs=source register, imm13=port number
        if opcode == OP_OUT:
            if self.io_bus:
                self.io_bus.write(imm13 & 0xFF, self._rn(rs))
            return

        # IN Rd, #port   — rd=dest register, imm13=port number
        # Blocks if the device has no data yet (acts as a blocking syscall)
        if opcode == OP_IN:
            val = self.io_bus.read(imm13 & 0xFF) if self.io_bus else 0
            self._setrn(rd, val & 0xFFFF)
            return

        # ---- LOAD ----
        if opcode == OP_LOAD:
            mode = rs
            if mode == LOAD_IMM:
                self._setrn(rd, imm13)
            elif mode == LOAD_RR:
                self._setrn(rd, self._rn(imm13 & 0x7))
            elif mode == LOAD_IND_R:
                addr = self._rn(imm13 & 0x7)
                self._setrn(rd, self.mem.read16(addr))
            elif mode == LOAD_IND_W:
                addr = self._rn(imm13 & 0x7)
                self.mem.write16(addr, self._rn(rd))
            elif mode == LOAD_IDX_R:
                base = self._rn((imm13 >> 10) & 0x7)
                off  = imm13 & 0x3FF
                self._setrn(rd, self.mem.read16(base + off))
            elif mode == LOAD_IDX_W:
                base = self._rn((imm13 >> 10) & 0x7)
                off  = imm13 & 0x3FF
                self.mem.write16(base + off, self._rn(rd))
            elif mode == LOAD_PCREL:
                addr = self.pc + imm13   # PC already advanced past instruction
                self._setrn(rd, self.mem.read16(addr))
            return

        # ---- ALU: ADD SUB AND OR XOR MUL DIV ----
        # imm13 bit 12: 0 = register source (rs field), 1 = immediate (imm[11:0])
        if opcode in (OP_ADD, OP_SUB, OP_AND, OP_OR, OP_XOR, OP_MUL, OP_DIV):
            if imm13 & 0x1000:
                src = imm13 & 0xFFF
            else:
                src = self._rn(rs)
            dst = self._rn(rd)

            if opcode == OP_ADD:
                raw = dst + src
                r   = self._set_arith_flags(raw,
                          carry    = raw > 0xFFFF,
                          overflow = ((dst ^ raw) & (src ^ raw) & 0x8000) != 0)
            elif opcode == OP_SUB:
                raw = dst - src
                r   = self._set_arith_flags(raw,
                          carry    = src > dst,
                          overflow = ((dst ^ src) & (dst ^ raw) & 0x8000) != 0)
            elif opcode == OP_AND:
                r = self._set_arith_flags(dst & src)
            elif opcode == OP_OR:
                r = self._set_arith_flags(dst | src)
            elif opcode == OP_XOR:
                r = self._set_arith_flags(dst ^ src)
            elif opcode == OP_MUL:
                raw = dst * src
                r   = self._set_arith_flags(raw, carry=(raw > 0xFFFF))
            elif opcode == OP_DIV:
                if src == 0:
                    self.halted = True
                    return
                r = self._set_arith_flags(dst // src)
            self._setrn(rd, r)
            return

        # ---- Unary / shift ----
        if opcode == OP_NOT:
            r = self._set_arith_flags(~self._rn(rd))
            self._setrn(rd, r)
            return

        if opcode == OP_SFT:
            # 4-bit signed shift: bit 3 set = negative = right shift
            n   = imm13 & 0xF
            if n & 0x8:
                n = n - 16
            val = self._rn(rd)
            r   = (val << n) if n >= 0 else (val >> (-n))
            self._setrn(rd, self._set_arith_flags(r))
            return

        if opcode == OP_SAR:
            n   = imm13 & 0xF
            val = self._rn(rd)
            if val & 0x8000:      # sign-extend into Python int
                val |= ~0xFFFF
            self._setrn(rd, self._set_arith_flags(val >> n))
            return

        if opcode == OP_SWP:
            val = self._rn(rd)
            self._setrn(rd, ((val & 0xFF) << 8) | ((val >> 8) & 0xFF))
            return

        # ---- Stack ----
        if opcode == OP_PUSH:
            self._push16(self._rn(rd))
            return

        if opcode == OP_POP:
            self._setrn(rd, self._pop16())
            return

        # ---- Control flow ----
        # Direct mode (rd==0): imm13 is a signed PC-relative offset.
        # Indirect mode (rd!=0): jump to address in register Rrd.
        if opcode == OP_JMP:
            if self._cond(rs):
                if rd != 0:
                    target = self._rn(rd)
                else:
                    offset = imm13 if not (imm13 & 0x1000) else imm13 - 0x2000
                    target = self.pc + offset
                self.pc = target
            return

        if opcode == OP_CAL:
            if self._cond(rs):
                self._push16(self.pc & 0xFFFF)
                if rd != 0:
                    target = self._rn(rd)
                else:
                    offset = imm13 if not (imm13 & 0x1000) else imm13 - 0x2000
                    target = self.pc + offset
                self.pc = target
            return

        if opcode == OP_RET:
            if self._cond(rs):
                self.pc = self._pop16()
            return

    def reset(self):
        self.halted = False
        self.pc = 0x00000
        self.sp = USERRAM_START - 1
        self.flags = 0


class Filesystem:
    """
    Simple nested-dict filesystem.

    Files are strings. Directories are dicts.
    Paths are Unix-style strings.
    """

    def __init__(self):
        self._root = {
            "sys": {
                "shell.pi": "# shell stub\n",
            },
            "home": {},
        }
        self._cwd = "/"

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def _resolve(self, path):
        if path.startswith("/"):
            parts = path.strip("/").split("/")
        else:
            base = [] if self._cwd == "/" else self._cwd.strip("/").split("/")
            parts = base + path.split("/")
        # normalise . and ..
        out = []
        for p in parts:
            if p == "" or p == ".":
                continue
            elif p == "..":
                if out:
                    out.pop()
            else:
                out.append(p)
        return out

    def _navigate(self, parts):
        node = self._root
        for p in parts:
            if not isinstance(node, dict) or p not in node:
                return None
            node = node[p]
        return node

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def cwd(self):
        return self._cwd

    def ls(self, path=None):
        parts = self._resolve(path or self._cwd)
        node  = self._navigate(parts)
        if node is None:
            return None, "no such directory"
        if not isinstance(node, dict):
            return None, "not a directory"
        return sorted(node.keys()), None

    def cd(self, path):
        parts = self._resolve(path)
        node  = self._navigate(parts)
        if node is None:
            return "no such directory"
        if not isinstance(node, dict):
            return "not a directory"
        self._cwd = "/" + "/".join(parts) if parts else "/"
        return None

    def read_file(self, path):
        parts = self._resolve(path)
        node  = self._navigate(parts)
        if node is None:
            return None, "no such file"
        if isinstance(node, dict):
            return None, "is a directory"
        return node, None

    def write_file(self, path, content):
        parts = self._resolve(path)
        if not parts:
            return "cannot write to root"
        parent = self._navigate(parts[:-1])
        if parent is None or not isinstance(parent, dict):
            return "no such directory"
        parent[parts[-1]] = content
        return None

    def mkdir(self, path):
        parts = self._resolve(path)
        if not parts:
            return "cannot mkdir root"
        parent = self._navigate(parts[:-1])
        if parent is None or not isinstance(parent, dict):
            return "no such directory"
        name = parts[-1]
        if name in parent:
            return "already exists"
        parent[name] = {}
        return None


class OS:
    """
    M56 OS — syscall layer. No threads, no interrupts.
    Input arrives from the terminal; output goes back to the terminal.
    """

    def __init__(self, fs, terminal):
        self.fs       = fs
        self.terminal = terminal
        self._input_buf  = []
        self._input_lock = threading.Lock()
        self._input_event = threading.Event()

    # ------------------------------------------------------------------
    # Called by T46 when a key arrives
    # ------------------------------------------------------------------

    def push_input(self, char):
        with self._input_lock:
            self._input_buf.append(char)
        self._input_event.set()

    # ------------------------------------------------------------------
    # Syscalls (called by CPU / Pi interpreter)
    # ------------------------------------------------------------------

    def read_line(self):
        """Block until a full line is available. Returns the line (no newline)."""
        line = []
        while True:
            self._input_event.wait()
            with self._input_lock:
                chars = list(self._input_buf)
                self._input_buf.clear()
                self._input_event.clear()
            for ch in chars:
                if ch == "\n":
                    return "".join(line)
                elif ch == "\b":
                    if line:
                        line.pop()
                        self.print_char("\b \b")
                else:
                    line.append(ch)
                    self.print_char(ch)

    def print_text(self, text):
        self.terminal.receive({"type": "print", "text": text})

    def print_char(self, ch):
        self.terminal.receive({"type": "print", "text": ch})

    def println(self, text=""):
        self.print_text(text + "\n")

    def sys_ls(self, path=None):
        entries, err = self.fs.ls(path)
        if err:
            self.println(f"ls: {err}")
            return
        self.println("  ".join(entries) if entries else "")

    def sys_cd(self, path):
        err = self.fs.cd(path)
        if err:
            self.println(f"cd: {err}")

    def sys_cat(self, path):
        content, err = self.fs.read_file(path)
        if err:
            self.println(f"cat: {err}")
            return
        self.println(content)

    def sys_write(self, path, content):
        err = self.fs.write_file(path, content)
        if err:
            self.println(f"write: {err}")

    def sys_mkdir(self, path):
        err = self.fs.mkdir(path)
        if err:
            self.println(f"mkdir: {err}")


class Shell:
    """
    Minimal line-oriented command interpreter running on the OS layer.
    This stands in for the Pi shell program that will eventually live in ROM.
    """

    COMMANDS = {"ls", "cd", "cat", "mkdir", "help"}

    def __init__(self, os_):
        self.os = os_

    def prompt(self):
        self.os.print_text(f"{self.os.fs.cwd}> ")

    def run_line(self, line):
        line = line.strip()
        if not line:
            return
        parts = line.split(None, 1)
        cmd   = parts[0]
        arg   = parts[1] if len(parts) > 1 else None

        if cmd == "ls":
            self.os.sys_ls(arg)
        elif cmd == "cd":
            if arg:
                self.os.sys_cd(arg)
            else:
                self.os.sys_cd("/")
        elif cmd == "cat":
            if arg:
                self.os.sys_cat(arg)
            else:
                self.os.println("usage: cat <file>")
        elif cmd == "mkdir":
            if arg:
                self.os.sys_mkdir(arg)
            else:
                self.os.println("usage: mkdir <dir>")
        elif cmd == "help":
            self.os.println("commands: " + "  ".join(sorted(self.COMMANDS)))
        else:
            self.os.println(f"unknown command: {cmd}")

    def loop(self):
        self.os.println("M56 ready.")
        while True:
            self.prompt()
            line = self.os.read_line()
            self.run_line(line)


class M56:
    def __init__(self, terminal):
        self.terminal = terminal
        self.memory   = Memory()
        self.io_bus   = IOBus()
        self.cpu      = CPU(self.memory, self.io_bus)
        self.fs       = Filesystem()
        self.os       = OS(self.fs, terminal)
        self.shell    = Shell(self.os)

        self._entry   = None
        self._thread  = threading.Thread(target=self._run, daemon=True)

    def load(self, code, addr=USERRAM_START):
        """Load machine code into memory and set PC to addr."""
        self.memory.write_bytes(addr, code)
        self._entry = addr

    def connect(self):
        self.terminal.register_on_bus(self.io_bus)
        self.cpu.reset()
        self._thread.start()

    def input(self, char):
        """Legacy path: called by T46 for the Python-level OS shell."""
        self.os.push_input(char)

    def _run(self):
        if self._entry is not None:
            self.cpu.pc = self._entry
            while not self.cpu.halted:
                self.cpu.step()
        else:
            self.shell.loop()
