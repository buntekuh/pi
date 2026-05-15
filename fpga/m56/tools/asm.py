#!/usr/bin/env python3
"""
asm.py — two-pass assembler for the M56 CPU.

Instruction format (32 bits):
    bits 31..27  opcode   (5 bits)
    bits 26..24  mode     (3 bits)
    bits 23..20  register (4 bits)
    bits 19..0   imm20   (20 bits)

Usage:
    python3 asm.py firmware.s           — print address + word to stdout
    python3 asm.py firmware.s out.hex   — also write hex + VHDL package
"""

import sys

OPCODES = {
    'mov': 0, 'mvb': 1, 'add': 2, 'sub': 3, 'and': 4,
    'orr': 5, 'xor': 6, 'not': 7, 'shf': 8, 'sar': 9,
    'jmp': 10, 'jpr': 11, 'bra': 12, 'bar': 13,
    'wfi': 14, 'eai': 15, 'dai': 16, 'rti': 17,
}

# Instructions that take no operands — encoded with all fields zero.
ZERO_OPERAND = {'wfi', 'eai', 'dai', 'rti'}

COND = {'al': 0, 'z': 1, 'nz': 2, 'n': 3, 'nn': 4}


def reg(s):
    s = s.strip().upper()
    if not s.startswith('R'):
        raise ValueError(f"expected register, got '{s}'")
    return int(s[1:])


def imm(s):
    return int(s.strip().lstrip('#'), 0)


def resolve(s, symbols):
    """Resolve s to an integer: numeric literal, char literal 'x', or symbol name."""
    s = s.strip().lstrip('#')
    if len(s) == 3 and s[0] == "'" and s[2] == "'":
        return ord(s[1])
    try:
        return int(s, 0)
    except ValueError:
        if s in symbols:
            return symbols[s]
        raise ValueError(f"undefined symbol: {s!r}")


def encode(opcode, mode, r, imm20):
    return (opcode << 27) | (mode << 24) | (r << 20) | (imm20 & 0xFFFFF)


def clean(line):
    return line.split(';')[0].strip()


def split_ops(tail):
    return [o.strip() for o in tail.split(',')]


def expand_macros(lines):
    """Expand assembler macros into real instructions."""
    out = []
    for line in lines:
        if not line or line.endswith(':'):
            out.append(line)
            continue
        parts = line.split(None, 1)
        mn   = parts[0].lower()
        tail = parts[1].strip() if len(parts) > 1 else ''
        ops  = [o.strip() for o in tail.split(',')] if tail else []

        if mn == 'nop':
            out.append('add R0, #0')
        elif mn == 'clr':
            out.append(f'xor {ops[0]}, {ops[0]}')
        elif mn == 'inc':
            out.append(f'add {ops[0]}, #1')
        elif mn == 'dec':
            out.append(f'sub {ops[0]}, #1')
        elif mn == 'psh':
            out.append('sub R14, #4')
            out.append(f'mov {ops[0]}, [R14]')
        elif mn == 'pop':
            out.append(f'mov [R14], {ops[0]}')
            out.append('add R14, #4')
        elif mn == 'ret':
            out.append('rts')
        elif mn == 'cal':
            out.append(f'bra {tail}')
        elif mn == 'shl':
            out.append(f'shf {tail}')
        elif mn == 'shr':
            count = ops[1].lstrip('#')
            out.append(f'shf {ops[0]}, #-{count}')
        else:
            out.append(line)
    return out


