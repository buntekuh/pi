"""
M56 Assembler

Converts M56 assembly text into 24-bit machine code.

Instruction format (24-bit):
  23..19  opcode (5 bits)
  18..16  rs     (3 bits)
  15..13  rd     (3 bits)
  12..0   imm13  (13 bits)

Usage:
  python3 assembler.py input.asm output.bin [--load-addr 0x8000]
  python3 assembler.py input.asm            (prints hex dump)
"""

import re
import sys

from m56 import (
    OP_LOAD, OP_ADD,  OP_SUB,  OP_AND,  OP_OR,  OP_XOR,
    OP_NOT,  OP_SFT,  OP_SAR,  OP_MUL,  OP_DIV, OP_SWP,
    OP_JMP,  OP_CAL,  OP_RET,  OP_PUSH, OP_POP, OP_NOP, OP_HALT,
    OP_OUT,  OP_IN,
    PORT_T46_CMD, PORT_T46_ARG0, PORT_T46_ARG1, PORT_T46_ARG2,
    PORT_T46_ARG3, PORT_T46_KEY,
    T46_CMD_CLS, T46_CMD_PRINT, T46_CMD_PEN, T46_CMD_PLOT,
    T46_CMD_LINE, T46_CMD_FILL,  T46_CMD_RECT, T46_CMD_MODE,
    LOAD_IMM, LOAD_RR, LOAD_IND_R, LOAD_IND_W,
    LOAD_IDX_R, LOAD_IDX_W, LOAD_PCREL,
    COND_Z, COND_NZ, COND_C, COND_NC,
    COND_N, COND_NN, COND_V, COND_AL,
    USERRAM_START,
)

# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

CONDITIONS = {
    'Z': COND_Z,   'NZ': COND_NZ, 'C':  COND_C,  'NC': COND_NC,
    'N': COND_N,   'NN': COND_NN, 'V':  COND_V,  'AL': COND_AL,
}

REGISTERS = {f'R{i}': i for i in range(8)}


# ---------------------------------------------------------------------------
# Encoding helpers
# ---------------------------------------------------------------------------

def encode(opcode, rs, rd, imm13):
    word = ((opcode & 0x1F) << 19) | ((rs & 0x7) << 16) | ((rd & 0x7) << 13) | (imm13 & 0x1FFF)
    return bytes([word & 0xFF, (word >> 8) & 0xFF, (word >> 16) & 0xFF])


