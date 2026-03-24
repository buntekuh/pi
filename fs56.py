"""
56FS — Virtual Filesystem for the M56.

Sits above individual Cartridge instances and routes path operations
to the correct one based on the mount table.

Mount points live under /volumes. /bin is read-only system territory.
The OS bypasses protection for privileged operations (mounting etc).
"""

from cartridge import Cartridge, NotFound, AlreadyExists, NotADirectory, \
                      NotAFile, NoSpace, FSError, TYPE_FILE, TYPE_DIR


class PermissionError(FSError):
    pass


# Paths the user cannot write to or create directories in.
# The OS can bypass this with _protected=False on internal calls.
_PROTECTED = frozenset(['/bin', '/volumes'])

# System programs pre-installed in /bin.
# Values are the initial file contents (stub scripts for now).
_BIN = {
    'ls':     '# list directory contents\n',
    'cd':     '# change directory\n',
    'mkdir':  '# make directory\n',
    'rm':     '# remove file or empty directory\n',
    'cat':    '# print file to terminal\n',
    'nano':   '# simple text editor\n',
    'asm':    '# M56 assembler\n',
    'hex':    '# hex viewer/editor\n',
    'mount':  '# mount a cartridge at /volumes/<name>\n',
    'umount': '# unmount a cartridge\n',
}


class FS56:
    """
    Virtual filesystem.

    Usage:
        vfs = VFS()               # creates and formats a boot cartridge
        vfs.ls('/')               # [('bin', dir, 0), ('home', dir, 0), ...]
        vfs.write_file('/home/hello.pi', 'print("hi")')
        vfs.mount(cart, 'game')   # mounts cart at /volumes/game
        vfs.ls('/volumes/game')
        vfs.umount('game')
    """

    def __init__(self, boot_cartridge=None):
        self._boot = boot_cartridge or Cartridge()
        self._boot.format()
        self._mounts  = {}    # name → Cartridge  (mounted under /volumes)
        self.cwd      = '/'
        self._setup_boot()

    def _setup_boot(self):
        """Create the standard directory tree on the boot cartridge."""
        for d in ('/bin', '/volumes', '/home', '/tmp'):
            self._boot.mkdir(d)
        for name, stub in _BIN.items():
            self._boot.write_file(f'/bin/{name}', stub)

    # ------------------------------------------------------------------
    # Mount / unmount
    # ------------------------------------------------------------------

    def mount(self, cartridge, name):
        """
        Mount cartridge at /volumes/<name>.
        The mount point directory is created automatically.
        """
        if name in self._mounts:
            raise AlreadyExists(f'/volumes/{name}')
        self._mounts[name] = cartridge
        # Create a placeholder dir entry in /volumes on the boot cartridge
        self._boot.mkdir(f'/volumes/{name}')

    def umount(self, name):
        """Unmount cartridge at /volumes/<name>."""
        if name not in self._mounts:
            raise NotFound(f'/volumes/{name}')
        del self._mounts[name]
        self._boot.delete(f'/volumes/{name}')

    def mounted(self):
        """Return list of (name, cartridge) for all mounted cartridges."""
        return list(self._mounts.items())

    # ------------------------------------------------------------------
    # Path routing
    # ------------------------------------------------------------------

    def _route(self, path):
        """
        Return (cartridge, local_path) for an absolute path.

        Paths under /volumes/<name>/... are routed to the named cartridge.
        Everything else goes to the boot cartridge.
        """
        path = self._abs(path)
        parts = path.strip('/').split('/')
        if len(parts) >= 2 and parts[0] == 'volumes' and parts[1] in self._mounts:
            cart       = self._mounts[parts[1]]
            local_path = '/' + '/'.join(parts[2:]) if len(parts) > 2 else '/'
            return cart, local_path
        return self._boot, path

    def _abs(self, path):
        """Resolve to absolute path."""
        if path is None:
            path = self.cwd
        if not path.startswith('/'):
            path = self.cwd.rstrip('/') + '/' + path
        # normalise . and ..
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

    def _check_writable(self, path):
        """Raise PermissionError if path is inside a protected directory."""
        path = self._abs(path)
        for p in _PROTECTED:
            if path == p or path.startswith(p + '/'):
                raise PermissionError(f'{path}: read-only')

    # ------------------------------------------------------------------
    # Filesystem operations (same interface as Cartridge)
    # ------------------------------------------------------------------

    def ls(self, path=None):
        path = self._abs(path)
        # /volumes: merge boot entries with live mount names
        if path == '/volumes':
            entries = [(n, TYPE_DIR, 0) for n in self._mounts]
            return entries
        cart, local = self._route(path)
        return cart.ls(local)

    def mkdir(self, path):
        self._check_writable(path)
        cart, local = self._route(path)
        cart.mkdir(local)

    def read_file(self, path):
        cart, local = self._route(path)
        return cart.read_file(local)

    def write_file(self, path, data):
        self._check_writable(path)
        cart, local = self._route(path)
        cart.write_file(local, data)

    def delete(self, path):
        self._check_writable(path)
        cart, local = self._route(path)
        cart.delete(local)

    def exists(self, path):
        cart, local = self._route(self._abs(path))
        return cart.exists(local)

    def stat(self, path):
        cart, local = self._route(self._abs(path))
        return cart.stat(local)

    def cd(self, path):
        target = self._abs(path)
        # verify it's a directory
        if target != '/':
            cart, local = self._route(target)
            if not cart.exists(local):
                raise NotFound(target)
            entry = cart.stat(local)
            if entry['type'] != TYPE_DIR:
                raise NotADirectory(target)
        self.cwd = target
