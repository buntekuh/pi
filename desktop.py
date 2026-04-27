"""
desktop.py — Titania desktop environment

Mac OS 9 / Atari ST inspired: teal background, drive icons on the right,
overlapping explorer windows with icon-grid browsing.
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import pygame
from pathlib import Path

_ACTIONS_PATH = Path(__file__).parent / 'etc' / 'actions.json'

def load_actions():
    try:
        with open(_ACTIONS_PATH) as f:
            return json.load(f)
    except OSError:
        return {}

def actions_for(filename, actions):
    ext = Path(filename).suffix.lower()
    return actions.get(ext) or actions.get('*') or []

try:
    from fs import FS
except ImportError:
    FS = None

# ── Palette ──────────────────────────────────────────────────────────────────
# (0x16, 0x60, 0x84)    teal
# (0x4b, 0x60, 0x7f)    blue
# 4381ac
C_BG        = (0x43, 0x81, 0xac)   # teal desktop
C_TITLE     = (0x00, 0x00, 0x00)   # steel-blue title bar
C_STRIPE    = (0x38, 0x4c, 0x63)   # darker stripe in title bar
C_TITLE_TXT = (0xe8, 0xd8, 0xc9)   # cream text on title bar
C_BODY      = (0xe8, 0xd8, 0xc9)   # cream window body
C_PATHBAR   = (0xd0, 0xc2, 0xb0)   # slightly darker path bar
C_BORDER    = (0x18, 0x18, 0x18)   # near-black border
C_SELECT    = (0xf3, 0x70, 0x1e)   # orange selection
C_LABEL     = (0x18, 0x18, 0x18)
C_LABEL_SEL = (0xff, 0xff, 0xff)

# ── Layout ───────────────────────────────────────────────────────────────────

SCREEN_W = 1024
SCREEN_H = 768
TITLE_H  = 28
PATH_H   = 22
BORDER   = 2
WIN_B1    = 3                        # outer black border
WIN_BG    = 3                        # desktop-colour gap
WIN_B2    = 1                        # inner black border
WIN_INSET = WIN_B1 + WIN_BG + WIN_B2 # total content inset
ICON_SZ  = 48
CELL_W   = 90
CELL_H   = 82
PAD      = 14
DBL_MS   = 380   # double-click interval in milliseconds

_ICON_DIR = Path(__file__).parent / 'assets' / 'img'


def _draw_window_border(surf, x, y, w, h):
    """Three-layer window border: outer black / desktop-colour gap / inner black."""
    pygame.draw.rect(surf, C_BORDER, (x, y, w, h), WIN_B1)
    pygame.draw.rect(surf, C_BG,
                     (x + WIN_B1, y + WIN_B1, w - WIN_B1 * 2, h - WIN_B1 * 2), WIN_BG)
    pygame.draw.rect(surf, C_BORDER,
                     (x + WIN_B1 + WIN_BG, y + WIN_B1 + WIN_BG,
                      w - (WIN_B1 + WIN_BG) * 2, h - (WIN_B1 + WIN_BG) * 2), WIN_B2)


def _load_icon(rel, size=ICON_SZ):
    try:
        s = pygame.image.load(str(_ICON_DIR / rel)).convert_alpha()
        return pygame.transform.smoothscale(s, (size, size))
    except Exception:
        s = pygame.Surface((size, size), pygame.SRCALPHA)
        s.fill((180, 160, 140, 255))
        return s

_icon_up    = None
_icon_close = None

def _get_ui_icons():
    global _icon_up, _icon_close
    if _icon_up is None:
        _icon_up    = _load_icon('up.png',    size=16)
        _icon_close = _load_icon('close.png', size=16)

# ── Filesystem mounts ─────────────────────────────────────────────────────────

class HostMount:
    """Wraps the host machine's filesystem (pathlib)."""
    label = 'Host'
    supports_actions = False

    def __init__(self, root: Path):
        self._root = root
        self._drive_icon = self._dir_icon = self._file_icon = None

    def _load(self):
        if self._drive_icon is None:
            self._drive_icon = _load_icon('directories1_1.png')
            self._dir_icon   = _load_icon('directories1_1.png')
            self._file_icon  = _load_icon('files1_1.png')

    @property
    def drive_icon(self): self._load(); return self._drive_icon
    @property
    def dir_icon(self):   self._load(); return self._dir_icon
    @property
    def file_icon(self):  self._load(); return self._file_icon

    def ls(self, path='/', **_):
        p = self._root if path == '/' else self._root / path.lstrip('/')
        try:
            entries = sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
            return [(e.name, e.is_dir()) for e in entries if not e.name.startswith('.')]
        except OSError:
            return []

    def read_file(self, path, **_):
        p = self._root if path == '/' else self._root / path.lstrip('/')
        return p.read_bytes()

    def write_file(self, path, data, **_):
        p = self._root if path == '/' else self._root / path.lstrip('/')
        p.write_bytes(data)