def disassemble_word(word):
    """Turn a 24-bit integer back into a human-readable string."""
    opcode = (word >> 19) & 0x1F
    rs     = (word >> 16) & 0x07
    rd     = (word >> 13) & 0x07
    imm13  = word & 0x1FFF

    name = {
        OP_LOAD: 'LOAD', OP_ADD:  'ADD',  OP_SUB:  'SUB', OP_AND: 'AND',
        OP_OR:   'OR',   OP_XOR:  'XOR',  OP_NOT:  'NOT', OP_SFT: 'SFT',
        OP_SAR:  'SAR',  OP_MUL:  'MUL',  OP_DIV:  'DIV', OP_SWP: 'SWP',
        OP_JMP:  'JMP',  OP_CAL:  'CAL',  OP_RET:  'RET', OP_PUSH:'PUSH',
        OP_POP:  'POP',  OP_NOP:  'NOP',  OP_HALT: 'HALT',
        OP_OUT:  'OUT',  OP_IN:   'IN',
    }.get(opcode, f'???({opcode})')

    cond_name = {v: k for k, v in CONDITIONS.items()}

    if opcode == OP_NOP:
        return 'NOP'
    if opcode == OP_HALT:
        return 'HALT'
    if opcode == OP_OUT:
        return f'OUT #{imm13 & 0xFF}, R{rs}'
    if opcode == OP_IN:
        return f'IN R{rd}, #{imm13 & 0xFF}'

    if opcode == OP_LOAD:
        mode = rs
        if mode == LOAD_IMM:
            return f'LOAD #{imm13}, R{rd}'
        elif mode == LOAD_RR:
            return f'LOAD R{imm13 & 7}, R{rd}'
        elif mode == LOAD_IND_R:
            return f'LOAD [R{imm13 & 7}], R{rd}'
        elif mode == LOAD_IND_W:
            return f'LOAD R{rd}, [R{imm13 & 7}]'
        elif mode == LOAD_IDX_R:
            base = (imm13 >> 10) & 7
            off  = imm13 & 0x3FF
            return f'LOAD [R{base}+{off}], R{rd}'
        elif mode == LOAD_IDX_W:
            base = (imm13 >> 10) & 7
            off  = imm13 & 0x3FF
            return f'LOAD R{rd}, [R{base}+{off}]'
        elif mode == LOAD_PCREL:
            return f'LOAD [PC+{imm13}], R{rd}'

    if opcode in (OP_ADD, OP_SUB, OP_AND, OP_OR, OP_XOR, OP_MUL, OP_DIV):
        if imm13 & 0x1000:
            src = f'#{imm13 & 0xFFF}'
        else:
            src = f'R{rs}'
        return f'{name} {src}, R{rd}'

    if opcode == OP_NOT:
        return f'NOT R{rd}'
    if opcode == OP_SFT:
        n = imm13 & 0xF
        if n & 8: n -= 16
        return f'SFT R{rd}, #{n}'
    if opcode == OP_SAR:
        return f'SAR R{rd}, #{imm13 & 0xF}'
    if opcode == OP_SWP:
        return f'SWP R{rd}'
    if opcode == OP_PUSH:
        return f'PUSH R{rd}'
    if opcode == OP_POP:
        return f'POP R{rd}'

    if opcode in (OP_JMP, OP_CAL):
        cond = cond_name.get(rs, f'?{rs}')
        if rd != 0:
            target = f'R{rd}'
        else:
            offset = imm13 if not (imm13 & 0x1000) else imm13 - 0x2000
            target = f'PC{offset:+d}'
        return f'{name} {cond}, {target}'
    if opcode == OP_RET:
        cond = cond_name.get(rs, f'?{rs}')
        return f'RET {cond}'

    return f'{name} rs={rs} rd={rd} imm={imm13}'


# ---------------------------------------------------------------------------
# Tokeniser
# ---------------------------------------------------------------------------

def tokenise(line):
    """Strip comments, return list of tokens (upper-cased mnemonics)."""
    line = line.split(';')[0].strip()
    # Split on commas and whitespace, keep brackets attached
    tokens = re.split(r'[,\s]+', line)
    return [t for t in tokens if t]


# ---------------------------------------------------------------------------
# Operand parsers
# ---------------------------------------------------------------------------

def parse_reg(tok):
    """Parse 'R0'..'R7' → 0..7, or raise."""
    t = tok.upper()
    if t not in REGISTERS:
        raise ValueError(f"expected register, got {tok!r}")
    return REGISTERS[t]


def parse_imm(tok, labels, pc):
    """Parse an immediate: #42, #0xFF, label name, or bare integer."""
    t = tok.lstrip('#')
    if t.upper() in labels:
        return labels[t.upper()]
    try:
        return int(t, 0)
    except ValueError:
        raise ValueError(f"unknown immediate or label: {tok!r}")


def parse_cond(tok):
    t = tok.upper()
    if t not in CONDITIONS:
        raise ValueError(f"unknown condition: {tok!r}")
    return CONDITIONS[t]


def parse_indexed(tok):
    """
    Parse '[Rs+off]' or '[Rs]' or '[PC+off]'.
    Returns (base_str, offset_int).
    base_str is 'PC' or 'R0'..'R7'.
    """
    m = re.match(r'^\[(\w+)(?:\+(\d+))?\]$', tok, re.IGNORECASE)
    if not m:
        raise ValueError(f"invalid indirect operand: {tok!r}")
    base = m.group(1).upper()
    off  = int(m.group(2)) if m.group(2) else 0
    return base, off