def assemble(source):
    lines = [clean(l) for l in source.splitlines()]
    lines = expand_macros(lines)

    def str_chars(tail):
        """Return list of ints for a .str directive, including null terminator."""
        s = tail.strip()
        if s.startswith('"') and s.endswith('"'):
            s = s[1:-1]
        s = s.replace('\\r', '\r').replace('\\n', '\n').replace('\\t', '\t').replace('\\0', '\0')
        return [ord(c) for c in s] + [0]

    # Pass 1 — assign an address to every label
    symbols = {}
    pc = 0
    for line in lines:
        if not line:
            continue
        if line.endswith(':'):
            symbols[line[:-1]] = pc
            continue
        mn1 = line.split()[0].lower()
        if mn1 == '.str':
            pc += len(str_chars(line.split(None, 1)[1])) * 4
        else:
            pc += 4

    # Pass 2 — encode instructions
    words = []
    pc = 0
    for line in lines:
        if not line or line.endswith(':'):
            continue

        parts = line.split(None, 1)
        mn   = parts[0].lower()
        tail = parts[1] if len(parts) > 1 else ''
        ops  = split_ops(tail) if tail else []

        # --- pseudo-ops ---
        if mn == '.word':
            words.append(resolve(tail.strip(), symbols) & 0xFFFFFFFF)
            pc += 4
            continue
        if mn == '.str':
            for ch in str_chars(tail):
                words.append(ch)
                pc += 4
            continue

        # --- zero-operand: wfi, eai, dai, rti ---
        if mn in ZERO_OPERAND:
            words.append(encode(OPCODES[mn], 0, 0, 0))
            pc += 4
            continue

        # --- rts: return from subroutine (rti opcode, mode 1) ---
        if mn == 'rts':
            words.append(encode(17, 1, 0, 0))
            pc += 4
            continue

        # --- jpr[.cond] — relative goto ---
        if mn.startswith('jpr'):
            cond_name = mn.split('.')[1] if '.' in mn else 'al'
            cond  = COND[cond_name]
            if cond == 0:
                rcmp, label = 0, ops[0]
            else:
                rcmp, label = reg(ops[0]), ops[1]
            offset = symbols[label] - (pc + 4)
            words.append(encode(11, cond, rcmp, offset))
            pc += 4
            continue

        # --- bar[.cond] — relative call ---
        if mn.startswith('bar'):
            cond_name = mn.split('.')[1] if '.' in mn else 'al'
            cond  = COND[cond_name]
            if cond == 0:
                rcmp, label = 0, ops[0]
            else:
                rcmp, label = reg(ops[0]), ops[1]
            offset = symbols[label] - (pc + 4)
            words.append(encode(13, cond, rcmp, offset))
            pc += 4
            continue

        # --- jmp[.cond] — absolute goto ---
        if mn.startswith('jmp'):
            cond_name = mn.split('.')[1] if '.' in mn else 'al'
            cond  = COND[cond_name]
            if cond == 0:
                rcmp  = 0
                target = imm(ops[0]) if ops[0].startswith('#') else symbols[ops[0]]
            else:
                rcmp  = reg(ops[0])
                target = imm(ops[1]) if ops[1].startswith('#') else symbols[ops[1]]
            words.append(encode(10, cond, rcmp, target))
            pc += 4
            continue

        # --- bra[.cond] — absolute call ---
        if mn.startswith('bra'):
            cond_name = mn.split('.')[1] if '.' in mn else 'al'
            cond  = COND[cond_name]
            if cond == 0:
                rcmp  = 0
                target = imm(ops[0]) if ops[0].startswith('#') else symbols[ops[0]]
            else:
                rcmp  = reg(ops[0])
                target = imm(ops[1]) if ops[1].startswith('#') else symbols[ops[1]]
            words.append(encode(12, cond, rcmp, target))
            pc += 4
            continue

        # --- not Rsrc ---
        if mn == 'not':
            words.append(encode(OPCODES['not'], 0, reg(ops[0]), 0))
            pc += 4
            continue

        # --- shf Rsrc, #count  or  shf Rsrc, Rcnt ---
        if mn == 'shf':
            dst, src = ops[0], ops[1]
            if src.startswith('#') or src.lstrip('-+').isdigit():
                words.append(encode(OPCODES['shf'], 0, reg(dst), imm(src)))
            else:
                words.append(encode(OPCODES['shf'], 2, reg(dst), reg(src)))
            pc += 4
            continue

        # --- sar Rsrc, #count  or  sar Rsrc, Rcnt ---
        if mn == 'sar':
            dst, src = ops[0], ops[1]
            if src.startswith('#') or src.lstrip('-+').isdigit():
                words.append(encode(OPCODES['sar'], 0, reg(dst), imm(src)))
            else:
                words.append(encode(OPCODES['sar'], 2, reg(dst), reg(src)))
            pc += 4
            continue

        # --- mov-h #imm20, Rdst — load into bits 31..12 ---
        if mn == 'mov-h':
            words.append(encode(0, 1, reg(ops[1]), imm(ops[0])))
            pc += 4
            continue

        # --- mov (five forms) ---
        if mn == 'mov':
            src, dst = ops[0], ops[1]
            if src.startswith('#') or src.lstrip('-+').isdigit():
                words.append(encode(0, 0, reg(dst), resolve(src, symbols)))
            elif src.startswith('['):
                words.append(encode(0, 3, reg(src.strip('[]')), reg(dst)))
            elif dst.startswith('['):
                words.append(encode(0, 4, reg(src), reg(dst.strip('[]'))))
            else:
                words.append(encode(0, 2, reg(src), reg(dst)))
            pc += 4
            continue

        # --- mvb (byte move) ---
        if mn == 'mvb':
            src, dst = ops[0], ops[1]
            if src.startswith('['):
                words.append(encode(1, 3, reg(src.strip('[]')), reg(dst)))
            elif src.startswith('#') and dst.startswith('['):
                words.append(encode(1, 5, reg(dst.strip('[]')), imm(src)))
            elif dst.startswith('['):
                words.append(encode(1, 4, reg(src), reg(dst.strip('[]'))))
            else:
                raise ValueError(f"mvb requires indirect operand: {line!r}")
            pc += 4
            continue

        # --- ALU: add sub and orr xor (mode 0=immediate, mode 2=register) ---
        if mn in OPCODES:
            opc = OPCODES[mn]
            dst, src = ops[0], ops[1]
            if src.startswith('#') or src.lstrip('-+').isdigit():
                words.append(encode(opc, 0, reg(dst), imm(src)))
            else:
                words.append(encode(opc, 2, reg(dst), reg(src)))
            pc += 4
            continue

        raise ValueError(f"unknown mnemonic: {mn!r}  (line: {line!r})")

    return words


