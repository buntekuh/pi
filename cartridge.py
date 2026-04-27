"""
Utronic Data Cartridge — M56 block-storage device.

Layout (512-byte blocks):
  Block 0        Superblock
  Blocks 1–4     FAT  (1024 entries × 2 bytes = 2048 bytes = 4 blocks)
  Block 5        Root directory
  Blocks 6+      Data

FAT entry values:
  0x0000         free
  0x0001–0xFFFE  next block in chain
  0xFFFF         end of chain (EOF)

Directory entry (32 bytes):
  name       16s   null-padded filename
  type        B    0=free  1=file  2=dir
  first       H    first block (0 if empty file)
  size        I    bytes (files) or 0 (dirs track via entries)
  flags       B    bit 0 = hidden, bit 1 = read-only
  reserved    8s
"""

import struct
import os

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------

BLOCK_SIZE        = 512
TOTAL_BLOCKS      = 1024          # 512 KB cartridge

FAT_START         = 1
FAT_ENTRY_SIZE    = 2             # uint16 per block
FAT_ENTRIES       = TOTAL_BLOCKS
FAT_BYTES         = FAT_ENTRIES * FAT_ENTRY_SIZE          # 2048
FAT_BLOCKS        = (FAT_BYTES + BLOCK_SIZE - 1) // BLOCK_SIZE  # 4

ROOT_BLOCK        = FAT_START + FAT_BLOCKS                # 5
DATA_START        = ROOT_BLOCK + 1                        # 6

MAGIC             = b'56FS'
VERSION           = 1

FAT_FREE          = 0x0000
FAT_EOF           = 0xFFFF

TYPE_FREE         = 0
TYPE_FILE         = 1
TYPE_DIR          = 2

FLAG_HIDDEN       = 0x01   # not shown in ls()
FLAG_READONLY     = 0x02   # directory cannot be written to

ENTRY_SIZE        = 32
ENTRIES_PER_BLOCK = BLOCK_SIZE // ENTRY_SIZE              # 16

ENTRY_FMT         = '<16sBHIB8s'  # name, type, first, size, flags, _reserved


# ---------------------------------------------------------------------------
# Filesystem errors
# ---------------------------------------------------------------------------

class FSError(Exception):
    pass

class NotFound(FSError):
    pass

class AlreadyExists(FSError):
    pass

class NotADirectory(FSError):
    pass

class NotAFile(FSError):
    pass

class NoSpace(FSError):
    pass


# ---------------------------------------------------------------------------
# Cartridge
# ---------------------------------------------------------------------------

