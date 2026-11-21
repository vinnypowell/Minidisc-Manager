"""Disc packages: a whole disc (audio exactly as read, titles, groups, disc name, picture, disc label, lyrics, video links, group pictures) saved as ONE
.mdpack file, which another copy of the app can open and write to a blank disc of the same kind. PackageMixin is mixed into himd_app.Api.

A package is a zip holding what Clone disc keeps on the PC while a copy waits for its disc (manifest.json + stage/...), a small header (mdpack.json)
and extras.json (lyrics, video links and group pictures for the tracks in it). Opening one puts it back in CLONE_DIR as a waiting copy, so the
ordinary Clone disc writer (with its byte-for-byte check on a Hi-MD disc) does the writing. Every file is checked against its SHA-256 on the way in."""
import datetime
import hashlib
import json
import os
import re
import shutil
import zipfile

import webview
import lyrics
from mdm_paths import BACKUP_DIR, CLONE_DIR

PACKAGE_KIND = 'disc-package'
PACKAGE_VERSION = 1
EXT = '.mdpack'
MAX_JSON = 80 * 1000 * 1000          # lyrics + group pictures are small; anything bigger than this in a json entry is not ours


def _sha(path):
    d = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            d.update(chunk)
    return d.hexdigest()


class PackageMixin:
    # -- what travels with the tracks -------------------------------------------------------------
    def _pkg_extras(self, m):
        """Lyrics, video links and group pictures of the tracks in the saved copy `m`, from this PC's own stores."""
        out = {'lyrics': [], 'videos': [], 'groupart': {}}
        ly, vd = self._ly_read(), self._video_read()
        for it in m['tracks']:
            title, artist, secs = it.get('title') or '', it.get('artist') or '', it['seconds']
            if not title:
                continue
            e = self._ly_find(ly, title, artist, secs)
            if e and e not in out['lyrics']:
                out['lyrics'].append(e)
            v = next((x for x in vd if lyrics._same(x, title, artist, secs)), None)
            if v and v not in out['videos']:
                out['videos'].append(v)
        if m.get('type') != 'netmd' and m.get('sourceId'):
            art = self._ga_read().get(m['sourceId']) or {}
            names = {g['title'] for g in m.get('groups', []) if g.get('title')}
            out['groupart'] = {n: art[n] for n in names if n in art}
        return out

    @staticmethod
    def _pkg_files(m):
        """Every file of the saved copy that belongs in the package: [(name inside the zip, path)]."""
        stage = os.path.join(CLONE_DIR, 'stage')
        names = []
        for it in m['tracks']:
            names.append(it['file'])
            if it.get('spatial'):
                names.append(it['spatial']['file'])
        for key in ('cover', 'label'):
            if m.get(key):
                names.append(m[key])
        return [('stage/' + n, os.path.join(stage, n)) for n in names]

    def package_choose_path(self, title=''):
        """Asks where the package file should be saved (the page does this first, before the disc is read, so the long read is never wasted on a
        cancelled dialog). Returns {path} or {cancelled}. Nothing is written."""
        kind = getattr(getattr(webview, 'FileDialog', None), 'SAVE', None) or webview.SAVE_DIALOG
        safe = re.sub(r'[\\/:*?"<>|]+', ' ', str(title or '')).strip()[:80] or 'disc'
        start = os.path.join(os.path.expanduser('~'), 'Documents')
        path = self._window.create_file_dialog(kind, directory=start if os.path.isdir(start) else '', save_filename=safe + EXT, file_types=('MiniDisc package (*%s)' % EXT,))
        if not path:
            return {'cancelled': True}
        path = path if isinstance(path, str) else path[0]
        if not path.lower().endswith(EXT):
            path += EXT
        return {'path': path}

    def package_export(self, path=None):
        """Writes the waiting PC copy (see Clone disc) plus the extras as one .mdpack file at `path` (asks where, if no path is given). Reads no disc."""
        m = self._clone_manifest()
        if not m:
            return {'error': 'There is no saved copy of a disc to make a package from. Use Export disc package… to copy a disc first.'}
        if not path:
            r = self.package_choose_path(m.get('discTitle') or '')
            if 'path' not in r:
                return r
            path = r['path']
        path = str(path)
        if not path.lower().endswith(EXT):
            path += EXT
        if not os.path.isdir(os.path.dirname(os.path.abspath(path))):
            return {'error': 'The folder for the package file does not exist any more. Choose another place.'}
        files = self._pkg_files(m)
        for _, p in files:
            if not os.path.isfile(p):
                return {'error': 'The saved copy is incomplete (%s is missing). Discard it and copy the disc again.' % os.path.basename(p)}
        extras = self._pkg_extras(m)
        header = {'app': 'MiniDiscManager', 'kind': PACKAGE_KIND, 'version': PACKAGE_VERSION, 'created': datetime.datetime.now().isoformat(timespec='seconds'),
                  'type': m.get('type') or 'himd', 'title': m.get('discTitle') or '', 'tracks': len(m['tracks']), 'seconds': m['seconds'], 'bytes': m['bytes'],
                  'hasCover': bool(m.get('cover')), 'hasLabel': bool(m.get('label')), 'lyrics': len(extras['lyrics']), 'videos': len(extras['videos']),
                  'groupPictures': len(extras['groupart'])}
        tmp = path + '.part'
        total = sum(os.path.getsize(p) for _, p in files) or 1
        done = 0
        try:
            with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_STORED, allowZip64=True) as z:
                z.writestr('mdpack.json', json.dumps(header, ensure_ascii=False, indent=1), zipfile.ZIP_DEFLATED)
                z.writestr('manifest.json', json.dumps(m, ensure_ascii=False, indent=1), zipfile.ZIP_DEFLATED)
                z.writestr('extras.json', json.dumps(extras, ensure_ascii=False), zipfile.ZIP_DEFLATED)
                for k, (name, p) in enumerate(files):
                    self._clone_tell(phase='packing', n=k, count=len(files), name=os.path.basename(p), done=done, total=total)
                    with open(p, 'rb') as src, z.open(name, 'w', force_zip64=True) as dst:
                        for chunk in iter(lambda: src.read(1 << 20), b''):
                            dst.write(chunk)
                            done += len(chunk)
                            self._clone_tell(phase='packing', n=k, count=len(files), name=os.path.basename(p), done=done, total=total)
            os.replace(tmp, path)
        except (OSError, zipfile.BadZipFile) as exc:
            try:
                os.remove(tmp)
            except OSError:
                pass
            return {'error': 'The package could not be written: %s' % exc}
        return {'ok': True, 'path': path, 'bytes': os.path.getsize(path), 'tracks': len(m['tracks']), 'lyrics': len(extras['lyrics']), 'videos': len(extras['videos']),
                'groupPictures': len(extras['groupart']), 'label': bool(m.get('label')), 'cover': bool(m.get('cover'))}

    # -- opening a package ------------------------------------------------------------------------
    def package_pick(self):
        kind = getattr(getattr(webview, 'FileDialog', None), 'OPEN', None) or webview.OPEN_DIALOG
        start = os.path.join(os.path.expanduser('~'), 'Documents')
        path = self._window.create_file_dialog(kind, directory=start if os.path.isdir(start) else '', allow_multiple=False,
                                               file_types=('MiniDisc package (*%s)' % EXT,))
        if not path:
            return {'cancelled': True}
        return {'path': path if isinstance(path, str) else path[0]}

    @staticmethod
    def _pkg_json(z, name):
        info = z.getinfo(name)
        if info.file_size > MAX_JSON:
            raise ValueError('%s is far too large' % name)
        return json.loads(z.read(name).decode('utf-8'))

    @staticmethod
    def _pkg_names_ok(m):
        """The file names in the manifest, or None unless every one is a plain file name (nothing that could point outside the folder it is unpacked to)."""
        if not isinstance(m.get('tracks'), list) or not m['tracks']:
            return None
        names = []
        for it in m['tracks']:
            names.append(it.get('file'))
            if it.get('spatial'):
                names.append(it['spatial'].get('file'))
        for key in ('cover', 'label'):
            if m.get(key):
                names.append(m[key])
        if any(not isinstance(n, str) or not n or n != os.path.basename(n) or n in ('.', '..') or '\\' in n or '/' in n or ':' in n for n in names):
            return None
        return names

    def package_inspect(self, path):
        """Reads only the header of a package and says what it holds and whether this PC can take it. Writes nothing."""
        try:
            with zipfile.ZipFile(path) as z:
                h = self._pkg_json(z, 'mdpack.json')
                if h.get('kind') != PACKAGE_KIND or not isinstance(h.get('version'), int):
                    return {'error': 'This is not a MiniDisc Manager disc package.'}
                if h['version'] > PACKAGE_VERSION:
                    return {'error': 'This package was made by a newer version of MiniDisc Manager. Update the program to open it.'}
                m = self._pkg_json(z, 'manifest.json')
                if not m.get('complete') or self._pkg_names_ok(m) is None:
                    return {'error': 'This package is damaged.'}
        except (OSError, zipfile.BadZipFile, KeyError, ValueError) as exc:
            return {'error': 'This file could not be read as a disc package (%s).' % exc}
        os.makedirs(CLONE_DIR, exist_ok=True)
        need = int(h.get('bytes') or 0)
        free = shutil.disk_usage(CLONE_DIR).free
        return {'ok': True, 'title': h.get('title') or '', 'type': h.get('type') or 'himd', 'tracks': h.get('tracks'), 'seconds': h.get('seconds'), 'bytes': need,
                'created': h.get('created') or '', 'hasCover': bool(h.get('hasCover')), 'hasLabel': bool(h.get('hasLabel')), 'lyrics': h.get('lyrics', 0),
                'videos': h.get('videos', 0), 'groupPictures': h.get('groupPictures', 0), 'freeBytes': free, 'fits': free > need * 1.05 + 200 * 1000 * 1000,
                'pending': bool(self._clone_manifest())}

    def package_import(self, path, replace=False):
        """Unpacks the package into the waiting-copy folder (checking every file), adds its lyrics and video links to this PC's own, and leaves the copy
        waiting for a disc (the page goes straight on to writing it). `replace`: the user agreed to delete another waiting copy first. Writes nothing to a recorder."""
        info = self.package_inspect(path)
        if 'error' in info:
            return info
        if info['pending'] and not replace:
            return {'error': 'A saved copy of a disc is already waiting on this PC. Write it to a disc or discard it first (Clone disc…).', 'pending': True}
        if not info['fits']:
            return {'error': 'There is not enough free space on this PC to unpack the package (about %d MB needed).' % (info['bytes'] // 1000000 + 200)}
        self._clone_cancel = False
        stage = os.path.join(CLONE_DIR, 'stage')
        shutil.rmtree(CLONE_DIR, ignore_errors=True)
        os.makedirs(stage)
        tell = self._clone_tell
        try:
            with zipfile.ZipFile(path) as z:
                m = self._pkg_json(z, 'manifest.json')
                names = self._pkg_names_ok(m)
                try:
                    extras = self._pkg_json(z, 'extras.json')
                except KeyError:
                    extras = {}
                total = sum(z.getinfo('stage/' + n).file_size for n in names) or 1
                done = 0
                for k, n in enumerate(names):
                    tell(phase='unpacking', n=k, count=len(names), name=n, done=done, total=total)
                    with z.open('stage/' + n) as src, open(os.path.join(stage, n), 'wb') as dst:
                        for chunk in iter(lambda: src.read(1 << 20), b''):
                            dst.write(chunk)
                            done += len(chunk)
                            tell(phase='unpacking', n=k, count=len(names), name=n, done=done, total=total)
                    if self._clone_cancel:
                        shutil.rmtree(CLONE_DIR, ignore_errors=True)
                        return {'cancelled': True}
            tell(phase='checking', n=0, count=len(m['tracks']), name='', done=0, total=0)
            for it in m['tracks']:                                          # every file must be exactly what was packed
                p = os.path.join(stage, it['file'])
                if m.get('type') == 'netmd':
                    ok = os.path.getsize(p) == it['bytes'] and _sha(p) == it['sha']
                else:
                    ok = self._clone_core(p, it['kind'])[1:] == (it['bytes'], it['sha'])
                if not ok:
                    raise RuntimeError('“%s” in the package is damaged.' % (it.get('title') or it['file']))
                sp = it.get('spatial')
                if sp and (os.path.getsize(os.path.join(stage, sp['file'])) != sp['bytes'] or _sha(os.path.join(stage, sp['file'])) != sp['sha']):
                    raise RuntimeError('A spatial file in the package is damaged.')
            for key in ('cover', 'label'):
                if m.get(key):
                    with open(os.path.join(stage, m[key]), 'rb') as f:
                        if f.read(3) != b'\xff\xd8\xff':
                            raise RuntimeError('The disc picture in the package is not a picture file.' if key == 'cover' else 'The disc label in the package is not a picture file.')
            added = self._pkg_merge(extras)
            groupart = {str(k): v for k, v in (extras.get('groupart') or {}).items() if isinstance(v, str) and v.startswith('data:image/')}
            with open(os.path.join(CLONE_DIR, 'extras.json'), 'w', encoding='utf-8') as f:
                json.dump({'groupart': groupart, 'videos': bool(extras.get('videos')), 'lyrics': bool(extras.get('lyrics'))}, f, ensure_ascii=False)
            m['fromPackage'] = os.path.basename(path)
            tmp = os.path.join(CLONE_DIR, 'manifest.tmp')                    # the manifest goes in last: only then does the copy count as waiting
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(m, f, indent=1)
            os.replace(tmp, os.path.join(CLONE_DIR, 'manifest.json'))
        except (RuntimeError, OSError, zipfile.BadZipFile, KeyError, ValueError) as exc:
            shutil.rmtree(CLONE_DIR, ignore_errors=True)
            return {'error': 'The package could not be opened: %s Nothing was changed on any disc.' % exc}
        return {'ok': True, 'title': m.get('discTitle') or '', 'type': m.get('type') or 'himd', 'tracks': len(m['tracks']), 'bytes': m['bytes'],
                'lyricsAdded': added['lyrics'], 'videosAdded': added['videos']}

    def _pkg_merge(self, extras):
        """Adds the package's lyrics and video links to this PC's own (what this PC already has is kept)."""
        added = {'lyrics': 0, 'videos': 0}
        items = self._ly_read()
        for e in (extras.get('lyrics') or []):
            if isinstance(e, dict) and isinstance(e.get('title'), str) and isinstance(e.get('lrc'), str) and not self._ly_find(items, e['title'], e.get('artist'), e.get('seconds')):
                items.append({k: e.get(k) for k in ('title', 'artist', 'seconds', 'offset', 'synced', 'source', 'lrc')})
                added['lyrics'] += 1
        if added['lyrics']:
            self._ly_write(items)
        vids = self._video_read()
        for e in (extras.get('videos') or []):
            link = e.get('url') if isinstance(e, dict) else None
            if isinstance(e, dict) and isinstance(e.get('title'), str) and isinstance(link, str) and link.startswith('https://') \
                    and not any(lyrics._same(x, e['title'], e.get('artist'), e.get('seconds')) for x in vids):
                vids.append({'title': e['title'], 'artist': e.get('artist') or '', 'seconds': e.get('seconds') or 0, 'url': link, 'vtitle': (e.get('vtitle') or '')[:200]})
                added['videos'] += 1
        if added['videos']:
            self._video_write(vids)
        return added

    # -- after a package's disc has been written ---------------------------------------------------
    def _pkg_finish(self, index, m):
        """Best effort, never fails a clone: puts what a package carries beyond the audio onto the new Hi-MD disc (the disc label, group pictures, the
        lyrics file, the track list with its video links). Returns a short note about anything that did not work, or ''."""
        notes = []
        try:
            ex = {}
            try:
                with open(os.path.join(CLONE_DIR, 'extras.json'), encoding='utf-8') as f:
                    ex = json.load(f)
            except (OSError, ValueError):
                pass
            if m.get('label'):
                src = os.path.join(CLONE_DIR, 'stage', m['label'])
                self._release_devices()
                with self._lock:
                    r = self._run_helper('label_set', {'file': src, 'backupDir': os.path.join(BACKUP_DIR, 'clone_label')})
                if 'error' in r:
                    notes.append('disc label: ' + str(r['error']))
            if ex.get('groupart') or ex.get('lyrics') or ex.get('videos'):
                self.load(int(index))                                       # the new disc: its tracks and its key
            if ex.get('groupart') and self._disc_key:
                art = self._ga_read()
                art.setdefault(self._disc_key, {}).update(ex['groupart'])
                self._ga_write(art)
                r = self.groupart_save_disc(index)
                if 'error' in r:
                    notes.append('group pictures: ' + str(r['error']))
            if ex.get('lyrics'):
                r = self.lyrics_save_disc(index)
                if 'error' in r:
                    notes.append('lyrics: ' + str(r['error']))
            if ex.get('videos'):
                self.load(int(index))
                r = self.tracklist_sync(index)
                if isinstance(r, dict) and 'error' in r:
                    notes.append('track list: ' + str(r['error']))
        except Exception as exc:                                            # nothing here may undo a verified clone
            notes.append(str(exc))
        return '; '.join(notes)
