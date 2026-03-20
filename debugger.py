"""
M56 Debugger

Loads an assembly file, assembles it into M56 memory, and provides
an interactive step-through interface in the terminal.

Commands:
  s / step          — execute one instruction
  r / run           — run until halt or breakpoint
  b / break <addr>  — toggle breakpoint at address (hex)
  m / mem <addr>    — dump 64 bytes of memory from address (hex)
  p / print         — print all registers
  q / quit          — exit

Usage:
  python3 debugger.py program.asm [--load-addr 0x8000]
"""

import sys
import argparse
import readline  # noqa: F401 — enables arrow-key history in input()

from m56 import (
    M56, Memory, CPU, USERRAM_START,
    FLAGS_ZERO, FLAGS_CARRY, FLAGS_OVERFLOW, FLAGS_NEGATIVE,
)
from assembler import assemble, disassemble_word, AssemblerError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def flag_str(flags):
    return "".join([
        'Z' if flags & FLAGS_ZERO     else '-',
        'C' if flags & FLAGS_CARRY    else '-',
        'V' if flags & FLAGS_OVERFLOW else '-',
        'N' if flags & FLAGS_NEGATIVE else '-',
    ])


STACK_DEPTH = 6   # how many stack entries to show

def print_regs(cpu):
    f = cpu.flags
    print(f"  PC={cpu.pc:05X}  SP={cpu.sp:04X}  FLAGS={f:02X} [{flag_str(f)}]")
    for row in range(2):
        parts = []
        for col in range(4):
            i = row * 4 + col
            parts.append(f"R{i}={cpu.get_reg(f'R{i}'):04X}")
        print("  " + "  ".join(parts))
    # Stack: top few entries from SP upward
    stack_vals = []
    sp = cpu.sp
    for i in range(STACK_DEPTH):
        addr = (sp + i * 2) & 0xFFFF
        val  = cpu.mem.read16(addr)
        stack_vals.append(f"{val:04X}")
    top_marker = "<- SP" if stack_vals else ""
    print(f"  stack [{', '.join(stack_vals)}]  {top_marker}")


def print_mem(mem, addr, count=64):
    addr = addr & ~0xF   # align to 16
    for row in range(0, count, 16):
        a = addr + row
        raw = [mem.read8(a + i) for i in range(16)]
        hex_part  = " ".join(f"{b:02X}" for b in raw)
        char_part = "".join(chr(b) if 32 <= b < 127 else '.' for b in raw)
        print(f"  {a:05X}  {hex_part}  {char_part}")


def print_instruction(cpu, mem, listing_map):
    pc   = cpu.pc
    # fetch without advancing PC
    b0 = mem.read8(pc)
    b1 = mem.read8(pc + 1)
    b2 = mem.read8(pc + 2)
    word = b0 | (b1 << 8) | (b2 << 16)
    asm  = disassemble_word(word)
    src  = listing_map.get(pc, "")
    print(f"  {pc:05X}: {b0:02X} {b1:02X} {b2:02X}  {asm:<30}  ; {src}")


# ---------------------------------------------------------------------------
# Debugger
# ---------------------------------------------------------------------------

