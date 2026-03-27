"""
M56 Mainframe

Virtual fantasy computer. Contains:
  - Memory (flat bytearray, memory-mapped layout from spec)
  - CPU (fetch/decode/execute)
  - OS (syscall layer — handles input from T46, sends output back)
  - 56FS filesystem

The M56 runs in its own thread. The T46 pushes input via m56.input().
The M56 pushes display commands via terminal.receive().
"""

import threading
from fs56 import FS56


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




class OS:
    """
    M56 OS — syscall layer. No threads, no interrupts.
    Input arrives from the terminal; output goes back to the terminal.
    """

    def __init__(self, fs, terminal):
        self.fs       = fs
        self.terminal = terminal

    # ------------------------------------------------------------------
    # Syscalls (called by CPU / Pi interpreter)
    # ------------------------------------------------------------------

    def read_line(self):
        """Block until the user presses Enter. Returns the line (no newline)."""
        return self.terminal.read_line()

    def print_text(self, text):
        self.terminal.receive({"type": "print", "text": text})

    def print_char(self, ch):
        self.terminal.receive({"type": "print", "text": ch})

    def println(self, text=""):
        self.print_text(text + "\n")

    def sys_ls(self, path=None):
        try:
            entries = self.fs.ls(path)
            if not entries:
                return
            # dirs first, then files; dirs get trailing /
            dirs  = sorted(n + '/' for n, t, _ in entries if t == 2)
            files = sorted(n       for n, t, _ in entries if t != 2)
            self.println("  ".join(dirs + files))
        except Exception as e:
            self.println(f"ls: {e}")

    def sys_cd(self, path):
        try:
            self.fs.cd(path)
        except Exception as e:
            self.println(f"cd: {e}")

    def sys_cat(self, path):
        try:
            data = self.fs.read_file(path)
            self.println(data.decode(errors='replace'))
        except Exception as e:
            self.println(f"cat: {e}")

    def sys_write(self, path, content):
        try:
            self.fs.write_file(path, content)
        except Exception as e:
            self.println(f"write: {e}")

    def sys_mkdir(self, path):
        try:
            self.fs.mkdir(path)
        except Exception as e:
            self.println(f"mkdir: {e}")

    def sys_cp(self, src, dst):
        try:
            data = self.fs.read_file(src)
        except Exception as e:
            self.println(f"cp: {e}")
            return
        # If dst is a directory, copy into it using src's filename.
        try:
            if self.fs.stat(dst).get('type') == 2:   # TYPE_DIR
                from pathlib import Path
                dst = dst.rstrip('/') + '/' + Path(src).name
        except Exception:
            pass
        try:
            self.fs.write_file(dst, data)
        except Exception as e:
            self.println(f"cp: {e}")
            return
        self.println(f"{src} → {dst}")

    def sys_edit(self, path):
        from editor import Editor
        try:
            highlighter = None
            if path.endswith('.grue'):
                from grui import highlight_line
                highlighter = highlight_line
            try:
                content = self.fs.read_file(path).decode(errors="replace")
            except Exception:
                content = ""
            Editor(self, path, highlighter=highlighter).run(content)
        except Exception as e:
            self.println(f"edit: {e}")

    def sys_asm(self, path, out_path=None):
        """Assemble a .asm file from the virtual FS, write the binary back."""
        from assembler import assemble, AssemblerError
        import os as _os
        try:
            source = self.fs.read_file(path).decode(errors='replace')
        except Exception as e:
            self.println(f"asm: {e}")
            return
        try:
            code, labels, _ = assemble(source, USERRAM_START)
        except AssemblerError as e:
            self.println(f"asm: {e}")
            return
        if out_path is None:
            basename = _os.path.basename(path)
            stem     = basename.rsplit('.', 1)[0] if '.' in basename else basename
            out_path = f'/tmp/{stem}.bin'
        try:
            self.fs.write_file(out_path, code)
        except Exception as e:
            self.println(f"asm: write failed: {e}")
            return
        self.println(f"assembled {len(code)} bytes  →  {out_path}")
        if labels:
            label_strs = [f"{n}=0x{a:05X}"
                          for n, a in sorted(labels.items(), key=lambda x: x[1])]
            self.println("labels: " + "  ".join(label_strs))

    def sys_grue(self, src_path, out_path=None):
        """Compile a .grue file to .pi."""
        from grue import parse, emit, GrueError
        from pathlib import Path
        try:
            data = self.fs.read_file(src_path)
        except Exception as e:
            self.println(f"grue: {e}")
            return
        if out_path is None:
            stem = Path(src_path).stem
            out_path = f'/tmp/{stem}.pi'
        try:
            ast = parse(data.decode(errors='replace'))
            pi  = emit(ast)
        except GrueError as e:
            self.println(f"grue: {e}")
            return
        try:
            self.fs.write_file(out_path, pi.encode())
        except Exception as e:
            self.println(f"grue: write failed: {e}")
            return
        self.println(f"compiled {src_path}  →  {out_path}  ({len(ast['rooms'])} rooms)")

    def sys_grui(self, src_path, script_path=None):
        """Interpret a .grue file directly.  If script_path is given, commands
        are read from that file one per line with a short pause between each."""
        import time
        from grui import load_and_run, GrueError

        try:
            data = self.fs.read_file(src_path)
        except Exception as e:
            self.println(f"grui: {e}")
            return

        # --- input function --------------------------------------------------
        if script_path:
            try:
                raw = self.fs.read_file(script_path).decode(errors='replace')
            except Exception as e:
                self.println(f"grui: {e}")
                return
            commands = [l.strip() for l in raw.splitlines()
                        if l.strip() and not l.strip().startswith('//')]
            it = iter(commands)
            def scripted_input(_):
                time.sleep(0.6)
                cmd = next(it, None)
                if cmd is None:
                    raise EOFError
                self.print_text(cmd + '\n')
                return cmd
            input_fn = scripted_input
        else:
            input_fn = lambda _: self.read_line()

        # --- status bar (T46 only) -------------------------------------------
        term       = getattr(self, 'terminal', None)
        status_fn  = None
        SCROLL_ROW = 22   # rows 0-22 scroll; 23-24 are the fixed status bar

        if term is not None:
            def draw_status(room_name, exits):
                # T46 handles cursor save/restore in the main thread where
                # _cur_row is authoritative — no cross-thread tracking needed.
                term.receive({'type': 'status',
                              'room': room_name, 'exits': exits})

            # Clear screen and set scroll region so rows 23-24 are protected.
            term.receive({'type': 'cls'})
            term.receive({'type': 'goto', 'row': 0, 'col': 0})
            term.receive({'type': 'scroll_region', 'bottom': SCROLL_ROW})

            status_fn = draw_status

        output_fn = self.print_text

        # --- run -------------------------------------------------------------
        try:
            load_and_run(
                data.decode(errors='replace'),
                output=output_fn,
                input_fn=input_fn,
                status_fn=status_fn,
            )
        except GrueError as e:
            self.println(f"grui: {e}")
        finally:
            if term is not None:
                # Restore full-screen scroll and clear the status bar rows.
                term.receive({'type': 'scroll_region', 'bottom': 24})
                term.receive({'type': 'cls'})
                term.receive({'type': 'goto', 'row': 0, 'col': 0})

    def sys_grui_check(self, src_path):
        """Run the Grue syntax/semantic checker on a .grue file."""
        from grui import Parser, GrueError
        try:
            data = self.fs.read_file(src_path)
        except Exception as e:
            self.println(f"grue: {e}")
            return
        source = data.decode(errors='replace')
        try:
            issues = Parser().check(source)
        except GrueError as e:
            self.println(f"grue: {e}")
            return
        if not issues:
            self.println(f"{src_path}: ok")
        else:
            for issue in issues:
                self.println(f"{src_path}: {issue}")

    def sys_debug(self, path):
        """Load a .asm or .bin file from the virtual FS and start the debugger."""
        from assembler import assemble, AssemblerError
        from debugger import Debugger
        load_addr = USERRAM_START
        try:
            data = self.fs.read_file(path)
        except Exception as e:
            self.println(f"debug: {e}")
            return
        if path.endswith('.asm') or path.endswith('.s'):
            try:
                code, labels, listing = assemble(data.decode(errors='replace'), load_addr)
            except AssemblerError as e:
                self.println(f"debug: assembler error: {e}")
                return
            self.println(f"assembled {len(code)} bytes at 0x{load_addr:05X}")
        else:
            code    = data
            labels  = {}
            listing = [(load_addr + i, code[i:i+3], '')
                       for i in range(0, len(code), 3)]
            self.println(f"loaded {len(code)} bytes at 0x{load_addr:05X}")
        mem = Memory()
        mem.write_bytes(load_addr, code)
        cpu = CPU(mem)
        cpu.reset()
        cpu.pc = load_addr
        cpu.sp = load_addr - 2
        Debugger(cpu, mem, load_addr, listing, labels,
                 println=self.println, read_line=self.read_line,
                 term=self.terminal).loop()

    def sys_run(self, path):
        """Run a Pi source file from the virtual filesystem."""
        from pi_interp import Interpreter, InterpError
        from pi_lexer import LexError
        try:
            source = self.fs.read_file(path).decode(errors="replace")
        except Exception as e:
            self.println(f"run: {e}")
            return
        interp = Interpreter(output=self.print_text, input_fn=self.read_line,
                             term_fn=self.terminal.receive)
        try:
            interp.run(source)
        except (LexError, InterpError) as e:
            self.println(str(e))

    def sys_repl(self):
        """Launch the interactive Pi REPL."""
        from pi_repl import PiRepl
        repl = PiRepl(println=self.println, read_line=self.read_line,
                      term=self.terminal)
        repl.loop()


