"""Walkman / audio player support: finds a Sony Walkman (or another music player) that is plugged in as an ordinary drive, lists its music and
makes the folder a disc's tracks are copied into. WalkmanMixin is mixed into himd_app.Api (the page calls these methods on it).

A Sony Walkman shows up as a drive (or two: its own memory and the SD card) with a `default-capability.xml` file in the top folder, and the
music lives in its MUSIC folder, usually as Artist/Album/track. Another brand's player is found when it is a removable drive (Windows) or has a
Music folder, and any folder can also be chosen by hand. Nothing here converts or copies audio: player -> disc reads the files where they are
(the normal "Add tracks to the disc" check and write), and disc -> player uses the normal "Save to PC" with the player's folder as the
destination. This module only finds the player, reads its folder list and makes the destination folder."""
import os
import re
import shutil
import sys

AUDIO = {'.flac', '.wav', '.mp3', '.m4a', '.mp4', '.aac', '.wma', '.ogg', '.dsf', '.dff', '.aif', '.aiff'}   # what can be added to a disc (ffmpeg reads them)
SKIPPED_HINT = {'.oma': 'Sony ATRAC (.oma) files can be copy-protected and cannot be read here'}
IGNORE_DIRS = {'system volume information', '$recycle.bin', 'found.000', '.trashes', '.spotlight-v100', '.fseventsd', 'recycler'}
MUSIC_NAMES = ('music',)                                                       # the folder a player keeps its music in (any capitalisation)
_custom = {}                                                                   # folders chosen by hand this run: path -> player dict


def _natural(text):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r'(\d+)', text)]


def _read_capability(root):
    """Sony's own description of the player: (class, model, marketing name) or None when this is not a Walkman."""
    try:
        with open(os.path.join(root, 'default-capability.xml'), 'r', encoding='latin-1', errors='replace') as f:
            text = f.read(6000)
    except OSError:
        return None

    def tag(name):
        m = re.search(r'<%s>\s*([^<]*?)\s*</%s>' % (name, name), text)
        return m.group(1) if m else ''
    cls = tag('class')
    if 'walkman' not in cls.lower() and 'walkman' not in tag('marketingname').lower():
        return None
    return cls, tag('model'), tag('marketingname') or tag('model') or 'Walkman'


def _candidate_roots():
    """(root, removable): every drive (Windows) or volume (macOS) worth a look. removable is only known on Windows."""
    if sys.platform == 'win32':
        import ctypes
        for letter in 'DEFGHIJKLMNOPQRSTUVWXYZ':
            root = letter + ':\\'
            try:
                kind = ctypes.windll.kernel32.GetDriveTypeW(root)
            except Exception:
                kind = 3
            if kind in (0, 1, 4):                                              # unknown / no root / network drive: skip (slow to ask)
                continue
            yield root, kind == 2
    else:
        base = '/Volumes'
        try:
            names = sorted(os.listdir(base))
        except OSError:
            names = []
        for n in names:
            p = os.path.join(base, n)
            if os.path.realpath(p) == '/':                                     # the startup disk shows up here as a link to /
                continue
            yield p, False


def _music_dir(root):
    """The player's music folder (any capitalisation), or None."""
    try:
        for n in os.listdir(root):
            if n.lower() in MUSIC_NAMES and os.path.isdir(os.path.join(root, n)):
                return os.path.join(root, n)
    except OSError:
        pass
    return None


def _volume_label(root):
    if sys.platform == 'win32':
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(261)
            ctypes.windll.kernel32.GetVolumeInformationW(root, buf, 261, None, None, None, None, 0)
            return buf.value
        except Exception:
            return ''
    return os.path.basename(root.rstrip('/'))


def find_walkmen():
    """Every player found: Sony Walkmen first (marked sony), then other removable drives / volumes with a Music folder, then folders chosen by hand."""
    sony, other = [], []
    for root, removable in _candidate_roots():
        try:
            music = _music_dir(root)
            cap = _read_capability(root) if os.path.isfile(os.path.join(root, 'default-capability.xml')) else None
            if not cap and not music and not removable:
                continue
            usage = shutil.disk_usage(root)
            item = {'root': root, 'sony': bool(cap), 'custom': False, 'label': _volume_label(root), 'music': music or '',
                    'total': usage.total, 'free': usage.free}
            if cap:
                item.update(model=cap[1], name=cap[2])
                sony.append(item)
            else:
                item.update(model='', name='Music player')
                other.append(item)
        except OSError:
            continue
    return sony + other + list(_custom.values())