def _db_bytes(args_str, labels=None):
    """
    Parse the argument portion of a .DB directive and return bytes.

    Handles:
      "hello", 0          → b'hello\x00'
      'A', 0x0D, 10       → b'A\r\n'
      42                  → b'\x2a'
    """
    result = bytearray()
    # Tokenize: keep quoted strings intact, split rest on commas
    tokens = []
    remaining = args_str.strip()
    while remaining:
        remaining = remaining.lstrip()
        if not remaining:
            break
        if remaining[0] in ('"', "'"):
            q = remaining[0]
            end = remaining.find(q, 1)
            if end == -1:
                raise AssemblerError(f"unterminated string in .DB: {args_str}")
            tokens.append(remaining[1:end])
            remaining = remaining[end+1:].lstrip().lstrip(',')
        else:
            part, _, remaining = remaining.partition(',')
            tokens.append(part.strip())

    for tok in tokens:
        if not tok:
            continue
        # Multi-char: it came from a quoted string
        if len(tok) > 1 and not tok.startswith('0'):
            for ch in tok:
                result.append(ord(ch))
        else:
            # numeric or label
            try:
                val = int(tok, 0)
            except ValueError:
                val = (labels or {}).get(tok.upper(), 0)
            result.append(val & 0xFF)
    return bytes(result)


# ---------------------------------------------------------------------------
# Assembler passes
# ---------------------------------------------------------------------------

class AssemblerError(Exception):
    def __init__(self, msg, lineno=None):
        self.lineno = lineno
        super().__init__(f"line {lineno}: {msg}" if lineno else msg)


def assemble(source, load_addr=USERRAM_START):
    """
    Two-pass assembly.

    Returns (bytes_out, labels, listing) where:
      bytes_out — the raw machine code
      labels    — dict of label → address
      listing   — list of (addr, bytes3, source_line) tuples
    """
    lines  = source.splitlines()
    labels = {}
    listing = []

    # --- Pass 1: collect labels, measure size ---
    addr = load_addr
    sizes = []   # size (bytes) for each non-empty, non-label line
    pending = []  # (lineno, addr, tokens) for pass 2

    for lineno, raw in enumerate(lines, 1):
        clean = raw.split(';')[0].strip()
        if not clean:
            continue
        # Label definition
        if clean.endswith(':'):
            label = clean[:-1].upper()
            labels[label] = addr
            continue
        # Label+instruction on same line: "loop: NOP"
        if ':' in clean:
            label_part, rest = clean.split(':', 1)
            labels[label_part.strip().upper()] = addr
            clean = rest.strip()
            if not clean:
                continue

        toks = re.split(r'[,\s]+', clean)
        toks = [t for t in toks if t]
        mnemonic = toks[0].upper()

        # Constant definition:  NAME = value
        if '=' in clean and not clean.startswith('.'):
            name, _, val = clean.partition('=')
            labels[name.strip().upper()] = int(val.strip(), 0)
            continue

        # Directives
        if mnemonic == '.EQU':
            labels[toks[1].upper()] = int(toks[2], 0)
            continue
        if mnemonic == '.ORG':
            addr = int(toks[1], 0)
            continue
        if mnemonic == '.DW':   # define word (2 bytes)
            sizes.append(2)
            pending.append((lineno, addr, toks, raw))
            addr += 2
            continue
        if mnemonic == '.DB':
            args_str = clean[len('.DB'):].strip()
            n = len(_db_bytes(args_str))
            sizes.append(n)
            pending.append((lineno, addr, toks, raw))
            addr += n
            continue
        if mnemonic == '.DS':   # define space: reserve N zero bytes
            n = int(toks[1], 0)
            sizes.append(n)
            pending.append((lineno, addr, toks, raw))
            addr += n
            continue

        # LA Rd, label — load 16-bit address, expands to 3 instructions (9 bytes)
        if mnemonic == 'LA':
            sizes.append(9)
            pending.append((lineno, addr, toks, raw))
            addr += 9
            continue

        sizes.append(3)
        pending.append((lineno, addr, toks, raw))
        addr += 3

    # --- Pass 2: emit machine code ---
    output = bytearray()

    for (lineno, iaddr, toks, raw) in pending:
        mnemonic = toks[0].upper()
        args     = toks[1:]

        try:
            data = _emit(mnemonic, args, labels, iaddr, raw)
        except (ValueError, IndexError) as e:
            raise AssemblerError(str(e), lineno)

        listing.append((iaddr, bytes(data), raw.strip()))
        output += data

    return bytes(output), labels, listing