def _common_prefix(words):
    if not words:
        return ''
    prefix = words[0]
    for w in words[1:]:
        while not w.startswith(prefix):
            prefix = prefix[:-1]
            if not prefix:
                return ''
    return prefix


class Shell:
    """
    Minimal line-oriented command interpreter running on the OS layer.
    This stands in for the Pi shell program that will eventually live in ROM.
    """

    COMMANDS = {"ls", "cd", "mkdir", "cat", "cp", "edit", "run", "bat", "asm", "debug", "grue", "pi", "help"}

    def __init__(self, os_):
        self.os = os_
        if hasattr(os_.terminal, 'set_tab_callback'):
            os_.terminal.set_tab_callback(self.complete)

    def prompt(self):
        self.os.print_text(f"{self.os.fs.cwd} > ")

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
                self.os.sys_cd("/home")
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
        elif cmd == "cp":
            if arg:
                parts2 = arg.split(None, 1)
                if len(parts2) == 2:
                    self.os.sys_cp(parts2[0], parts2[1])
                else:
                    self.os.println("usage: cp <src> <dst>")
            else:
                self.os.println("usage: cp <src> <dst>")
        elif cmd == "edit":
            if arg:
                self.os.sys_edit(arg)
            else:
                self.os.println("usage: edit <file>")
        elif cmd == "run":
            if arg:
                if arg.endswith('.bat'):
                    self._run_bat(arg)
                elif arg.split(None, 1)[0].endswith('.grue'):
                    self.os.sys_grui(arg.split(None, 1)[0])
                else:
                    self.os.sys_run(arg)
            else:
                self.os.println("usage: run <file.pi|file.bat|file.grue>")
        elif cmd == "bat":
            if arg:
                self._run_bat(arg)
            else:
                self.os.println("usage: bat <file.bat>")
        elif cmd == "asm":
            if arg:
                parts2 = arg.split(None, 1)
                self.os.sys_asm(parts2[0], parts2[1] if len(parts2) > 1 else None)
            else:
                self.os.println("usage: asm <file.asm> [output.bin]")
        elif cmd == "grue":
            if arg:
                parts2 = arg.split()
                check  = '--check' in parts2
                parts2 = [p for p in parts2 if p != '--check']
                if check:
                    self.os.sys_grui_check(parts2[0])
                else:
                    self.os.sys_grui(parts2[0], parts2[1] if len(parts2) > 1 else None)
            else:
                self.os.println("usage: grue [--check] <file.grue> [script.play]")
        elif cmd == "debug":
            if arg:
                self.os.sys_debug(arg)
            else:
                self.os.println("usage: debug <file.asm|file.bin>")
        elif cmd == "pi":
            self.os.sys_repl()
        elif cmd == "help":
            self.os.println("M56 SHELL COMMANDS")
            self.os.println()
            self.os.println("  ls [path]       list directory contents")
            self.os.println("  cd <path>       change directory")
            self.os.println("  mkdir <dir>     create a new directory")
            self.os.println("  cp <src> <dst>  copy a file")
            self.os.println("  cat <file>      print a file to the terminal")
            self.os.println("  edit <file>     open file in editor")
            self.os.println("  run <file.pi>              run a Pi program")
            self.os.println("  bat <file.bat>             run a batch script")
            self.os.println("  asm <file.asm> [out.bin]   assemble to binary")
            self.os.println("  debug <file.asm|.bin>      step debugger")
            self.os.println("  grue <file.grue>           run a Grue interactive fiction file")
            self.os.println("  grue --check <file.grue>   check syntax without running")
            self.os.println("  pi                         interactive Pi REPL")
            self.os.println("  help                       this message")
        elif cmd.endswith('.bat'):
            self._run_bat(cmd)
        else:
            self.os.println(f"unknown command: {cmd}")

    def _run_bat(self, path):
        try:
            data = self.os.fs.read_file(path)
        except Exception as e:
            self.os.println(f"bat: {e}")
            return
        for line in data.decode(errors='replace').splitlines():
            line = line.strip()
            if not line or line.startswith('//'):
                continue
            self.run_line(line)

    def complete(self, line):
        """Tab-complete line. Returns the completed line string, or None."""
        parts   = line.split()
        trailing = line.endswith(' ')

        # --- completing the command word ---
        if not parts or (len(parts) == 1 and not trailing):
            prefix  = parts[0] if parts else ''
            matches = sorted(c for c in self.COMMANDS if c.startswith(prefix))
            if not matches:
                return None
            common = _common_prefix(matches)
            return common + (' ' if len(matches) == 1 else '')

        # --- completing a path argument (always the last token) ---
        path_prefix = '' if trailing else parts[-1]

        if '/' in path_prefix:
            slash     = path_prefix.rfind('/')
            dir_part  = path_prefix[:slash] or '/'
            name_part = path_prefix[slash + 1:]
        else:
            dir_part  = None   # list cwd
            name_part = path_prefix

        try:
            entries = self.os.fs.ls(dir_part)
        except Exception:
            return None

        matches = [(n, t) for n, t, _ in entries if n.startswith(name_part)]
        if not matches:
            return None

        suffixed = [n + ('/' if t == 2 else '') for n, t in matches]
        common   = _common_prefix(suffixed)

        if dir_part is not None:
            sep   = '' if dir_part.endswith('/') else '/'
            token = dir_part + sep + common
        else:
            token = common

        if trailing:
            new_line = line + token
        else:
            before   = line[:len(line) - len(path_prefix)]
            new_line = before + token

        if len(matches) == 1 and not new_line.endswith('/'):
            new_line += ' '
        return new_line

    def _dots(self, n, delay=0.08):
        """Print n dots with a short pause between each."""
        import time
        for _ in range(n):
            self.os.print_text(".")
            time.sleep(delay)

    def loop(self):
        import time

        w = self.os.println
        p = self.os.print_text

        w()
        w("T46 TERMINAL  REV 2.1")
        w("UTRONIC DATA SYSTEMS INC.")
        w()
        time.sleep(0.3)

        p("SCANNING NETWORK FOR MAINFRAME NODE")
        self._dots(3, 0.4)
        self._dots(6, 0.12)
        w()
        time.sleep(0.2)

        p("M56 MAINFRAME FOUND  SN: 948-464")
        self._dots(3, 0.25)
        w()
        time.sleep(0.15)

        p("AUTHENTICATING")
        self._dots(4, 0.18)
        w("  OK")
        time.sleep(0.1)

        p("ESTABLISHING LINK")
        self._dots(4, 0.14)
        w("  CONNECTED")
        w()
        time.sleep(0.25)

        w("MEMORY TEST ............. 65536 BYTES OK")
        time.sleep(0.06)
        w("56FS .................... 512K ONLINE")
        time.sleep(0.06)
        w("TERMINAL LINK ........... T46 OK")
        w()
        time.sleep(0.2)
        w("SYSTEM READY.  Type help for commands.")
        w()
        self.os.sys_cd("/home")
        while self.os.terminal.running:
            self.prompt()
            line = self.os.read_line()
            if not self.os.terminal.running:
                break
            self.run_line(line)


class M56:
    def __init__(self, terminal):
        self.terminal = terminal
        self.memory   = Memory()
        self.io_bus   = IOBus()
        self.cpu      = CPU(self.memory, self.io_bus)
        self.fs       = FS56()
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

    def _run(self):
        if self._entry is not None:
            self.cpu.pc = self._entry
            while not self.cpu.halted:
                self.cpu.step()
        else:
            self.shell.loop()