# ── M56 connection layer ──────────────────────────────────────────────────────
#
# All communication with the M56 goes through a Connection.
# EmulatorConnection wraps a FS object and formats responses as the text
# protocol. SerialConnection (future) will do the same over a serial port.
#
# Protocol:
#   request:  single line, "VERB arg\n"
#   response: one entry per line, terminated by "OK\n" or "ERR reason\n"
#
#   ls /path  →  name D is_hidden is_writable   (directory)
#             →  name size is_hidden             (file)
#             →  OK


class EmulatorConnection:
    """Speaks the M56 text protocol against an in-process FS object."""

    def __init__(self, fs):
        self._fs = fs

    def send(self, cmd: str) -> str:
        # Command format: "PORT VERB [args...]"
        parts = cmd.strip().split()
        if len(parts) < 2:
            return 'ERR empty 0\n'
        port, verb, args = parts[0], parts[1], parts[2:]
        if verb == 'ls':
            return self._ls(args[0] if args else '/', port)
        if verb == 'read':
            return self._read(args[0] if args else '/', port)
        if verb == 'write':
            # format: PORT write PATH SIZE HEXDATA
            path, hex_data = args[0], args[2] if len(args) > 2 else ''
            return self._write(path, hex_data, port)
        return f'ERR unknown {verb} {port}\n'

    def _ls(self, path: str, port: str) -> str:
        try:
            names = self._fs.ls(path)
            lines = []
            for name in names:
                cp = path.rstrip('/') + '/' + name
                st = self._fs.stat(cp)
                hidden = str(not st['visible']).lower()
                if st['is_dir']:
                    lines.append(f"{name} D {hidden} {str(st['writable']).lower()}")
                else:
                    lines.append(f"{name} {st['size']} {hidden}")
            lines.append(f'OK {port}')
            return '\n'.join(lines) + '\n'
        except Exception as e:
            return f'ERR {e} {port}\n'

    def _read(self, path: str, port: str) -> str:
        try:
            data = self._fs.read(path)
            hex_data = data.hex()
            return f'SIZE {len(data)}\n{hex_data}\nOK {port}\n'
        except Exception as e:
            return f'ERR {e} {port}\n'

    def _write(self, path: str, hex_data: str, port: str) -> str:
        try:
            data = bytes.fromhex(hex_data)
            if self._fs.exists(path):
                self._fs.write(path, data)
            else:
                self._fs.create(path, data)
            return f'OK {port}\n'
        except Exception as e:
            return f'ERR {e} {port}\n'


class M56Mount:
    """File browser mount for the M56. Talks only through a Connection."""
    label = 'M56'
    supports_actions = True

    def __init__(self, connection):
        self._conn = connection
        self._drive_icon = self._dir_icon = self._file_icon = None

    def _load(self):
        if self._drive_icon is None:
            self._drive_icon = _load_icon('drives1_2.png')
            self._dir_icon   = _load_icon('directories1_1.png')
            self._file_icon  = _load_icon('files1_1.png')

    @property
    def drive_icon(self): self._load(); return self._drive_icon
    @property
    def dir_icon(self):   self._load(); return self._dir_icon
    @property
    def file_icon(self):  self._load(); return self._file_icon

    def ls(self, path='/', port=0):
        response = self._conn.send(f'{port} ls {path}')
        entries = []
        for line in response.splitlines():
            if line == '' or line.startswith('OK') or line.startswith('ERR'):
                break
            parts = line.split()
            if len(parts) < 2:
                continue
            name, second = parts[0], parts[1]
            entries.append((name, second == 'D'))
        return entries

    def read_file(self, path, port=0):
        response = self._conn.send(f'{port} read {path}')
        lines = response.splitlines()
        for i, line in enumerate(lines):
            if line.startswith('SIZE') and i + 1 < len(lines):
                return bytes.fromhex(lines[i + 1])
        return None

    def write_file(self, path, data, port=0):
        hex_data = data.hex()
        self._conn.send(f'{port} write {path} {len(data)} {hex_data}')

