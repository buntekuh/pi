"""
56FS — Virtual Filesystem for the M56.

Sits above individual Cartridge instances and routes path operations
to the correct one based on the mount table.

Mount points live under /volumes. /bin is read-only system territory.
The OS bypasses protection for privileged operations (mounting etc).

/uplink is a special read-only mount backed by the host 'uplink/'
directory.  Files placed there by the user's real editor appear
immediately inside the terminal without any copy step.
"""

import os as _os
import pathlib

from cartridge import Cartridge, NotFound, AlreadyExists, NotADirectory, \
                      NotAFile, NoSpace, FSError, TYPE_FILE, TYPE_DIR


# Default host paths (alongside this file).
_DEFAULT_UPLINK = pathlib.Path(__file__).parent / 'uplink'
_DEFAULT_HOME   = pathlib.Path(__file__).parent / 'home'


class PermissionError(FSError):
    pass


class HostCart:
    """
    Read-write cartridge backed by a real directory on the host filesystem.

    Used for /home — files written inside the terminal persist between
    sessions and are directly editable with the user's real editor.
    """

    def __init__(self, host_path):
        self._root = pathlib.Path(host_path)
        self._root.mkdir(parents=True, exist_ok=True)

    def _host(self, path: str) -> pathlib.Path:
        rel = path.strip('/')
        return self._root / rel if rel else self._root

    def ls(self, path='/'):
        host = self._host(path)
        if not host.is_dir():
            raise NotFound(path)
        entries = []
        for p in sorted(host.iterdir()):
            if p.name.startswith('.'):
                continue
            if p.is_dir():
                entries.append((p.name, TYPE_DIR, 0))
            else:
                entries.append((p.name, TYPE_FILE, p.stat().st_size))
        return entries

    def read_file(self, path) -> bytes:
        host = self._host(path)
        if not host.is_file():
            raise NotFound(path)
        return host.read_bytes()

    def write_file(self, path, data):
        host = self._host(path)
        host.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, str):
            data = data.encode()
        host.write_bytes(data)

    def mkdir(self, path):
        host = self._host(path)
        if host.exists():
            raise AlreadyExists(path)
        host.mkdir(parents=True, exist_ok=True)

    def delete(self, path):
        host = self._host(path)
        if not host.exists():
            raise NotFound(path)
        if host.is_dir():
            try:
                host.rmdir()
            except OSError:
                raise FSError(f'{path}: directory not empty')
        else:
            host.unlink()

    def exists(self, path) -> bool:
        return self._host(path).exists()

    def stat(self, path) -> dict:
        host = self._host(path)
        if not host.exists():
            raise NotFound(path)
        if host.is_dir():
            return {'type': TYPE_DIR, 'size': 0}
        return {'type': TYPE_FILE, 'size': host.stat().st_size}


class UplinkCart:
    """
    Read-only cartridge backed by a directory on the host filesystem.

    Every read goes straight to disk, so files edited in the user's
    real editor are visible inside the terminal immediately — no sync
    step required.  Write operations raise PermissionError; the M56
    cannot modify uplinked files.
    """

    def __init__(self, host_path):
        self._root = _os.path.abspath(str(host_path))

    def _host(self, path: str) -> str:
        """Map a virtual path to an absolute host path."""
        rel = path.strip('/')
        return _os.path.join(self._root, rel) if rel else self._root

    def ls(self, path='/'):
        host = self._host(path)
        if not _os.path.isdir(host):
            raise NotFound(path)
        entries = []
        for name in sorted(_os.listdir(host)):
            if name.startswith('.'):
                continue   # skip .DS_Store and other hidden files
            full = _os.path.join(host, name)
            if _os.path.isdir(full):
                entries.append((name, TYPE_DIR, 0))
            else:
                entries.append((name, TYPE_FILE, _os.path.getsize(full)))
        return entries

    def read_file(self, path) -> bytes:
        host = self._host(path)
        if not _os.path.isfile(host):
            raise NotFound(path)
        with open(host, 'rb') as f:
            return f.read()

    def exists(self, path) -> bool:
        return _os.path.exists(self._host(path))

    def stat(self, path) -> dict:
        host = self._host(path)
        if not _os.path.exists(host):
            raise NotFound(path)
        if _os.path.isdir(host):
            return {'type': TYPE_DIR, 'size': 0}
        return {'type': TYPE_FILE, 'size': _os.path.getsize(host)}

    # Write operations are not permitted on uplinked files.
    def write_file(self, path, data):
        raise PermissionError(f'{path}: uplink is read-only')

    def mkdir(self, path):
        raise PermissionError(f'{path}: uplink is read-only')

    def delete(self, path):
        raise PermissionError(f'{path}: uplink is read-only')


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
    'edit':   '# text editor\n',
    'run':    '# run a Pi source file\n',
    'asm':    '# assemble M56 assembly to binary\n',
    'debug':  '# interactive step debugger\n',
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

    def __init__(self, boot_cartridge=None, uplink_path=_DEFAULT_UPLINK,
                 home_path=_DEFAULT_HOME):
        self._boot = boot_cartridge or Cartridge()
        self._boot.format()
        self._mounts  = {}    # name → Cartridge  (mounted under /volumes)
        self.cwd      = '/'
        uplink_path = pathlib.Path(uplink_path)
        self._uplink = UplinkCart(uplink_path) if uplink_path.is_dir() else None
        self._home   = HostCart(home_path)
        self._setup_boot()

    def _setup_boot(self):
        """Create the standard directory tree on the boot cartridge."""
        # /home is a stub entry only — actual storage is in HostCart.
        # /uplink is a stub entry only — actual storage is in UplinkCart.
        dirs = ['/bin', '/volumes', '/home', '/tmp']
        if self._uplink:
            dirs.append('/uplink')
        for d in dirs:
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

        /uplink/...         → UplinkCart (host filesystem, read-only)
        /volumes/<n>/...    → mounted Cartridge
        everything else     → boot Cartridge
        """
        path = self._abs(path)
        parts = path.strip('/').split('/')
        if self._uplink and parts[0] == 'uplink':
            local_path = '/' + '/'.join(parts[1:]) if len(parts) > 1 else '/'
            return self._uplink, local_path
        if parts[0] == 'home':
            local_path = '/' + '/'.join(parts[1:]) if len(parts) > 1 else '/'
            return self._home, local_path
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
