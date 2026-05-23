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
    'bra': 10, 'bar': 11, 'cal': 12, 'car': 13,
    'wfi': 14, 'eai': 15, 'dai': 16,
    'iba': 18, 'ica': 19, 'stk': 20,
}

# Instructions that take no operands — encoded with all fields zero.
ZERO_OPERAND = {'wfi', 'eai', 'dai'}

COND = {'al': 0, 'z': 1, 'nz': 2, 'n': 3, 'nn': 4, 'c': 5, 'nc': 6}


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
            out.append(f'stk.u {ops[0]}')
        elif mn == 'pop':
            out.append(f'stk.o {ops[0]}')
        elif mn == 'ret':
            out.append('ret.s')
        elif mn == 'shl':
            out.append(f'shf {tail}')
        elif mn == 'shr':
            count = ops[1].lstrip('#')
            out.append(f'shf {ops[0]}, #-{count}')
        elif mn in ('mul', 'div', 'mod'):
            # T-code pseudo-ops: expand to argument setup + cal _<op>.
            # Calling convention: R0 = first arg / result, R1 = second arg.
            # Supports: Rdst, Rsrc  or  Rdst, #imm
            fn   = '_' + mn
            rdst = ops[0].strip().upper()
            rsrc = ops[1].strip()
            rimm = rsrc.startswith('#') or rsrc.lstrip('-+').replace('#','').isdigit()
            rsrc_u = rsrc.upper()
            if rimm:
                # immediate second operand: load into R1 first
                if rdst != 'R0':
                    out.append(f'mov {ops[0]}, R0')
                out.append(f'mov {rsrc}, R1')
                out.append(f'cal {fn}')
                if rdst != 'R0':
                    out.append(f'mov R0, {ops[0]}')
            elif rsrc_u == 'R0' and rdst != 'R0':
                # src is R0 and dst is not — moving dst to R0 would clobber src;
                # use R2 (caller-saved scratch) to shuttle the original R0 into R1.
                out.append(f'mov R0, R2')
                out.append(f'mov {ops[0]}, R0')
                out.append(f'mov R2, R1')
                out.append(f'cal {fn}')
                out.append(f'mov R0, {ops[0]}')
            else:
                if rdst != 'R0':
                    out.append(f'mov {ops[0]}, R0')
                if rsrc_u != 'R1':
                    out.append(f'mov {rsrc}, R1')
                out.append(f'cal {fn}')
                if rdst != 'R0':
                    out.append(f'mov R0, {ops[0]}')
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

    # Pass 1 — assign an address to every label; resolve .equ constants
    symbols = {}
    pc = 0
    for line in lines:
        if not line:
            continue
        if line.endswith(':'):
            symbols[line[:-1]] = pc
            continue
        if '=' in line and not line.startswith('.'):
            name, _, val = line.partition('=')
            symbols[name.strip()] = int(val.strip(), 0)
            continue
        mn1 = line.split()[0].lower()
        if mn1 == '.equ':
            _, rest = line.split(None, 1)
            name, _, val = rest.partition(',')
            symbols[name.strip()] = int(val.strip(), 0)
            continue
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
        if '=' in line and not line.startswith('.'):
            continue
        if line.split()[0].lower() == '.equ':
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

        # --- ret.s / ret.i — return from subroutine or interrupt ---
        if mn.startswith('ret'):
            suffix = mn.split('.')[1] if '.' in mn else 's'
            mode = 0 if suffix == 'i' else 1
            words.append(encode(17, mode, 0, 0))
            pc += 4
            continue

        # --- stk.u / stk.o — stack push / pop ---
        if mn.startswith('stk'):
            suffix = mn.split('.')[1] if '.' in mn else None
            if suffix == 'u':
                words.append(encode(20, 0, reg(ops[0]), 0))
            elif suffix == 'o':
                words.append(encode(20, 1, reg(ops[0]), 0))
            else:
                raise ValueError(f"stk requires .u or .o suffix: {line!r}")
            pc += 4
            continue

        # --- bar[.cond] — relative goto ---
        if mn.startswith('bar'):
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

        # --- car[.cond] — relative call ---
        if mn.startswith('car'):
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

        # --- bra[.cond] — absolute goto ---
        if mn.startswith('bra'):
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

        # --- cal[.cond] — absolute call ---
        if mn.startswith('cal'):
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

        # --- iba[.cond] — indirect goto via register ---
        # Syntax: iba Rtarget  or  iba.cond Rcmp, Rtarget
        if mn.startswith('iba'):
            cond_name = mn.split('.')[1] if '.' in mn else 'al'
            cond = COND[cond_name]
            if cond == 0:
                rcmp, rtgt = 0, reg(ops[0])
            else:
                rcmp, rtgt = reg(ops[0]), reg(ops[1])
            words.append(encode(18, cond, rcmp, rtgt << 16))
            pc += 4
            continue

        # --- ica[.cond] — indirect call via register ---
        # Syntax: ica Rtarget  or  ica.cond Rcmp, Rtarget
        if mn.startswith('ica'):
            cond_name = mn.split('.')[1] if '.' in mn else 'al'
            cond = COND[cond_name]
            if cond == 0:
                rcmp, rtgt = 0, reg(ops[0])
            else:
                rcmp, rtgt = reg(ops[0]), reg(ops[1])
            words.append(encode(19, cond, rcmp, rtgt << 16))
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
        # Accepts either the pre-shifted value (#0x400) or a full address
        # (uart_reg = 0x400000): values > 20 bits are right-shifted by 12.
        if mn == 'mov-h':
            val = resolve(ops[0], symbols)
            if val > 0xFFFFF:
                val >>= 12
            words.append(encode(0, 1, reg(ops[1]), val))
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
                words.append(encode(opc, 0, reg(dst), resolve(src, symbols)))
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
    import argparse
    ap = argparse.ArgumentParser(description='M56 assembler')
    ap.add_argument('--mem-words', type=int, default=57600,
                    help='firmware_pkg.vhd array size (must match BLOCK_RAM_WORDS)')
    # Convention: last positional is the .hex output; all others are .s inputs
    ap.add_argument('files', nargs='+', help='input.s [input2.s ...] output.hex')
    args = ap.parse_args()

    if len(args.files) < 2:
        ap.error('provide at least one .s input and one .hex output')

    input_paths = args.files[:-1]
    output_path = args.files[-1]

    src = ''
    for path in input_paths:
        with open(path) as f:
            src += f.read() + '\n'
    words = assemble(src)

    hex_lines = [f'{w:08X}' for w in words]

    base = output_path.removesuffix('.hex')
    with open(output_path, 'w') as f:
        f.write('\n'.join(hex_lines) + '\n')
    pkg_path = base + '_pkg.vhd'
    with open(pkg_path, 'w') as f:
        f.write(vhdl_pkg(words, mem_words=args.mem_words))
    print(f'wrote {len(words)} words → {output_path}  and  {pkg_path}')

    for i, (w, h) in enumerate(zip(words, hex_lines)):
        print(f'0x{i*4:04X}  {h}')
