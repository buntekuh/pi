#!/usr/bin/env python3
"""
asm.py — two-pass assembler for the M56 CPU.

Handles the subset required for firmware/echo.s.
To be replaced by a self-hosted M56 assembler once the runtime exists.

Usage:
    python3 asm.py echo.s           — print address + word to stdout
    python3 asm.py echo.s echo.hex  — also write hex file (one word per line)
"""

import sys

OPCODES = {
    'mov': 0, 'mvb': 1, 'add': 2, 'sub': 3, 'and': 4,
    'orr': 5, 'xor': 6, 'not': 7, 'shf': 8, 'sar': 9,
    'jmp': 10, 'jpr': 11, 'wfi': 12, 'eai': 13, 'dai': 14, 'rti': 15,
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


def encode(opcode, mode, r, imm19):
    return (opcode << 27) | (mode << 23) | (r << 19) | (imm19 & 0x7FFFF)


def clean(line):
    return line.split(';')[0].strip()


def split_ops(tail):
    return [o.strip() for o in tail.split(',')]


def expand_macros(lines):
    """Expand assembler macros into real instructions.

    Multi-instruction macros (psh, pop, ret) produce multiple output lines.
    All other macros produce exactly one line.
    Labels and blank lines pass through unchanged.
    """
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
            out.append('mov [R14], R15')
            out.append('add R14, #4')
        elif mn == 'cal':
            out.append(f'jmp-s {tail}')
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

    # Pass 1 — assign an address to every label
    symbols = {}
    pc = 0
    for line in lines:
        if not line:
            continue
        if line.endswith(':'):
            symbols[line[:-1]] = pc
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

        # --- zero-operand instructions: wfi, eai, dai, rti ---
        if mn in ZERO_OPERAND:
            words.append(encode(OPCODES[mn], 0, 0, 0))
            pc += 4
            continue

        # --- jpr[.cond] and jpr-s[.cond] ---
        if mn.startswith('jpr'):
            sub   = 1 if '-s' in mn else 0
            parts = mn.replace('-s', '').split('.')
            cond_name = parts[1] if len(parts) > 1 else 'al'
            cond  = COND[cond_name]
            mode  = (sub << 3) | cond        # bit 3 = subroutine flag
            if cond == 0:
                rcmp  = 0
                label = ops[0]
            else:
                rcmp  = reg(ops[0])
                label = ops[1]
            offset = symbols[label] - (pc + 4)
            words.append(encode(11, mode, rcmp, offset))
            pc += 4
            continue

        # --- jmp[.cond] and jmp-s[.cond] ---
        if mn.startswith('jmp'):
            sub   = 1 if '-s' in mn else 0
            parts = mn.replace('-s', '').split('.')
            cond_name = parts[1] if len(parts) > 1 else 'al'
            cond  = COND[cond_name]
            mode  = (sub << 3) | cond
            if cond == 0:
                rcmp  = 0
                target = imm(ops[0]) if ops[0].startswith('#') else symbols[ops[0]]
            else:
                rcmp  = reg(ops[0])
                target = imm(ops[1]) if ops[1].startswith('#') else symbols[ops[1]]
            words.append(encode(10, mode, rcmp, target))
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

        # --- mov-h #imm, Rdst ---
        if mn == 'mov-h':
            words.append(encode(0, 1, reg(ops[1]), imm(ops[0])))
            pc += 4
            continue

        # --- mov (five forms) ---
        if mn == 'mov':
            src, dst = ops[0], ops[1]
            if src.startswith('#') or src.lstrip('-+').isdigit():  # mov #imm, Rdst
                words.append(encode(0, 0, reg(dst), imm(src)))
            elif src.startswith('['):                               # mov [Rsrc], Rdst
                words.append(encode(0, 3, reg(src.strip('[]')), reg(dst)))
            elif dst.startswith('['):                               # mov Rsrc, [Rdst]
                words.append(encode(0, 4, reg(src), reg(dst.strip('[]'))))
            else:                                                   # mov Rsrc, Rdst
                words.append(encode(0, 2, reg(src), reg(dst)))
            pc += 4
            continue

        # --- mvb (byte move) ---
        if mn == 'mvb':
            src, dst = ops[0], ops[1]
            if src.startswith('['):                                 # mvb [Rsrc], Rdst
                words.append(encode(1, 3, reg(src.strip('[]')), reg(dst)))
            elif src.startswith('#') and dst.startswith('['):      # mvb #imm, [Rdst]
                words.append(encode(1, 5, reg(dst.strip('[]')), imm(src)))
            elif dst.startswith('['):                               # mvb Rsrc, [Rdst]
                words.append(encode(1, 4, reg(src), reg(dst.strip('[]'))))
            else:
                raise ValueError(f"mvb requires indirect operand: {line!r}")
            pc += 4
            continue

        # --- ALU: add sub and orr xor (mode 0 = immediate, mode 2 = register) ---
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


def vhdl_pkg(words, mem_words=1024):
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