def vhdl_pkg(words, mem_words=57600):
    """VHDL package with sparse firmware initialisation for GHDL synth."""
    lines = [
        '-- firmware_pkg.vhd — generated by asm.py, do not edit',
        'library IEEE;',
        'use IEEE.STD_LOGIC_1164.ALL;',
        '',
        'package firmware_pkg is',
        f'    constant MEM_WORDS : integer := {mem_words};',
        f'    type bram_init_t is array(0 to MEM_WORDS-1) of std_logic_vector(31 downto 0);',
        '    constant FIRMWARE : bram_init_t := (',
    ]
    for i, w in enumerate(words):
        lines.append(f'        {i} => x"{w:08X}",')
    lines += [
        '        others => x"00000000"',
        '    );',
        'end package firmware_pkg;',
        '',
    ]
    return '\n'.join(lines)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(f'usage: {sys.argv[0]} input.s [output.hex]')

    with open(sys.argv[1]) as f:
        words = assemble(f.read())

    hex_lines = [f'{w:08X}' for w in words]

    if len(sys.argv) >= 3:
        base = sys.argv[2].removesuffix('.hex')
        with open(sys.argv[2], 'w') as f:
            f.write('\n'.join(hex_lines) + '\n')
        pkg_path = base + '_pkg.vhd'
        with open(pkg_path, 'w') as f:
            f.write(vhdl_pkg(words))
        print(f'wrote {len(words)} words → {sys.argv[2]}  and  {pkg_path}')

    for i, (w, h) in enumerate(zip(words, hex_lines)):
        print(f'0x{i*4:04X}  {h}')