# ── Context menu ─────────────────────────────────────────────────────────────

MENU_ITEM_H = 22
MENU_W      = 140
MENU_PAD    = 8


class ContextMenu:

    def __init__(self, actions, pos, screen_size):
        self._actions  = actions   # [{'name': ..., 'params': ...}]
        self._hovered  = None
        h = MENU_ITEM_H * len(actions) + BORDER * 2
        # Keep menu on screen
        x = min(pos[0], screen_size[0] - MENU_W - 4)
        y = min(pos[1], screen_size[1] - h - 4)
        self.rect = pygame.Rect(x, y, MENU_W, h)

    def draw(self, surf, font):
        pygame.draw.rect(surf, C_BODY, self.rect)
        for i, action in enumerate(self._actions):
            item_r = pygame.Rect(self.rect.x, self.rect.y + BORDER + i * MENU_ITEM_H,
                                 MENU_W, MENU_ITEM_H)
            if i == self._hovered:
                pygame.draw.rect(surf, C_SELECT, item_r)
            label_col = C_LABEL_SEL if i == self._hovered else C_LABEL
            txt = font.render(action['name'], True, label_col)
            surf.blit(txt, (item_r.x + MENU_PAD, item_r.y + (MENU_ITEM_H - txt.get_height()) // 2))
        pygame.draw.rect(surf, C_BORDER, self.rect, BORDER)

    def handle_event(self, event):
        """Returns action dict when selected, 'dismiss' when clicking outside, None otherwise."""
        if event.type == pygame.MOUSEMOTION:
            self._hovered = self._item_at(event.pos)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            i = self._item_at(event.pos)
            if i is not None:
                return self._actions[i]
            return 'dismiss'
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            return 'dismiss'
        return None

    def _item_at(self, pos):
        if not self.rect.collidepoint(pos):
            return None
        i = (pos[1] - self.rect.y - BORDER) // MENU_ITEM_H
        if 0 <= i < len(self._actions):
            return i
        return None


# ── Error dialog ─────────────────────────────────────────────────────────────

DIALOG_W   = 300
DIALOG_PAD = 16
BTN_H      = 26
BTN_W      = 64


class ErrorDialog:

    def __init__(self, message, screen_size):
        self._message = message
        lines = self._wrap(message, 32)
        body_h = DIALOG_PAD + len(lines) * 18 + DIALOG_PAD + BTN_H + DIALOG_PAD
        h = TITLE_H + body_h
        x = (screen_size[0] - DIALOG_W) // 2
        y = (screen_size[1] - h) // 2
        self.rect = pygame.Rect(x, y, DIALOG_W, h)
        self._lines = lines

    def _wrap(self, text, width):
        words, lines, line = text.split(), [], ''
        for w in words:
            if len(line) + len(w) + 1 <= width:
                line = (line + ' ' + w).strip()
            else:
                if line:
                    lines.append(line)
                line = w
        if line:
            lines.append(line)
        return lines

    @property
    def _btn_rect(self):
        bx = self.rect.x + (DIALOG_W - BTN_W) // 2
        by = self.rect.bottom - DIALOG_PAD - BTN_H
        return pygame.Rect(bx, by, BTN_W, BTN_H)

    def draw(self, surf, fonts):
        ft, _, fl = fonts
        x, y = self.rect.topleft
        w    = self.rect.width

        pygame.draw.rect(surf, C_BODY, self.rect)
        pygame.draw.rect(surf, C_TITLE, (x, y, w, TITLE_H))
        title_s = ft.render('ERROR', True, C_TITLE_TXT)
        surf.blit(title_s, title_s.get_rect(center=(x + w // 2, y + TITLE_H // 2)))

        for i, line in enumerate(self._lines):
            ls = fl.render(line, True, C_LABEL)
            surf.blit(ls, (x + DIALOG_PAD, y + TITLE_H + DIALOG_PAD + i * 18))

        btn_r = self._btn_rect
        pygame.draw.rect(surf, C_PATHBAR, btn_r)
        pygame.draw.rect(surf, C_BORDER, btn_r, BORDER)
        ok_s = fl.render('OK', True, C_LABEL)
        surf.blit(ok_s, ok_s.get_rect(center=btn_r.center))

        _draw_window_border(surf, *self.rect.topleft, *self.rect.size)

    def handle_event(self, event):
        """Returns 'dismiss' when OK is clicked or Escape pressed, else None."""
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._btn_rect.collidepoint(event.pos):
                return 'dismiss'
        elif event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_ESCAPE):
            return 'dismiss'
        return None


# ── Explorer window ───────────────────────────────────────────────────────────

class ExplorerWindow:

    def __init__(self, mount, port=0, pos=(80, 60), size=(500, 380), actions=None):
        self.mount    = mount
        self.port     = port
        self.pos      = list(pos)
        self.size     = list(size)
        self._actions = actions or {}
        self.path     = '/'
        self._stack   = []
        self.scroll_y = 0
        self.selected = None
        self._dragging  = False
        self._drag_off  = (0, 0)
        self._entries   = []
        self._last_t    = 0
        self._last_name = None
        self._menu      = None
        self._dialog    = None
        self.drag_file  = None   # (name, icon) set when a file is clicked, cleared on release
        self._refresh()

    @property
    def rect(self):
        return pygame.Rect(*self.pos, *self.size)

    @property
    def _content_rect(self):
        I = WIN_INSET
        return pygame.Rect(
            self.pos[0] + I,
            self.pos[1] + I + TITLE_H + PATH_H,
            self.size[0] - I * 2,
            self.size[1] - I * 2 - TITLE_H - PATH_H,
        )

    def _refresh(self):
        self._entries = self.mount.ls(self.path, port=self.port)
        self.scroll_y = 0
        self.selected = None
        self._last_name = None

    def _path_label(self):
        return f'{self.mount.label}:{self.path}'

    @property
    def _up_rect(self):
        I = WIN_INSET
        return pygame.Rect(self.pos[0] + I, self.pos[1] + I + TITLE_H, PATH_H, PATH_H)

    def _go_up(self):
        if self.path != '/':
            parent = str(Path(self.path).parent)
            self.path = parent if parent != '.' else '/'
            self._refresh()

    def _cols(self):
        return max(1, (self._content_rect.width - PAD) // CELL_W)

    def _grid(self):
        cr = self._content_rect
        cols = self._cols()
        out = []
        for i, (name, is_dir) in enumerate(self._entries):
            col = i % cols
            row = i // cols
            x = cr.x + PAD + col * CELL_W
            y = cr.y + PAD + row * CELL_H - self.scroll_y
            out.append((name, is_dir, pygame.Rect(x, y, CELL_W, CELL_H)))
        return out

    def _max_scroll(self):
        if not self._entries:
            return 0
        cols = self._cols()
        rows = (len(self._entries) + cols - 1) // cols
        return max(0, rows * CELL_H + PAD * 2 - self._content_rect.height)

    def draw(self, surf, fonts, active=True):
        ft, fp, fl = fonts
        x, y = self.pos
        w, h = self.size
        I = WIN_INSET

        # Window body background
        pygame.draw.rect(surf, C_BODY, (x + I, y + I + TITLE_H, w - I * 2, h - I * 2 - TITLE_H))

        # Title bar
        pygame.draw.rect(surf, C_TITLE, (x + I, y + I, w - I * 2, TITLE_H))
        for sx in range(x + I + 8, x + w - I - TITLE_H - 4, 5):
            pygame.draw.line(surf, C_STRIPE, (sx, y + I + 6), (sx, y + I + TITLE_H - 6))
        title_s = ft.render(self.mount.label.upper(), True, C_TITLE_TXT)
        tr = title_s.get_rect(center=(x + I + (w - I * 2 - TITLE_H) // 2, y + I + TITLE_H // 2))
        pygame.draw.rect(surf, C_TITLE, tr.inflate(12, 6))
        surf.blit(title_s, tr)

        # Close button
        _get_ui_icons()
        close_r = pygame.Rect(x + w - I - TITLE_H, y + I, TITLE_H, TITLE_H)
        pygame.draw.rect(surf, C_BORDER, close_r, BORDER)
        surf.blit(_icon_close, _icon_close.get_rect(center=close_r.center))

        # Path bar
        pygame.draw.rect(surf, C_PATHBAR, (x + I, y + I + TITLE_H, w - I * 2, PATH_H))
        pygame.draw.line(surf, C_BORDER, (x + I, y + I + TITLE_H), (x + w - I, y + I + TITLE_H))
        pygame.draw.line(surf, C_BORDER, (x + I, y + I + TITLE_H + PATH_H), (x + w - I, y + I + TITLE_H + PATH_H))

        # Up button
        at_root = self.path == '/'
        up_r = self._up_rect
        pygame.draw.rect(surf, C_BORDER, up_r, BORDER)
        icon = _icon_up.copy() if at_root else _icon_up
        if at_root:
            icon.set_alpha(80)
        surf.blit(icon, icon.get_rect(center=up_r.center))

        # Path label (starts after the up button)
        ps = fp.render(self._path_label(), True, C_LABEL)
        surf.blit(ps, (x + I + PATH_H + 4, y + I + TITLE_H + (PATH_H - ps.get_height()) // 2))

        # Icon grid (clipped to content area)
        cr = self._content_rect
        clip = surf.get_clip()
        surf.set_clip(cr)

        for name, is_dir, cell_r in self._grid():
            if cell_r.bottom < cr.top or cell_r.top > cr.bottom:
                continue
            selected = name == self.selected
            icon = self.mount.dir_icon if is_dir else self.mount.file_icon

            if selected:
                pygame.draw.rect(surf, C_SELECT, cell_r.inflate(-6, -4), border_radius=3)

            surf.blit(icon, (cell_r.x + (CELL_W - ICON_SZ) // 2, cell_r.y + 4))

            lbl = fl.render(name[:16], True, C_LABEL_SEL if selected else C_LABEL)
            surf.blit(lbl, (cell_r.x + (CELL_W - lbl.get_width()) // 2,
                            cell_r.y + 4 + ICON_SZ + 2))

        surf.set_clip(clip)

        # Grey overlay on inactive windows
        if not active:
            dim = pygame.Surface((w, h), pygame.SRCALPHA)
            dim.fill((0, 0, 0, 90))
            surf.blit(dim, (x, y))

        # Layered border: outer black / desktop-colour gap / inner black
        _draw_window_border(surf, x, y, w, h)

        # Context menu and error dialog float above everything
        if self._menu:
            self._menu.draw(surf, fl)
        if self._dialog:
            self._dialog.draw(surf, fonts)

    def _launch(self, name, action):
        stem = Path(name).stem
        params = action['params'].replace('NAME', stem)
        filepath = self.path.rstrip('/') + '/' + name
        print(f'[action] {action["name"]}: {filepath} {params}'.strip())

    def handle_event(self, event):
        """Returns 'close', 'raise', or None."""
        # Dialog eats all events while open
        if self._dialog:
            if self._dialog.handle_event(event) == 'dismiss':
                self._dialog = None
            return 'raise'

        # Menu eats events while open
        if self._menu:
            result = self._menu.handle_event(event)
            if result == 'dismiss':
                self._menu = None
            elif result is not None:
                self._launch(self.selected, result)
                self._menu = None
            return 'raise'

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            pos = event.pos
            I = WIN_INSET
            close_r = pygame.Rect(self.pos[0] + self.size[0] - I - TITLE_H,
                                  self.pos[1] + I, TITLE_H, TITLE_H)
            title_r = pygame.Rect(self.pos[0] + I, self.pos[1] + I,
                                  self.size[0] - I * 2 - TITLE_H, TITLE_H)

            if close_r.collidepoint(pos):
                return 'close'
            if self._up_rect.collidepoint(pos):
                self._go_up()
                return 'raise'
            if title_r.collidepoint(pos):
                self._dragging = True
                self._drag_off = (pos[0] - self.pos[0], pos[1] - self.pos[1])
                return 'raise'
            if self.rect.collidepoint(pos):
                cr = self._content_rect
                if cr.collidepoint(pos):
                    now = pygame.time.get_ticks()
                    hit = None
                    for name, is_dir, cell_r in self._grid():
                        if cell_r.collidepoint(pos):
                            hit = (name, is_dir)
                            break
                    if hit:
                        name, is_dir = hit
                        double = (name == self._last_name and now - self._last_t < DBL_MS)
                        self.selected = name
                        self._last_name = name
                        self._last_t = now
                        if not is_dir:
                            icon = self.mount.file_icon
                            self.drag_file = (name, icon)
                        if double and is_dir:
                            self._stack.append(self.path)
                            self.path = self.path.rstrip('/') + '/' + name
                            self._refresh()
                        elif double and not is_dir:
                            if not self.mount.supports_actions:
                                self._dialog = ErrorDialog(
                                    f'"{name}" lives on the host. Drop it into the M56 folder to run it.',
                                    (SCREEN_W, SCREEN_H))
                            else:
                                acts = actions_for(name, self._actions)
                                if acts:
                                    self._launch(name, acts[0])
                    else:
                        self.selected = None
                        self._last_name = None
                return 'raise'

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
            pos = event.pos
            if self.rect.collidepoint(pos):
                hit = None
                for name, is_dir, cell_r in self._grid():
                    if cell_r.collidepoint(pos):
                        hit = (name, is_dir)
                        break
                if hit:
                    self.selected = hit[0]
                    name, is_dir = hit
                    if not is_dir and self.mount.supports_actions:
                        acts = actions_for(name, self._actions)
                        if acts:
                            self._menu = ContextMenu(acts, pos, (SCREEN_W, SCREEN_H))
                else:
                    self.selected = None
                return 'raise'

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._dragging = False
            self.drag_file = None

        elif event.type == pygame.MOUSEMOTION:
            if self._dragging:
                self.pos[0] = event.pos[0] - self._drag_off[0]
                self.pos[1] = event.pos[1] - self._drag_off[1]

        elif event.type == pygame.MOUSEWHEEL:
            self.scroll_y = max(0, min(self._max_scroll(),
                                       self.scroll_y - event.y * 24))

        return None

# ── Desktop ───────────────────────────────────────────────────────────────────

_SIDE_SZ   = 48
_SIDE_CELL = _SIDE_SZ + 22
_SIDE_X    = SCREEN_W - 16 - _SIDE_SZ
_SIDE_Y    = 20


class Desktop:

    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        pygame.display.set_caption('Titania')
        self.clock = pygame.time.Clock()

        self._fonts = (
            pygame.font.SysFont('dejavusansmono,couriernew,monospace', 13, bold=True),
            pygame.font.SysFont('dejavusansmono,couriernew,monospace', 11),
            pygame.font.SysFont('dejavusansmono,couriernew,monospace', 10),
        )

        self._actions = load_actions()

        self._mounts = [HostMount(Path.home())]
        if FS is not None:
            fs = FS()
            fs.mkdir('/home')
            fs.create('/home/hello.asm', b'; hello world\n')
            fs.mkdir('/games')
            fs.create('/games/adventure.grue', b'room start\n  "A dark place."\n')
            self._mounts.append(M56Mount(EmulatorConnection(fs)))

        self._windows = []          # bottom → top
        self._sidebar_click = {}    # mount index → last click time
        self._drag = None           # {'win', 'name', 'icon', 'ghost', 'pos'} or None

    def _sidebar_rects(self):
        return [
            pygame.Rect(_SIDE_X, _SIDE_Y + i * _SIDE_CELL, _SIDE_SZ, _SIDE_SZ + 16)
            for i in range(len(self._mounts))
        ]

    def _draw_sidebar(self):
        fl = self._fonts[2]
        for mount, r in zip(self._mounts, self._sidebar_rects()):
            self.screen.blit(mount.drive_icon, (r.x, r.y))
            lbl = fl.render(mount.label, True, (0xff, 0xff, 0xff))
            self.screen.blit(lbl, (r.x + (_SIDE_SZ - lbl.get_width()) // 2,
                                   r.y + _SIDE_SZ + 2))

    def _open_window(self, mount):
        n = len(self._windows)
        pos = (50 + (n * 28) % 180, 50 + (n * 28) % 130)
        self._windows.append(ExplorerWindow(mount, port=n, pos=pos, actions=self._actions))

    def _raise(self, win):
        self._windows.remove(win)
        self._windows.append(win)

    def _drop(self, src_win, name, target_win):
        src_path = src_win.path.rstrip('/') + '/' + name
        dst_path = target_win.path.rstrip('/') + '/' + name
        try:
            data = src_win.mount.read_file(src_path, port=src_win.port)
            if data is None:
                return
            target_win.mount.write_file(dst_path, data, port=target_win.port)
            target_win._refresh()
        except Exception as e:
            target_win._dialog = ErrorDialog(f'Drop failed: {e}', (SCREEN_W, SCREEN_H))

    def _draw_drag(self):
        if not self._drag:
            return
        ghost = self._drag['ghost']
        x, y = self._drag['pos']
        self.screen.blit(ghost, (x - ICON_SZ // 2, y - ICON_SZ // 2))
        # Highlight the window under the cursor (if different mount)
        for win in reversed(self._windows):
            if win is not self._drag['win'] and win.rect.collidepoint((x, y)):
                pygame.draw.rect(self.screen, C_SELECT, win.rect, 3)
                break

    def run(self):
        while True:
            self.clock.tick(60)

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit(); sys.exit()

                # Sidebar: double-click to open explorer
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    now = pygame.time.get_ticks()
                    for i, r in enumerate(self._sidebar_rects()):
                        if r.collidepoint(event.pos):
                            prev = self._sidebar_click.get(i, 0)
                            if now - prev < DBL_MS:
                                self._open_window(self._mounts[i])
                                self._sidebar_click[i] = 0
                            else:
                                self._sidebar_click[i] = now
                            break

                # Window events
                if event.type == pygame.MOUSEBUTTONDOWN and event.button in (1, 3):
                    for win in reversed(self._windows):
                        result = win.handle_event(event)
                        if result == 'close':
                            self._windows.remove(win)
                            break
                        elif result == 'raise':
                            self._raise(win)
                            break

                elif event.type == pygame.MOUSEMOTION:
                    if event.buttons[0] and not self._drag:
                        # Start drag if a file was clicked in the topmost window
                        if self._windows:
                            top = self._windows[-1]
                            if top.drag_file:
                                name, icon = top.drag_file
                                ghost = icon.copy()
                                ghost.set_alpha(160)
                                self._drag = {'win': top, 'name': name,
                                              'ghost': ghost, 'pos': event.pos}
                    if self._drag:
                        self._drag['pos'] = event.pos
                    else:
                        for win in self._windows:
                            win.handle_event(event)

                elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    if self._drag:
                        pos = event.pos
                        src = self._drag['win']
                        name = self._drag['name']
                        for win in reversed(self._windows):
                            if win is not src and win.rect.collidepoint(pos):
                                if win.mount is not src.mount:
                                    self._drop(src, name, win)
                                break
                        self._drag = None
                        src.drag_file = None
                    else:
                        for win in self._windows:
                            win.handle_event(event)

                elif event.type == pygame.MOUSEWHEEL:
                    mpos = pygame.mouse.get_pos()
                    for win in reversed(self._windows):
                        if win.rect.collidepoint(mpos):
                            win.handle_event(event)
                            break
                else:
                    for win in self._windows:
                        win.handle_event(event)

            self.screen.fill(C_BG)
            self._draw_sidebar()
            for win in self._windows:
                win.draw(self.screen, self._fonts, active=(win is self._windows[-1]))
            self._draw_drag()
            pygame.display.flip()


if __name__ == '__main__':
    Desktop().run()