class Debugger:
    def __init__(self, cpu, mem, load_addr, listing, labels):
        self.cpu        = cpu
        self.mem        = mem
        self.load_addr  = load_addr
        self.breakpoints= set()
        self.labels     = labels
        # Map address → source line
        self.listing_map = {addr: src for addr, _, src in listing}
        self.last_cmd   = 's'

    def _step_one(self):
        if self.cpu.halted:
            print("  CPU halted.")
            return False
        self.cpu.step()
        return True

    def _run(self):
        count = 0
        while True:
            if self.cpu.halted:
                print(f"  CPU halted after {count} instructions.")
                break
            pc = self.cpu.pc
            self.cpu.step()
            count += 1
            if self.cpu.pc in self.breakpoints:
                print(f"  Breakpoint hit at {self.cpu.pc:05X} after {count} instructions.")
                break
            if count > 1_000_000:
                print("  Runaway — stopped after 1M instructions.")
                break

    def loop(self):
        print()
        print("M56 Debugger  —  ? for help")
        print_regs(self.cpu)
        print()
        print_instruction(self.cpu, self.mem, self.listing_map)
        print()

        while True:
            try:
                line = input("(dbg) ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not line:
                line = self.last_cmd
            self.last_cmd = line

            parts = line.split()
            cmd   = parts[0].lower() if parts else ''
            rest  = parts[1:]

            if cmd in ('q', 'quit', 'exit'):
                break

            elif cmd in ('?', 'h', 'help'):
                print("  s / step         — step one instruction")
                print("  r / run          — run until halt or breakpoint")
                print("  b / break <hex>  — toggle breakpoint")
                print("  m / mem <hex>    — dump memory at address")
                print("  p / print        — print registers")
                print("  l / list         — show listing around PC")
                print("  q / quit         — exit")

            elif cmd in ('s', 'step'):
                if self._step_one():
                    print_regs(self.cpu)
                    print()
                    print_instruction(self.cpu, self.mem, self.listing_map)

            elif cmd in ('r', 'run'):
                self._run()
                print_regs(self.cpu)
                print()
                print_instruction(self.cpu, self.mem, self.listing_map)

            elif cmd in ('b', 'break'):
                if not rest:
                    if self.breakpoints:
                        print("  Breakpoints: " + ", ".join(f"0x{a:05X}" for a in sorted(self.breakpoints)))
                    else:
                        print("  No breakpoints.")
                else:
                    try:
                        addr = int(rest[0], 16)
                    except ValueError:
                        # try label
                        name = rest[0].upper()
                        if name in self.labels:
                            addr = self.labels[name]
                        else:
                            print(f"  bad address: {rest[0]!r}")
                            continue
                    if addr in self.breakpoints:
                        self.breakpoints.discard(addr)
                        print(f"  Breakpoint cleared at 0x{addr:05X}")
                    else:
                        self.breakpoints.add(addr)
                        print(f"  Breakpoint set at 0x{addr:05X}")

            elif cmd in ('m', 'mem'):
                addr = int(rest[0], 16) if rest else self.load_addr
                print_mem(self.mem, addr)

            elif cmd in ('p', 'print', 'regs'):
                print_regs(self.cpu)

            elif cmd in ('l', 'list'):
                pc = self.cpu.pc
                # show a window of instructions around PC
                start = max(self.load_addr, pc - 9)
                for a in range(start, pc + 12, 3):
                    b0 = self.mem.read8(a)
                    b1 = self.mem.read8(a + 1)
                    b2 = self.mem.read8(a + 2)
                    word = b0 | (b1 << 8) | (b2 << 16)
                    asm  = disassemble_word(word)
                    src  = self.listing_map.get(a, "")
                    mark = ">>>" if a == pc else "   "
                    print(f"  {mark} {a:05X}: {b0:02X}{b1:02X}{b2:02X}  {asm:<30}  {src}")

            else:
                print(f"  unknown command: {cmd!r}  (? for help)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='M56 Debugger')
    parser.add_argument('input', help='assembly source file')
    parser.add_argument('--load-addr', default='0x8000',
                        help='load address (default: 0x8000)')
    args = parser.parse_args()

    load_addr = int(args.load_addr, 0)

    path = args.input
    if path.endswith('.bin') or path.endswith('.o'):
        with open(path, 'rb') as f:
            code = f.read()
        labels  = {}
        listing = [(load_addr + i, code[i:i+3], '') for i in range(0, len(code), 3)]
        print(f"Loaded {len(code)} bytes at 0x{load_addr:05X}")
    else:
        with open(path) as f:
            source = f.read()
        try:
            code, labels, listing = assemble(source, load_addr)
        except AssemblerError as e:
            print(f"assembler error: {e}", file=sys.stderr)
            sys.exit(1)
        print(f"Assembled {len(code)} bytes at 0x{load_addr:05X}")
        if labels:
            label_strs = [f"{n}=0x{a:05X}" for n, a in sorted(labels.items(), key=lambda x: x[1])]
            print("Labels: " + ", ".join(label_strs))

    # Build a standalone CPU+memory (no terminal needed)
    mem = Memory()
    mem.write_bytes(load_addr, code)

    cpu = CPU(mem)
    cpu.reset()
    cpu.pc = load_addr
    cpu.sp = load_addr - 2   # stack just below code

    dbg = Debugger(cpu, mem, load_addr, listing, labels)
    dbg.loop()


if __name__ == '__main__':
    main()