def _emit(mnemonic, args, labels, pc, raw=''):
    """Return 3 bytes for one instruction (or 1/2 for directives)."""

    def imm(tok):
        return parse_imm(tok, labels, pc)

    def reg(tok):
        return parse_reg(tok)

    if mnemonic == '.DW':
        val = imm(args[0]) & 0xFFFF
        return bytes([val & 0xFF, (val >> 8) & 0xFF])

    if mnemonic == '.DB':
        args_str = raw.split(';')[0].strip()[len('.DB'):].strip()
        return _db_bytes(args_str, labels)

    if mnemonic == '.DS':
        return bytes(int(args[0], 0))

    if mnemonic == 'NOP':
        return encode(OP_NOP, 0, 0, 0)

    if mnemonic == 'HALT':
        return encode(OP_HALT, 0, 0, 0)

    # LA Rd, value — load any 16-bit address into register (9 bytes)
    #   LOAD #(val >> 8), Rd   — high byte into low position
    #   SWP  Rd                — swap bytes → high byte in high position
    #   OR   #(val & 0xFF), Rd — OR in low byte
    if mnemonic == 'LA':
        rd  = reg(args[0])
        val = imm(args[1]) & 0xFFFF
        hi  = (val >> 8) & 0xFF
        lo  = val & 0xFF
        return (encode(OP_LOAD, LOAD_IMM, rd, hi) +
                encode(OP_SWP,  0,        rd, 0)  +
                encode(OP_OR,   0,        rd, 0x1000 | lo))

    # OUT #port, Rs  — rs=source register, imm13=port
    if mnemonic == 'OUT':
        port = imm(args[0]) & 0xFF
        rs   = reg(args[1])
        return encode(OP_OUT, rs, 0, port)

    # IN Rd, #port  — rd=dest register, imm13=port
    if mnemonic == 'IN':
        rd   = reg(args[0])
        port = imm(args[1]) & 0xFF
        return encode(OP_IN, 0, rd, port)

    # ---- LOAD ----
    if mnemonic == 'LOAD':
        src, dst = args[0], args[1]
        dst_up = dst.upper()
        src_up = src.upper()

        # LOAD #imm, Rd
        if src.startswith('#') or (src_up not in REGISTERS and '[' not in src_up and src_up not in ('PC',)):
            rd  = reg(dst)
            val = imm(src)
            if val > 0x1FFF:
                raise ValueError(
                    f"immediate 0x{val:X} exceeds 13-bit range — use LA for addresses")
            return encode(OP_LOAD, LOAD_IMM, rd, val)

        # LOAD [PC+off], Rd
        if src_up.startswith('[PC'):
            base, off = parse_indexed(src)
            rd = reg(dst)
            return encode(OP_LOAD, LOAD_PCREL, rd, off)

        # LOAD [Rs+off], Rd  or  LOAD [Rs], Rd
        if src_up.startswith('['):
            base, off = parse_indexed(src)
            base_reg  = reg(base)
            rd        = reg(dst)
            if off:
                return encode(OP_LOAD, LOAD_IDX_R, rd, (base_reg << 10) | (off & 0x3FF))
            else:
                return encode(OP_LOAD, LOAD_IND_R, rd, base_reg)

        # LOAD Rd, [Rs+off]  or  LOAD Rd, [Rs]
        if dst_up.startswith('['):
            base, off = parse_indexed(dst)
            base_reg  = reg(base)
            rd        = reg(src)   # rd field holds the source data register
            if off:
                return encode(OP_LOAD, LOAD_IDX_W, rd, (base_reg << 10) | (off & 0x3FF))
            else:
                return encode(OP_LOAD, LOAD_IND_W, rd, base_reg)

        # LOAD Rs, Rd  (register to register)
        rs_idx = reg(src)
        rd_idx = reg(dst)
        return encode(OP_LOAD, LOAD_RR, rd_idx, rs_idx)

    # ---- ALU ops ----
    ALU_OPS = {
        'ADD': OP_ADD, 'SUB': OP_SUB, 'AND': OP_AND, 'OR':  OP_OR,
        'XOR': OP_XOR, 'MUL': OP_MUL, 'DIV': OP_DIV,
    }
    if mnemonic in ALU_OPS:
        op    = ALU_OPS[mnemonic]
        src   = args[0]
        rd    = reg(args[1])
        if src.startswith('#') or src.upper() not in REGISTERS:
            val = imm(src) & 0xFFF
            return encode(op, 0, rd, 0x1000 | val)   # bit 12 = immediate flag
        else:
            return encode(op, reg(src), rd, 0)

    # ---- Unary / shift ----
    if mnemonic == 'NOT':
        return encode(OP_NOT, 0, reg(args[0]), 0)

    if mnemonic == 'SFT':
        rd = reg(args[0])
        n  = imm(args[1]) & 0xF   # 4-bit signed
        return encode(OP_SFT, 0, rd, n)

    if mnemonic == 'SAR':
        rd = reg(args[0])
        n  = imm(args[1]) & 0xF
        return encode(OP_SAR, 0, rd, n)

    if mnemonic == 'SWP':
        return encode(OP_SWP, 0, reg(args[0]), 0)

    # ---- Stack ----
    if mnemonic == 'PUSH':
        return encode(OP_PUSH, 0, reg(args[0]), 0)

    if mnemonic == 'POP':
        return encode(OP_POP, 0, reg(args[0]), 0)

    # ---- Control flow ----
    if mnemonic in ('JMP', 'CAL'):
        op   = OP_JMP if mnemonic == 'JMP' else OP_CAL
        cond = parse_cond(args[0])
        tgt  = args[1]
        if tgt.upper() in REGISTERS:
            return encode(op, cond, reg(tgt), 0)
        else:
            target = imm(tgt)
            # PC after fetch is pc+3; offset is signed 13-bit
            offset = target - (pc + 3)
            if not (-4096 <= offset <= 4095):
                raise ValueError(
                    f"branch target 0x{target:X} out of 13-bit PC-relative range "
                    f"(offset {offset:+d} from 0x{pc+3:X})"
                )
            return encode(op, cond, 0, offset & 0x1FFF)

    if mnemonic == 'RET':
        cond = parse_cond(args[0]) if args else COND_AL
        return encode(OP_RET, cond, 0, 0)

    raise ValueError(f"unknown mnemonic: {mnemonic!r}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(description='M56 Assembler')
    parser.add_argument('input',  help='source .asm file')
    parser.add_argument('output', nargs='?', help='binary output file')
    parser.add_argument('--load-addr', default='0x8000',
                        help='load address (default: 0x8000)')
    parser.add_argument('--listing', action='store_true',
                        help='print assembly listing')
    args = parser.parse_args()

    load_addr = int(args.load_addr, 0)

    with open(args.input) as f:
        source = f.read()

    try:
        code, labels, listing = assemble(source, load_addr)
    except AssemblerError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.listing or not args.output:
        print(f"  {'addr':6}  {'bytes':8}  source")
        print(f"  {'----':6}  {'-----':8}  ------")
        for addr, data, src in listing:
            hex_bytes = ' '.join(f'{b:02X}' for b in data)
            print(f"  {addr:06X}  {hex_bytes:<8}  {src}")
        if labels:
            print()
            print("Labels:")
            for name, addr in sorted(labels.items(), key=lambda x: x[1]):
                print(f"  {name:<20} 0x{addr:06X}")
        print(f"\n{len(code)} bytes")

    if args.output:
        with open(args.output, 'wb') as f:
            f.write(code)
        print(f"Written to {args.output}")


if __name__ == '__main__':
    main()
