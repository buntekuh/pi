"""
fs.py — Titania filesystem

The simplest possible filesystem that supports hidden and writable flags.

Design rationale
----------------
The filesystem is a plain tree of nodes. Every design decision was made by
asking "is this the minimum needed?" and removing anything that wasn't.

Why no users or permissions?
  Titania has no security model. Adding users and permissions would add
  complexity without serving any goal — there is only ever one person
  using the machine.

Why no timestamps?
  Nothing in the system needs them. They can be added later if a use case
  appears; leaving them out now keeps the node structure minimal.

Why only two flags?
  visible and writable are the only flags that serve a real purpose:
  visible hides files from ls while keeping them reachable by exact path,
  which is the foundation of the IF game mechanic (hidden rooms, locked
  doors, undiscovered objects). writable on directories works like the
  write-protect notch on a floppy — one flag locks everything inside.
  No other flag earns its place.

Why absolute paths only?
  The filesystem has no concept of a current directory — that state belongs
  to the process using the filesystem (the shell, the game engine). Keeping
  the FS stateless means it is easier to reason about and easier to
  reimplement on hardware. The caller resolves relative paths before
  calling in.

Why are directories called directories and not folders?
  "Folder" is a UI metaphor from the desktop era. A directory is what
  the structure actually is — a list of named entries pointing to nodes.
  The word matches the implementation.

Why no .. in path resolution?
  For the same reason: simplicity. The caller normalises paths. The
  filesystem just walks the tree.
"""

from pathlib import PurePosixPath


class FSError(Exception):
    """Raised for all filesystem errors: not found, wrong type, read-only."""
    pass


class Node:
    """
    One node in the filesystem tree.

    A node is either a file or a directory — never both.
    The distinction is simple: if it has children, it is a directory.
    If it has data, it is a file. A directory has no data; a file has
    no children.

    Both carry a visible flag (affects ls) and a writable flag
    (directories only — controls whether contents can be modified).
    The _parent backpointer lets write() check the parent's writable
    flag without walking the tree again.
    """

    __slots__ = ('name', 'visible', 'writable', '_children', '_data', '_parent')

    def __init__(self, name, *, visible=True, writable=True, is_dir=False):
        self.name     = name
        self.visible  = visible
        self.writable = writable    # only meaningful on directories
        self._parent  = None        # set when the node is inserted into the tree
        if is_dir:
            self._children = {}     # name → Node, preserves insertion order
            self._data     = None
        else:
            self._children = None   # None signals "I am a file"
            self._data     = b''

    @property
    def is_dir(self):
        return self._children is not None

    @property
    def is_file(self):
        return self._children is None