def _player(root):
    return next((w for w in find_walkmen() if w['root'] == root), None)


def _music_root(p):
    """Where the music is read from / written to for this player. A Sony Walkman always uses its MUSIC folder; another player its Music folder
    if it has one, else the top of the drive; a folder chosen by hand is used as it is."""
    if p.get('custom'):
        return p['root']
    return p['music'] or (os.path.join(p['root'], 'MUSIC') if p['sony'] else p['root'])


def list_music(p):
    """Every folder in the player's music folder that has audio files: [{rel, name, tracks: [{path, name, bytes}]}], plus how many files were skipped."""
    music = _music_root(p)
    if not os.path.isdir(music):
        return {'error': 'This player has no music folder.'}
    groups, skipped = [], {}
    for here, dirs, files in os.walk(music):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d.lower() not in IGNORE_DIRS]
        tracks = []
        for fn in files:
            ext = os.path.splitext(fn)[1].lower()
            if fn.startswith('.') or fn.startswith('._'):
                continue
            if ext in AUDIO:
                path = os.path.join(here, fn)
                try:
                    size = os.path.getsize(path)
                except OSError:
                    continue
                tracks.append({'path': path, 'name': os.path.splitext(fn)[0], 'bytes': size})
            elif ext in SKIPPED_HINT:
                skipped[ext] = skipped.get(ext, 0) + 1
        if tracks:
            tracks.sort(key=lambda t: _natural(t['name']))
            rel = os.path.relpath(here, music)
            groups.append({'rel': '' if rel == '.' else rel.replace('\\', '/'), 'name': os.path.basename(here) if rel != '.' else os.path.basename(music.rstrip('/\\')) or 'Music', 'tracks': tracks})
    groups.sort(key=lambda g: _natural(g['rel']))
    return {'groups': groups, 'skipped': [{'ext': k, 'count': v, 'why': SKIPPED_HINT[k]} for k, v in skipped.items()]}


def _clean(name, fallback):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', (name or '').strip()).strip(' .')
    return (name or fallback)[:80].rstrip(' .')


class WalkmanMixin:
    def walkman_find(self):
        try:
            return {'players': find_walkmen()}
        except Exception as exc:
            self.log('walkman_find failed: %r' % (exc,))
            return {'error': 'Could not look for a player: %s' % exc}

    def walkman_pick_folder(self):
        """Choose the music folder of a player by hand (any drive or folder). It then appears in the list for this run."""
        try:
            import webview
            kind = getattr(getattr(webview, 'FileDialog', None), 'FOLDER', None) or webview.FOLDER_DIALOG
            paths = self._window.create_file_dialog(kind)
            if not paths:
                return {'cancelled': True}
            folder = paths if isinstance(paths, str) else paths[0]
            if not os.path.isdir(folder):
                return {'error': 'That is not a folder.'}
            usage = shutil.disk_usage(folder)
            _custom[folder] = {'root': folder, 'sony': False, 'custom': True, 'label': os.path.basename(folder.rstrip('/\\')) or folder,
                               'music': folder, 'total': usage.total, 'free': usage.free, 'model': '', 'name': 'Chosen folder'}
            return {'root': folder}
        except Exception as exc:
            self.log('walkman_pick_folder failed: %r' % (exc,))
            return {'error': 'Could not choose that folder: %s' % exc}

    def walkman_list(self, root):
        p = _player(root)
        if not p:
            return {'error': 'That player is no longer connected.'}
        try:
            return list_music(p)
        except Exception as exc:
            self.log('walkman_list failed: %r' % (exc,))
            return {'error': 'Could not read the player: %s' % exc}

    def walkman_target(self, root, artist, album):
        """The folder <music folder>/<artist>/<album> on that player, made if it is not there yet. Returns its path and the free space."""
        try:
            p = _player(root)
            if not p:
                return {'error': 'That player is no longer connected.'}
            music = _music_root(p)
            if not os.path.isdir(music):
                os.makedirs(music, exist_ok=True)
            folder = os.path.join(music, _clean(artist, 'Unknown Artist'), _clean(album, 'Unknown Album'))
            if os.path.commonpath([os.path.abspath(folder), os.path.abspath(music)]) != os.path.abspath(music):
                return {'error': 'That folder name is not allowed.'}
            os.makedirs(folder, exist_ok=True)
            return {'folder': folder, 'free': shutil.disk_usage(music).free}
        except Exception as exc:
            self.log('walkman_target failed: %r' % (exc,))
            return {'error': 'Could not make the folder on the player: %s' % exc}