class Cartridge:
    """
    Virtual block-storage device.

    All data lives in self.data (bytearray). Callers interact through
    high-level methods; the block/FAT/directory layer is private.
    """

    def __init__(self, size=TOTAL_BLOCKS * BLOCK_SIZE):
        self.data          = bytearray(size)
        self.total_blocks  = size // BLOCK_SIZE
        self.cwd           = '/'        # current working directory
        self._cwd_block    = ROOT_BLOCK

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def format(self, label='UTRONIC'):
        """Wipe and initialise an empty filesystem."""
        self.data = bytearray(len(self.data))

        # Superblock
        super_data = struct.pack('<4sBHHHHH16s',
            MAGIC, VERSION,
            BLOCK_SIZE, self.total_blocks,
            FAT_START, FAT_BLOCKS, ROOT_BLOCK,
            label.encode()[:16].ljust(16, b'\x00'),
        )
        self._write_block(0, super_data.ljust(BLOCK_SIZE, b'\x00'))

        # FAT: mark reserved blocks (0 = superblock, 1-4 = FAT, 5 = root)
        for b in range(DATA_START):
            self._fat_set(b, FAT_EOF)

        # Root directory block: all entries free (already zero)
        self.cwd       = '/'
        self._cwd_block = ROOT_BLOCK

    def ls(self, path=None):
        """Return list of (name, type, size) for visible entries in path."""
        dir_block = self._resolve_dir(path)
        return [
            (e['name'], e['type'], e['size'])
            for e in self._dir_entries(dir_block)
            if e['type'] != TYPE_FREE and not (e['flags'] & FLAG_HIDDEN)
        ]

    def ls_all(self, path=None):
        """Return all entries including hidden ones."""
        dir_block = self._resolve_dir(path)
        return [
            (e['name'], e['type'], e['size'])
            for e in self._dir_entries(dir_block)
            if e['type'] != TYPE_FREE
        ]

    def mkdir(self, path, hidden=False, readonly=False):
        """Create a directory. Parent must exist."""
        parent_path, name = self._split(path)
        parent_block = self._resolve_dir(parent_path)
        if self._dir_find(parent_block, name):
            raise AlreadyExists(path)
        self._check_writable(parent_path)
        block = self._alloc_block()
        self._fat_set(block, FAT_EOF)
        flags = (FLAG_HIDDEN if hidden else 0) | (FLAG_READONLY if readonly else 0)
        self._dir_add(parent_block, name, TYPE_DIR, block, 0, flags)

    def write_file(self, path, data, hidden=False):
        """Write bytes to a file, creating or overwriting it."""
        if isinstance(data, str):
            data = data.encode()
        parent_path, name = self._split(path)
        parent_block = self._resolve_dir(parent_path)
        self._check_writable(parent_path)

        existing = self._dir_find(parent_block, name)
        if existing:
            if existing['type'] == TYPE_DIR:
                raise NotAFile(path)
            self._free_chain(existing['first'])
            self._dir_remove(parent_block, name)

        first = self._write_chain(data) if data else 0
        flags = FLAG_HIDDEN if hidden else 0
        self._dir_add(parent_block, name, TYPE_FILE, first, len(data), flags)

    def set_hidden(self, path, value: bool):
        """Show or hide a file or directory."""
        self._update_flags(path, FLAG_HIDDEN, value)

    def set_readonly(self, path, value: bool):
        """Lock or unlock a directory."""
        self._update_flags(path, FLAG_READONLY, value)

    def read_file(self, path):
        """Return bytes contents of a file."""
        entry = self._resolve_entry(path)
        if entry['type'] == TYPE_DIR:
            raise NotAFile(path)
        return self._read_chain(entry['first'], entry['size'])

    def delete(self, path):
        """Delete a file or empty directory."""
        parent_path, name = self._split(path)
        parent_block = self._resolve_dir(parent_path)
        entry = self._dir_find(parent_block, name)
        if not entry:
            raise NotFound(path)
        if entry['type'] == TYPE_DIR:
            if self._dir_entries(entry['first']):
                raise FSError(f"directory not empty: {path}")
            self._free_chain(entry['first'])
        else:
            if entry['first']:
                self._free_chain(entry['first'])
        self._dir_remove(parent_block, name)

    def cd(self, path):
        """Change current working directory."""
        if not path.startswith('/'):
            path = self.cwd.rstrip('/') + '/' + path
        path = self._normalise(path)
        block = self._resolve_dir(path)
        self.cwd        = path
        self._cwd_block = block

    def exists(self, path):
        try:
            self._resolve_entry(path)
            return True
        except (NotFound, NotADirectory):
            return False

    def stat(self, path):
        """Return entry dict for path including hidden and readonly flags."""
        e = self._resolve_entry(path)
        return {
            'name':     e['name'],
            'is_dir':   e['type'] == TYPE_DIR,
            'size':     e['size'],
            'hidden':   bool(e['flags'] & FLAG_HIDDEN),
            'readonly': bool(e['flags'] & FLAG_READONLY),
        }

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def _normalise(self, path):
        parts = []
        for p in path.split('/'):
            if p in ('', '.'):
                continue
            elif p == '..':
                if parts:
                    parts.pop()
            else:
                parts.append(p)
        return '/' + '/'.join(parts)

    def _resolve_path(self, path):
        """Return absolute path, resolved from cwd if relative."""
        if path is None:
            return self.cwd
        if not path.startswith('/'):
            path = self.cwd.rstrip('/') + '/' + path
        return self._normalise(path)

    def _split(self, path):
        """Split absolute path into (parent_path, name)."""
        path = self._resolve_path(path)
        if path == '/':
            return '/', ''
        parent, _, name = path.rpartition('/')
        return (parent or '/'), name

    def _resolve_dir(self, path):
        """Return block number of directory at path."""
        path = self._resolve_path(path)
        if path == '/':
            return ROOT_BLOCK
        block = ROOT_BLOCK
        for part in path.strip('/').split('/'):
            entry = self._dir_find(block, part)
            if not entry:
                raise NotFound(path)
            if entry['type'] != TYPE_DIR:
                raise NotADirectory(path)
            block = entry['first']
        return block

    def _resolve_entry(self, path):
        """Return entry dict for path."""
        path = self._resolve_path(path)
        if path == '/':
            return {'name': '', 'type': TYPE_DIR, 'first': ROOT_BLOCK, 'size': 0}
        parent_path, name = self._split(path)
        parent_block = self._resolve_dir(parent_path)
        entry = self._dir_find(parent_block, name)
        if not entry:
            raise NotFound(path)
        return entry

    # ------------------------------------------------------------------
    # Block I/O
    # ------------------------------------------------------------------

    def _read_block(self, n):
        off = n * BLOCK_SIZE
        return bytes(self.data[off: off + BLOCK_SIZE])

    def _write_block(self, n, data):
        off = n * BLOCK_SIZE
        self.data[off: off + BLOCK_SIZE] = data[:BLOCK_SIZE].ljust(BLOCK_SIZE, b'\x00')

    # ------------------------------------------------------------------
    # FAT
    # ------------------------------------------------------------------

    def _fat_offset(self, block):
        """Byte offset within self.data for FAT entry of block."""
        return FAT_START * BLOCK_SIZE + block * FAT_ENTRY_SIZE

    def _fat_get(self, block):
        off = self._fat_offset(block)
        return struct.unpack_from('<H', self.data, off)[0]

    def _fat_set(self, block, value):
        off = self._fat_offset(block)
        struct.pack_into('<H', self.data, off, value)

    def _alloc_block(self):
        for b in range(DATA_START, self.total_blocks):
            if self._fat_get(b) == FAT_FREE:
                self._fat_set(b, FAT_EOF)
                return b
        raise NoSpace("cartridge full")

    def _free_chain(self, first):
        b = first
        while b and b != FAT_EOF:
            nxt = self._fat_get(b)
            self._fat_set(b, FAT_FREE)
            # zero the block
            self._write_block(b, b'\x00' * BLOCK_SIZE)
            b = nxt

    def _chain(self, first):
        """Return ordered list of blocks in chain."""
        blocks = []
        b = first
        while b and b not in (FAT_FREE, FAT_EOF):
            blocks.append(b)
            b = self._fat_get(b)
        return blocks

    def _read_chain(self, first, size):
        raw = bytearray()
        for b in self._chain(first):
            raw += self._read_block(b)
        return bytes(raw[:size])

    def _write_chain(self, data):
        blocks_needed = (len(data) + BLOCK_SIZE - 1) // BLOCK_SIZE
        allocated = [self._alloc_block() for _ in range(blocks_needed)]
        # link the chain
        for i, b in enumerate(allocated):
            self._fat_set(b, allocated[i+1] if i+1 < len(allocated) else FAT_EOF)
        # write data
        for i, b in enumerate(allocated):
            chunk = data[i*BLOCK_SIZE: (i+1)*BLOCK_SIZE]
            self._write_block(b, chunk)
        return allocated[0]

    # ------------------------------------------------------------------
    # Directory
    # ------------------------------------------------------------------

    def _check_writable(self, path):
        """Raise FSError if the directory at path is read-only."""
        if path == '/':
            return
        try:
            e = self._resolve_entry(path)
            if e['flags'] & FLAG_READONLY:
                raise FSError(f'read-only: {path}')
        except (NotFound, NotADirectory):
            pass

    def _update_flags(self, path, flag, value):
        """Set or clear a single flag bit on an existing entry."""
        parent_path, name = self._split(path)
        parent_block = self._resolve_dir(parent_path)
        name_b = name.encode()[:16]
        for b in self._chain(parent_block) or [parent_block]:
            blk = bytearray(self._read_block(b))
            for i in range(ENTRIES_PER_BLOCK):
                off = i * ENTRY_SIZE
                n, typ = blk[off:off+16].rstrip(b'\x00'), blk[off+16]
                if typ != TYPE_FREE and n == name_b:
                    flags_off = off + 16 + 1 + 2 + 4   # after name, type, first, size
                    if value:
                        blk[flags_off] |= flag
                    else:
                        blk[flags_off] &= ~flag
                    self._write_block(b, bytes(blk))
                    return
        raise NotFound(path)

    def _dir_entries(self, dir_block):
        """Return all non-free entries in the directory chain."""
        entries = []
        for b in self._chain(dir_block) or [dir_block]:
            blk = self._read_block(b)
            for i in range(ENTRIES_PER_BLOCK):
                raw = blk[i*ENTRY_SIZE: (i+1)*ENTRY_SIZE]
                name_b, typ, first, size, flags, _ = struct.unpack(ENTRY_FMT, raw)
                if typ != TYPE_FREE:
                    entries.append({
                        'name':  name_b.rstrip(b'\x00').decode(errors='replace'),
                        'type':  typ,
                        'first': first,
                        'size':  size,
                        'flags': flags,
                        '_block': b,
                        '_slot':  i,
                    })
        return entries

    def _dir_find(self, dir_block, name):
        name_b = name.encode()[:16]
        for b in self._chain(dir_block) or [dir_block]:
            blk = self._read_block(b)
            for i in range(ENTRIES_PER_BLOCK):
                raw = blk[i*ENTRY_SIZE: (i+1)*ENTRY_SIZE]
                n, typ, first, size, flags, _ = struct.unpack(ENTRY_FMT, raw)
                if typ != TYPE_FREE and n.rstrip(b'\x00') == name_b:
                    return {'name': name, 'type': typ, 'first': first,
                            'size': size, 'flags': flags,
                            '_block': b, '_slot': i}
        return None

    def _dir_add(self, dir_block, name, typ, first, size, flags=0):
        """Write a new directory entry, extending the dir chain if needed."""
        name_b = name.encode()[:16].ljust(16, b'\x00')
        packed = struct.pack(ENTRY_FMT, name_b, typ, first, size, flags, b'\x00'*8)

        # Find a free slot in existing blocks
        for b in self._chain(dir_block) or [dir_block]:
            blk = bytearray(self._read_block(b))
            for i in range(ENTRIES_PER_BLOCK):
                off = i * ENTRY_SIZE
                if blk[off + 16] == TYPE_FREE:   # type byte
                    blk[off: off+ENTRY_SIZE] = packed
                    self._write_block(b, bytes(blk))
                    return

        # No free slot — extend dir chain with a new block
        new_b = self._alloc_block()
        # link last block to new one
        chain = self._chain(dir_block) or [dir_block]
        self._fat_set(chain[-1], new_b)
        self._fat_set(new_b, FAT_EOF)
        blk = bytearray(BLOCK_SIZE)
        blk[0: ENTRY_SIZE] = packed
        self._write_block(new_b, bytes(blk))

    def _dir_remove(self, dir_block, name):
        name_b = name.encode()[:16]
        for b in self._chain(dir_block) or [dir_block]:
            blk = bytearray(self._read_block(b))
            for i in range(ENTRIES_PER_BLOCK):
                off = i * ENTRY_SIZE
                n = blk[off:off+16].rstrip(b'\x00')
                typ = blk[off+16]
                if typ != TYPE_FREE and n == name_b:
                    blk[off: off+ENTRY_SIZE] = b'\x00' * ENTRY_SIZE
                    self._write_block(b, bytes(blk))
                    return
        raise NotFound(name)

    # ------------------------------------------------------------------
    # Persistence (save/load the raw bytearray)
    # ------------------------------------------------------------------

    def save(self, path):
        with open(path, 'wb') as f:
            f.write(self.data)

    def load(self, path):
        with open(path, 'rb') as f:
            self.data = bytearray(f.read())
        self.total_blocks = len(self.data) // BLOCK_SIZE
        self.cwd          = '/'
        self._cwd_block   = ROOT_BLOCK