class FS:
    """
    Titania filesystem.

    The tree is rooted at '/' which is always visible and writable.
    Paths are POSIX-style strings: '/home/arrival.grue'.
    All operations are synchronous — no concurrency handling here.
    The kernel message layer sits above this and serialises access.
    """

    def __init__(self):
        # The root node is the only node without a parent.
        self._root = Node('/', visible=True, writable=True, is_dir=True)

    # ------------------------------------------------------------------
    # Internal path helpers
    # ------------------------------------------------------------------

    def _parts(self, path):
        """
        Split a path into the names of nodes to visit, starting from root.
        The leading '/' is dropped because it is not a node name — it just
        means "start at self._root", which the walk loop already does.

        '/home/arrival.grue' → ['home', 'arrival.grue']
        '/'                  → []   (root itself, no steps needed)
        """
        return [p for p in PurePosixPath(path).parts if p != '/']

    def _resolve(self, path):
        """
        Walk the tree and return the node at path.
        Raises FSError if any component is missing or if a non-leaf
        component is not a directory.
        Does not follow '..' — paths must be absolute and clean.
        """
        node = self._root
        for part in self._parts(path):
            if not node.is_dir:
                raise FSError(f"not a directory: {path}")
            child = node._children.get(part)
            if child is None:
                raise FSError(f"not found: {path}")
            node = child
        return node

    def _resolve_parent(self, path):
        """
        Return (parent_node, child_name) for a path.
        Used by operations that need to insert or remove a node:
        create, delete, move.
        Raises FSError if the parent path does not exist or is not a directory.
        """
        parts = self._parts(path)
        if not parts:
            raise FSError("cannot operate on root")
        parent = self._root
        for part in parts[:-1]:
            if not parent.is_dir:
                raise FSError(f"not a directory: {path}")
            child = parent._children.get(part)
            if child is None:
                raise FSError(f"not found: {path}")
            parent = child
        return parent, parts[-1]

    def _check_writable(self, directory):
        """
        Raise FSError if the directory's writable flag is False.
        Called before any operation that modifies directory contents.
        """
        if not directory.writable:
            raise FSError("directory is read-only")

    # ------------------------------------------------------------------
    # Directory operations
    # ------------------------------------------------------------------

    def mkdir(self, path, visible=True, writable=True):
        """
        Create a new directory at path.
        The parent directory must already exist and must be writable.
        Returns the new Node.
        """
        parent, name = self._resolve_parent(path)
        if not parent.is_dir:
            raise FSError(f"parent is not a directory: {path}")
        self._check_writable(parent)
        if name in parent._children:
            raise FSError(f"already exists: {path}")
        node = Node(name, visible=visible, writable=writable, is_dir=True)
        node._parent = parent
        parent._children[name] = node
        return node

    def ls(self, path='/'):
        """
        List the names of visible children in a directory.
        Hidden nodes (visible=False) are excluded — they are still
        accessible by exact path but do not appear here.
        """
        node = self._resolve(path)
        if not node.is_dir:
            raise FSError(f"not a directory: {path}")
        return [n.name for n in node._children.values() if n.visible]

    def ls_all(self, path='/'):
        """
        List all children including hidden ones.
        Useful for debugging and for privileged game operations.
        """
        node = self._resolve(path)
        if not node.is_dir:
            raise FSError(f"not a directory: {path}")
        return list(node._children.keys())

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def create(self, path, data=b'', visible=True):
        """
        Create a new file at path with the given initial contents.
        The parent directory must be writable.
        Files are visible by default; pass visible=False to hide them
        until the game reveals them with set_visible().
        Returns the new Node.
        """
        parent, name = self._resolve_parent(path)
        if not parent.is_dir:
            raise FSError(f"parent is not a directory: {path}")
        self._check_writable(parent)
        if name in parent._children:
            raise FSError(f"already exists: {path}")
        node = Node(name, visible=visible, is_dir=False)
        node._data   = bytes(data)
        node._parent = parent
        parent._children[name] = node
        return node

    def read(self, path):
        """
        Return the full contents of a file as bytes.
        Works regardless of the visible flag — hidden files are readable
        if you know their path.
        """
        node = self._resolve(path)
        if not node.is_file:
            raise FSError(f"not a file: {path}")
        return node._data

    def write(self, path, data):
        """
        Replace the entire contents of a file.
        Fails if the parent directory is not writable.
        """
        node = self._resolve(path)
        if not node.is_file:
            raise FSError(f"not a file: {path}")
        if not node._parent.writable:
            raise FSError("directory is read-only")
        node._data = bytes(data)

    def append(self, path, data):
        """
        Append bytes to a file without replacing existing contents.
        Fails if the parent directory is not writable.
        Useful for log files and player journals.
        """
        node = self._resolve(path)
        if not node.is_file:
            raise FSError(f"not a file: {path}")
        if not node._parent.writable:
            raise FSError("directory is read-only")
        node._data += bytes(data)

    # ------------------------------------------------------------------
    # Operations common to files and directories
    # ------------------------------------------------------------------

    def delete(self, path):
        """
        Delete a file, or an empty directory.
        The parent directory must be writable.
        Raises FSError if trying to delete a non-empty directory.
        """
        parent, name = self._resolve_parent(path)
        self._check_writable(parent)
        node = parent._children.get(name)
        if node is None:
            raise FSError(f"not found: {path}")
        if node.is_dir and node._children:
            raise FSError(f"directory not empty: {path}")
        del parent._children[name]

    def move(self, src, dst):
        """
        Move or rename a node.
        Both the source and destination parent directories must be writable.
        The destination must not already exist.
        """
        src_parent, src_name = self._resolve_parent(src)
        dst_parent, dst_name = self._resolve_parent(dst)
        self._check_writable(src_parent)
        self._check_writable(dst_parent)
        node = src_parent._children.get(src_name)
        if node is None:
            raise FSError(f"not found: {src}")
        if dst_name in dst_parent._children:
            raise FSError(f"already exists: {dst}")
        # Relink the node into its new location
        del src_parent._children[src_name]
        node.name    = dst_name
        node._parent = dst_parent
        dst_parent._children[dst_name] = node

    def exists(self, path):
        """Return True if the path resolves to any node, False otherwise."""
        try:
            self._resolve(path)
            return True
        except FSError:
            return False

    def stat(self, path):
        """
        Return a dict describing the node at path.
        For directories: name, is_dir, visible, writable.
        For files:       name, is_dir, visible, size (bytes).
        """
        node = self._resolve(path)
        d = {
            'name':    node.name,
            'is_dir':  node.is_dir,
            'visible': node.visible,
        }
        if node.is_dir:
            d['writable'] = node.writable
        else:
            d['size'] = len(node._data)
        return d

    # ------------------------------------------------------------------
    # Flag control — the game mechanic
    # ------------------------------------------------------------------

    def set_visible(self, path, value: bool):
        """
        Show or hide a node in directory listings.
        Hidden nodes remain fully accessible by exact path.
        The game calls this when the player discovers a hidden room or object.
        """
        node = self._resolve(path)
        node.visible = value

    def set_writable(self, path, value: bool):
        """
        Lock or unlock a directory.
        When False, no file inside can be written, created, or deleted.
        The game calls this to lock a room (locking its objects in place)
        or unlock it (letting the player modify its contents).
        Only applies to directories — files inherit from their parent.
        """
        node = self._resolve(path)
        if not node.is_dir:
            raise FSError(f"writable flag is directory-only: {path}")
        node.writable = value

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self):
        """
        Serialise the entire filesystem to a plain dict.
        File contents are stored as hex strings so the dict is JSON-safe.
        Used to save and restore game state.
        """
        def _node(n):
            d = {'visible': n.visible}
            if n.is_dir:
                d['writable'] = n.writable
                d['children'] = {name: _node(child)
                                  for name, child in n._children.items()}
            else:
                d['data'] = n._data.hex()
            return d
        return _node(self._root)

    def from_dict(self, d):
        """
        Restore the filesystem from a dict produced by to_dict().
        Replaces the current tree entirely.
        """
        def _load(parent, name, d):
            if 'children' in d:
                # Directory node
                node = Node(name, visible=d['visible'],
                            writable=d.get('writable', True), is_dir=True)
                node._parent = parent
                for cname, cd in d['children'].items():
                    node._children[cname] = _load(node, cname, cd)
            else:
                # File node
                node = Node(name, visible=d['visible'], is_dir=False)
                node._data   = bytes.fromhex(d.get('data', ''))
                node._parent = parent
            return node
        self._root = _load(None, '/', d)
