"""Spatial (multichannel) audio on Hi-MD discs: preparing the files while tracks are added, writing them to the disc and linking them to their
tracks afterwards, showing them, playing them (rendered for headphones) and removing them. SpatialMixin is mixed into himd_app.Api.

On the disc each spatial track is an ordinary stereo track (the recorder plays it) plus a hidden root file SPnnnnnn.HMS (see spatial.py). A small
index file SPATIAL.JSN in the root folder says which file belongs to which track: the track's own key (the random 8 bytes in its index entry)
plus the title and length as a second check. Standard discs have no file system, so they cannot hold these files."""
import json
import os
import re
import shutil
import threading
import time
import uuid

import spatial
from mdm_paths import BACKUP_DIR, PLAY_DIR, SPATIAL_DIR

INDEX_NAME = 'SPATIAL.JSN'
NAME_RE = re.compile(r'^SP[0-9A-Z]{1,6}\.HMS$')


class SpatialMixin:
    _sp_staged = None                    # token -> {'folder', 'items': [{'hms', 'seconds', 'title', 'bytes'}]}
    _sp_entries = ()                     # the index of the disc now showing: dicts {key, title, seconds, file, codec, channels, layout, quality, bytes}
    _sp_sizes = None                     # root file name -> size, for every spatial file on the disc now showing
    _sp_cancel = None
    _sp_cache = None                     # (disc key, file, size) -> rendered WAV path

    def _sp_state(self):
        if self._sp_staged is None:
            self._sp_staged, self._sp_cancel, self._sp_cache, self._sp_sizes = {}, threading.Event(), {}, {}

    def _sp_say(self, **msg):
        if getattr(self, '_window', None):
            try:
                self._window.evaluate_js('window.onSpatialProgress && window.onSpatialProgress(%s)' % json.dumps(msg))
            except Exception:
                pass

    # -- looking at the source files ---------------------------------------------------------------
    def spatial_probe(self, paths):
        """Read-only: which of these files are multichannel (6 or more channels), with the layout guessed and the size of the spatial copy for each setting."""
        self._sp_state()
        out = []
        for p in paths:
            info = spatial.probe(p)
            if 'error' not in info and info.get('spatial'):
                s, n = info['seconds'], info['channels']
                info['est'] = {'lossless': spatial.estimate_bytes(s, n, 'lossless'), 'low': spatial.estimate_bytes(s, n, 'opus', 'low'),
                               'medium': spatial.estimate_bytes(s, n, 'opus', 'medium'), 'high': spatial.estimate_bytes(s, n, 'opus', 'high')}
            info['path'] = p
            out.append(info)
        return {'files': out}

    # -- making the files, before the tracks are written -------------------------------------------
    def spatial_prepare(self, items, codec, quality):
        """items: [{path, layout, title}] in upload order. Writes, for each, the stereo version (a WAV the normal upload takes in place of the original)
        and the spatial file, into a working folder. Returns {token, files: [{path (the stereo WAV), seconds, bytes}]}. Nothing touches the disc."""
        self._sp_state()
        self._sp_cancel.clear()
        token = uuid.uuid4().hex[:12]
        folder = os.path.join(SPATIAL_DIR, token)
        os.makedirs(folder, exist_ok=True)
        done = []
        try:
            for i, it in enumerate(items):
                self._sp_say(phase='prepare', file=i, count=len(items), name=os.path.basename(it['path']), step='stereo')
                down, hms = os.path.join(folder, '%02d-stereo.wav' % i), os.path.join(folder, '%02d.hms' % i)
                info = spatial.probe(it['path'])
                if 'error' in info:
                    raise spatial.SpatialError(info['error'])
                layout = it.get('layout') or info['layout']
                spatial.downmix(it['path'], down, layout)
                if self._sp_cancel.is_set():
                    raise spatial.SpatialError('Cancelled.')
                self._sp_say(phase='prepare', file=i, count=len(items), name=os.path.basename(it['path']), step='spatial')
                r = spatial.encode(it['path'], hms, codec, quality, layout, it.get('title') or '', cancel=self._sp_cancel)
                done.append({'path': down, 'hms': hms, 'seconds': r['seconds'], 'bytes': r['bytes'], 'layout': layout, 'channels': r['channels'],
                             'title': it.get('title') or '', 'codec': codec, 'quality': quality})
        except Exception as exc:
            shutil.rmtree(folder, ignore_errors=True)
            return {'error': str(exc) if isinstance(exc, spatial.SpatialError) else 'Could not prepare the spatial audio: %s' % exc}
        self._sp_staged[token] = {'folder': folder, 'items': done}
        return {'token': token, 'files': [{'path': d['path'], 'seconds': d['seconds'], 'bytes': d['bytes']} for d in done]}

    def spatial_cancel(self):
        self._sp_state()
        self._sp_cancel.set()
        return {'ok': True}

    def spatial_discard(self, token):
        self._sp_state()
        st = self._sp_staged.pop(token, None)
        if st:
            shutil.rmtree(st['folder'], ignore_errors=True)
        return {'ok': True}

    # -- writing them to the disc, after the tracks are there -------------------------------------
    @staticmethod
    def _sp_next_name(taken):
        taken = {n.upper() for n in taken}
        for n in range(1, 999999):
            name = 'SP%06d.HMS' % n
            if name not in taken:
                return name
        raise spatial.SpatialError('No free file name for the spatial audio.')

    def _sp_put(self, name, path, label='', n=0, count=1, tell=None):
        """WRITES A FILE TO THE DISC (the helper checks the volume before and after). Retries a few times: a recorder can stay busy after a write.
        A big file reports its progress (writing, then reading back to check): to the Add window as phase 'store', or through `tell` (Clone / Split) as 'writing'."""
        size = os.path.getsize(path)

        def progress(m):
            if m.get('event') != 'progress':
                return
            write = m.get('phase') == 'write'
            if tell:
                tell(phase='writing', n=n, count=count, name=label + (' (spatial audio)' if write else ' (spatial audio, checking)'), done=m.get('done', 0), total=m.get('total', size))
            else:
                self._sp_say(phase='store', step='write' if write else 'verify', n=n, count=count, name=label, done=m.get('done', 0), total=m.get('total', size))
        res = {'error': 'not tried'}
        for _ in range(3):
            with self._lock:
                res = self._run_helper('spatial_put', {'name': name, 'file': path, 'backupDir': os.path.join(BACKUP_DIR, 'spatial_latest')}, progress)
            if 'error' not in res:
                return res
            time.sleep(2.5)
        return res

    def _sp_write_index(self, entries):
        folder = os.path.join(SPATIAL_DIR, 'index-' + uuid.uuid4().hex[:6])
        os.makedirs(folder, exist_ok=True)
        try:
            tmp = os.path.join(folder, INDEX_NAME)
            with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
                json.dump({'app': 'MiniDiscManager', 'version': 1, 'tracks': list(entries)}, f, ensure_ascii=False)
            return self._sp_put(INDEX_NAME, tmp)
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def spatial_commit(self, token, index, total=None, positions=None):
        """WRITES FILES TO THE DISC. The tracks of the upload are now on the disc (the last `total` ones in the list): stores each spatial file and links it to
        its track in SPATIAL.JSN. `positions`: for each spatial file, which of the `total` new tracks it belongs to (0-based; default: the last ones, in order).
        Returns {ok, stored} or an error (the stereo tracks stay on the disc either way)."""
        self._sp_state()
        st = self._sp_staged.get(token)
        if not st:
            return {'error': 'The spatial files for this upload are no longer available.'}
        res = self.load(index)
        if 'error' in res or not res.get('disc'):
            return {'error': res.get('error') or 'Could not read the disc to link the spatial files.'}
        tracks = res['disc']['tracks']
        items = st['items']
        total = int(total or len(items))
        positions = [int(x) for x in positions] if positions else list(range(total - len(items), total))
        if len(positions) != len(items) or len(tracks) < total or any(not 0 <= x < total for x in positions):
            return {'error': 'The disc has fewer tracks than were just added.'}
        added = tracks[-total:]
        new = [added[x] for x in positions]
        for t, it in zip(new, items):
            if abs(t['seconds'] - it['seconds']) > 4:
                return {'error': 'The new tracks on the disc do not match the files that were added (lengths differ), so no spatial files were stored.'}
        entries = [dict(e) for e in self._sp_entries if any(t['key'] == e.get('key') for t in tracks)]
        names = set(self._sp_sizes or {})
        stored = 0
        for k, (t, it) in enumerate(zip(new, items)):
            name = self._sp_next_name(names)
            self._sp_say(phase='store', step='write', n=k, count=len(items), name=t['title'], done=0, total=it['bytes'])
            r = self._sp_put(name, it['hms'], t['title'], k, len(items))
            if 'error' in r:
                return {'error': 'The tracks were added, but a spatial file could not be stored: %s' % r['error'], 'stored': stored}
            names.add(name)
            entries.append({'key': t['key'], 'title': t['title'], 'seconds': t['seconds'], 'file': name, 'codec': it['codec'], 'channels': it['channels'],
                            'layout': it['layout'], 'quality': it['quality'], 'bytes': it['bytes']})
            r = self._sp_write_index(entries)
            if 'error' in r:
                return {'error': 'A spatial file was stored but its index could not be written: %s' % r['error'], 'stored': stored}
            stored += 1
        self.spatial_discard(token)
        return {'ok': True, 'stored': stored}

    def _sp_attach(self, index, parts, tell=None):
        """WRITES FILES TO THE DISC. Stores ready-made spatial files and links each to a track that is now on the disc (used by Clone and Split).
        parts: [{'number': the track's number on the disc now, 'hms': path, 'seconds', 'codec', 'channels', 'layout', 'quality', 'bytes'}].
        Reads the disc again first and checks each file arrived with the right size. Returns {'ok', 'stored'} or {'error', 'stored'}."""
        self._sp_state()
        parts = [p for p in parts if p]
        if not parts:
            return {'ok': True, 'stored': 0}
        res = self.load(index)
        if 'error' in res or not res.get('disc'):
            return {'error': res.get('error') or 'Could not read the disc to link the spatial files.', 'stored': 0}
        tracks = res['disc']['tracks']
        by_number = {t['number']: t for t in tracks}
        entries = [dict(e) for e in self._sp_entries if any(t['key'] == e.get('key') for t in tracks)]
        names, stored, sizes = set(self._sp_sizes or {}), 0, {}
        for k, p in enumerate(parts):
            t = by_number.get(int(p['number']))
            if t is None:
                return {'error': 'Track %s is not on the disc, so its spatial file was not stored.' % p['number'], 'stored': stored}
            name = self._sp_next_name(names)
            r = self._sp_put(name, p['hms'], t['title'], k, len(parts), tell)
            if 'error' in r:
                return {'error': 'A spatial file could not be stored: %s' % r['error'], 'stored': stored}
            names.add(name)
            sizes[t['number']] = os.path.getsize(p['hms'])
            entries.append({'key': t['key'], 'title': t['title'], 'seconds': t['seconds'], 'file': name, 'codec': p.get('codec', ''), 'channels': p.get('channels', 0),
                            'layout': p.get('layout', ''), 'quality': p.get('quality', ''), 'bytes': sizes[t['number']]})
            r = self._sp_write_index(entries)
            if 'error' in r:
                return {'error': 'A spatial file was stored but its index could not be written: %s' % r['error'], 'stored': stored}
            stored += 1
        res = self.load(index)                                     # check: every file is there, linked to its track, and the size is the one that was sent
        if 'error' in res or not res.get('disc'):
            return {'error': 'The spatial files were stored but the disc could not be read back to check them.', 'stored': stored}
        back = {t['number']: t for t in res['disc']['tracks']}
        bad = [n for n, size in sizes.items() if not (back.get(n) or {}).get('spatial') or back[n]['spatial']['bytes'] != size]
        if bad:
            return {'error': 'The spatial file of track %s is not on the disc as it was sent.' % ', '.join(map(str, bad)), 'stored': stored}
        return {'ok': True, 'stored': stored}

    def _sp_cut_for_split(self, track, spans, folder, titles, tell=None):
        """Pulls the track's spatial file off the disc and cuts it into one file per kept part. spans: [(start, duration or None)], titles: one per part.
        Reads the disc only. Returns the parts [{'hms', 'seconds', 'codec', 'channels', 'layout', 'quality', 'bytes'}] (same order) or raises SpatialError."""
        if tell:
            tell(phase='spatialread', n=0, count=1, name=track.get('title') or '', done=0, total=0)
        pulled, err = self._spatial_pull(track)
        if err:
            raise spatial.SpatialError(err)
        parts = []
        for i, ((start, dur), title) in enumerate(zip(spans, titles)):
            self._sp_say(phase='prepare', file=i, count=len(spans), name=title, step='spatial')
            if tell:
                tell(phase='spatialcut', n=i, count=len(spans), name=title, done=0, total=0)
            out = os.path.join(folder, 'sp-part%02d.hms' % (i + 1))
            r = spatial.cut(pulled, out, start, dur, title)
            parts.append(dict(r, hms=out))
        return parts

    # -- reading them when a disc is loaded --------------------------------------------------------
    def _spatial_on_load(self, fs, tracks):
        """Marks every track that has a spatial version. Returns (bytes used by spatial files, number of orphan files with no track)."""
        self._sp_state()
        for t in tracks:
            t['spatial'] = None
        sizes, entries = {}, []
        try:
            for e in fs.listdir('/'):
                if e['dir']:
                    continue
                short = e['short'].upper()
                if NAME_RE.match(short) or short == INDEX_NAME:
                    sizes[short] = e['size']
            if INDEX_NAME in sizes and 0 < sizes[INDEX_NAME] <= 2000000:
                data = json.loads(bytes(fs.read_file('/' + INDEX_NAME)).decode('utf-8-sig'))
                entries = [x for x in data.get('tracks', []) if isinstance(x, dict) and NAME_RE.match(str(x.get('file', '')).upper()) and str(x['file']).upper() in sizes]
        except Exception:
            entries = []
        self._sp_sizes, self._sp_entries = sizes, entries
        used, linked = sum(sizes.values()), set()
        for e in entries:
            t = next((t for t in tracks if t['key'] == e.get('key')), None) or next((t for t in tracks if t['title'] == e.get('title') and abs(t['seconds'] - int(e.get('seconds') or -99)) <= 1 and not t['spatial']), None)
            if t is not None:
                t['spatial'] = {'file': e['file'].upper(), 'codec': e.get('codec', ''), 'channels': e.get('channels', 0), 'layout': e.get('layout', ''), 'quality': e.get('quality', ''), 'bytes': sizes[e['file'].upper()]}
                linked.add(e['file'].upper())
        orphans = [n for n in sizes if n != INDEX_NAME and n not in linked]
        return used, len(orphans)

    # -- playing ----------------------------------------------------------------------------------
    def play_spatial(self, index, number, on_pulled=None):
        """Reads a track's spatial file from the disc, renders it for headphones and returns a URL like play_prepare does (or an error, in which case the page
        plays the stereo track instead). Reads only.
        on_pulled: called (no arguments) as soon as the file has been read from the disc and before the headphone picture is rendered, so a caller can start
        its own work on the file at the same time (the TV's surround files)."""
        self._sp_state()
        self._play_seq += 1
        mine = self._play_seq
        with self._play_mutex:
            if mine != self._play_seq:
                return {'superseded': True}
            try:
                return self._play_spatial_locked(index, int(number), mine, on_pulled)
            except spatial.SpatialError as exc:
                return {'error': str(exc)}
            except OSError as exc:
                return {'error': 'Could not play the spatial version: %s' % exc}

    def _play_spatial_locked(self, index, number, mine, on_pulled=None):
        track = next((t for t in self._tracks if t['number'] == number), None)
        if not track or not track.get('spatial'):
            return {'error': 'This track has no spatial version.'}
        sp = track['spatial']
        pf = self._sp_pf
        if pf is not None and pf['file'] == sp['file']:        # this very track is being read ahead right now: wait for it instead of starting again
            pf['ev'].wait(300)
        if self._active is not None:
            self._active['announced'] = False
        self._cancel_extract()
        key, name, path = self._sp_render_target(track)
        os.makedirs(PLAY_DIR, exist_ok=True)
        self._ensure_server()
        if not (os.path.exists(path) and self._sp_cache.get(key) == path):
            self._play_mutex.release()                             # a newer request may replace this one while the file is read
            try:
                pulled, err = self._spatial_pull(track)
            finally:
                self._play_mutex.acquire()
            if mine != self._play_seq:
                return {'superseded': True}
            if err:
                return {'error': err}
            if on_pulled:
                try:
                    on_pulled()
                except Exception as exc:
                    self.log('spatial: early start failed: %s' % exc)
            try:
                self._sp_say(phase='render', name=track['title'], done=0, total=track['seconds'])
                tmp = path + '.part'
                spatial.render_binaural(pulled, tmp, progress=lambda s: self._sp_say(phase='render', name=track['title'], done=s, total=track['seconds']))
                os.replace(tmp, path)
            finally:
                self._rm(path + '.part')
            self._sp_cache[key] = path
        if mine != self._play_seq:
            return {'superseded': True}
        st = {'key': 'spatial-' + name, 'name': name, 'format': 'wav', 'path': path, 'total': os.path.getsize(path), 'mime': 'audio/wav', 'done': True,
              'failed': False, 'cancelled': False, 'announced': True, 'error': ''}
        self._streams[name] = st
        self._active = None
        return self._play_reply(st)

    def _spatial_pull(self, track, raw=False):
        """Copies the track's spatial file from the disc into PLAY_DIR (kept for the next play of the same track). Returns (path, error text or '').
        raw: used by the read-ahead of the next track: takes the USB lock without the gate (so it does not cancel itself), gives up at once when the
        recorder is busy, and can be stopped between blocks by anything else that needs the recorder."""
        sp = track['spatial']
        key = '%s|%s|%d' % (self._disc_key, sp['file'], sp['bytes'])
        path = os.path.join(PLAY_DIR, 'spatial-%s.hms' % uuid.uuid5(uuid.NAMESPACE_URL, key).hex[:16])
        os.makedirs(PLAY_DIR, exist_ok=True)
        if os.path.exists(path) and os.path.getsize(path) == sp['bytes']:
            return path, ''
        if not raw:
            self._sp_say(phase='read', name=track['title'], done=0, total=sp['bytes'])
        progress = (lambda m: None) if raw else (lambda m: self._sp_say(phase='read', name=track['title'], done=m.get('done'), total=m.get('total')) if m.get('event') == 'progress' else None)
        if raw:
            if not self._lock.raw.acquire(False):
                return '', 'busy'
            try:
                res = self._run_helper('spatial_get', {'name': sp['file'], 'out': path + '.part'}, progress)
            finally:
                self._lock.raw.release()
                self._drive_touched()
        else:
            with self._lock:
                res = self._run_helper('spatial_get', {'name': sp['file'], 'out': path + '.part'}, progress)
        got = res.get('result') or {}
        if 'error' in res or not got.get('found') or got.get('stopped'):
            self._rm(path + '.part')
            return '', 'stopped' if got.get('stopped') else (res.get('error') or 'The spatial file is not on the disc any more.')
        ms = got.get('ms')
        if ms:
            self.log('spatial file read: %.1f MB; opening the disc %.1fs, listing files %.1fs, copying %.1fs (%.2f MB/s)' % (
                sp['bytes'] / 1e6, ms['open'] / 1000, ms['files'] / 1000, ms['read'] / 1000, sp['bytes'] / 1e6 / max(ms['read'] / 1000, 0.001)))
        os.replace(path + '.part', path)
        return path, ''

    # -- reading the next track ahead while a 5.1 track plays on a TV ----------------------------------------------------
    _sp_pf = None                         # {'file', 'ev'} while a read-ahead (read + headphone picture + TV files) of one spatial track is running

    def _sp_render_target(self, track):
        """(cache key, file name, path) of the rendered headphone / visualizer picture of a track's spatial version."""
        sp = track['spatial']
        key = '%s|%s|%d' % (self._disc_key, sp['file'], sp['bytes'])
        name = 'spatial-%s.wav' % uuid.uuid5(uuid.NAMESPACE_URL, key).hex[:16]
        return key, name, os.path.join(PLAY_DIR, name)

    def _sp_prefetch_next(self, number, mine):
        """A 5.1 track has just started on a TV. If the next track also has a spatial version, its file is read from the disc and everything the TV needs
        is made while this one plays, so moving on takes seconds instead of a minute. Reads only; it gives way (stops between blocks) the moment anything
        else needs the recorder, exactly like the read-ahead of standard discs, and it does nothing when the recorder is busy."""
        try:
            self._sp_state()
            if getattr(self, '_loaded_netmd', False) or not self._app_setting('spatialTvSurround') or mine != self._cast_seq:
                return
            track = next((t for t in (self._tracks or []) if t['number'] == int(number) + 1), None)
            if not track or not track.get('spatial') or self._sp_pf is not None:
                return
            if self._thread is not None and self._thread.is_alive():
                return                                         # a playback read is still running
            st = {'name': 'sp-prefetch-%d' % track['number'], 'cancelled': False, 'announced': False, 'done': False, 'failed': False, 'ahead': True,
                  'number': track['number'], 'error': ''}
            t = threading.Thread(target=self._sp_prefetch_run, args=(dict(track), st, mine), daemon=True)
            with self._ra_lock:
                self._thread, self._active = t, st
            self._sp_pf = {'file': track['spatial']['file'], 'ev': threading.Event()}
            t.start()
        except Exception as exc:
            self.log('spatial read-ahead not started: %s' % exc)

    def _sp_prefetch_run(self, track, st, mine):
        pf = self._sp_pf
        t0 = time.time()
        try:
            pulled, err = self._spatial_pull(track, raw=True)
            with self._ra_lock:                                # the disc part is over: nothing may wait for this thread any more
                if self._active is st:
                    self._active = None
                if self._thread is threading.current_thread():
                    self._thread = None
            st['done'] = True
            if err:
                self.log('spatial read-ahead of track %d: %s' % (track['number'], err))
                return
            if st['cancelled'] or mine != self._cast_seq:
                return
            key, name, wav = self._sp_render_target(track)     # the picture the window's visualizer uses
            if not (os.path.exists(wav) and self._sp_cache.get(key) == wav):
                tmp = wav + '.part'
                spatial.render_binaural(pulled, tmp)
                os.replace(tmp, wav)
                self._sp_cache[key] = wav
            if mine != self._cast_seq:
                return
            sound = self._surround_audio(track)                # the 5.1 sound, the still picture and the video that joins them
            pic = self._surround_splash(track)
            if sound and pic:
                self._surround_video(sound, pic)
            self.log('spatial read-ahead: track %d ready after %.1f s' % (track['number'], time.time() - t0))
        except Exception as exc:
            self.log('spatial read-ahead of track %d failed: %s' % (track['number'], exc))
        finally:
            with self._ra_lock:
                if self._active is st:
                    self._active = None
                if self._thread is threading.current_thread():
                    self._thread = None
            if pf is not None:
                pf['ev'].set()
            if self._sp_pf is pf:
                self._sp_pf = None

    def spatial_surround_source(self, track):
        """For a TV: the track's spatial audio as a plain file plus the ffmpeg filter that mixes it down to 5.1 (heights folded into the floor channels; the TV's
        soundbar gets Dolby Digital Plus 5.1). Uses the file play_spatial already pulled. Returns {'path', 'filter', 'mode'} or None."""
        sp = track.get('spatial')
        if not sp:
            return None
        pulled, err = self._spatial_pull(track)
        if err:
            self.log('spatial surround: %s' % err)
            return None
        info = spatial.peek(pulled)
        flt, used, n = spatial.surround_filter(info['names'], '5.1')
        audio = pulled + ('.opus' if info['codec'] == 'opus' else '.wv')
        if not os.path.exists(audio):
            spatial.unpack_audio(pulled, audio)
        return {'path': audio, 'filter': flt, 'mode': used}

    @staticmethod
    def _rm(path):
        try:
            os.remove(path)
        except OSError:
            pass

    # -- saving the spatial version as an ordinary file, for other equipment --------------------------
    SAVE_FORMATS = ('flac', 'eac3', 'native')

    def spatial_save(self, index, numbers, folder, fmt='flac'):
        """Reads the spatial version of each of these tracks from the disc and writes it to `folder` as a normal multichannel file that other players
        understand: 'flac' (lossless 5.1 or 7.1; heights are folded into the floor channels because FLAC holds 8 channels at most), 'eac3' (Dolby Digital
        Plus 5.1 in an MP4, for TVs, soundbars and media boxes) or 'native' (every channel, as stored: .opus or .wv). Reads the disc only.
        Returns {saved: [{number, file}], failed: [{number, title, error}], cancelled, folder}."""
        self._sp_state()
        fmt = fmt if fmt in self.SAVE_FORMATS else 'flac'
        if self._is_netmd(index):
            return {'error': 'Only Hi-MD discs hold spatial versions.'}
        if not folder or not os.path.isdir(folder):
            return {'error': 'Choose a folder to save into.'}
        wanted = {int(n) for n in numbers}
        tracks = [t for t in (self._tracks or []) if t['number'] in wanted and t.get('spatial')]
        if not tracks:
            return {'error': 'None of these tracks has a spatial version.'}
        self._save_cancel = False
        self._sp_cancel.clear()
        saved, failed = [], []
        for n, t in enumerate(tracks):
            if self._save_cancel:
                break
            label = t['title'] if t['title'] != '(untitled)' else 'Track %d' % t['number']
            self._sp_say(phase='save', n=n, count=len(tracks), name=label, step='reading')
            try:
                pulled, err = self._spatial_pull(t)
                if err:
                    raise RuntimeError(err)
                if self._save_cancel:
                    break
                self._sp_say(phase='save', n=n, count=len(tracks), name=label, step='writing')
                info = spatial.peek(pulled)
                names = info['names']
                tags = []
                for key, val in (('title', t['title'] if t['title'] != '(untitled)' else ''), ('artist', t.get('artist')), ('album', t.get('album'))):
                    if val:
                        tags += ['-metadata', '%s=%s' % (key, val)]
                tags += ['-metadata', 'track=%d' % t['number']]
                audio = pulled + ('.opus' if info['codec'] == 'opus' else '.wv')
                if not os.path.exists(audio):
                    spatial.unpack_audio(pulled, audio)
                stem = self._file_stem(t['number'], t['title']) + ' (surround)'
                if fmt == 'flac':
                    both = {'SL', 'SR'} <= set(names) and {'BL', 'BR'} <= set(names)
                    flt, used, _n = spatial.surround_filter(names, '7.1' if both else '5.1')
                    dest = self._unique(os.path.join(folder, stem + '.flac'))
                    bits = ['-sample_fmt', 's16'] if info['codec'] == 'opus' else ['-sample_fmt', 's32', '-bits_per_raw_sample', '24']       # Opus has no real 24-bit detail: 16 bits keeps the file small
                    codec = ['-af', flt, '-c:a', 'flac', '-compression_level', '8'] + bits
                elif fmt == 'eac3':
                    flt, used, _n = spatial.surround_filter(names, '5.1')
                    dest = self._unique(os.path.join(folder, stem + '.mp4'))
                    codec = ['-af', flt, '-c:a', 'eac3', '-b:a', '640k', '-ar', '48000', '-f', 'mp4', '-movflags', '+faststart']
                else:
                    dest = self._unique(os.path.join(folder, stem + ('.opus' if info['codec'] == 'opus' else '.wv')))
                    codec = ['-c:a', 'copy']
                r = spatial._run(['-y', '-loglevel', 'error', '-i', audio, '-vn', '-map_metadata', '-1'] + tags + codec + [dest], timeout=3600)
                if r.returncode or not os.path.exists(dest):
                    raise RuntimeError('Could not write the file: %s' % (r.stderr or b'').decode('utf-8', 'replace').strip()[-200:])
                saved.append({'number': t['number'], 'file': dest})
            except (RuntimeError, OSError, spatial.SpatialError) as exc:
                if self._save_cancel:
                    break
                failed.append({'number': t['number'], 'title': label, 'error': str(exc)})
        return {'saved': saved, 'failed': failed, 'cancelled': bool(self._save_cancel), 'folder': folder}

    # -- taking them off the disc ------------------------------------------------------------------
    def spatial_remove(self, index, number=None):
        """WRITES TO THE DISC. Removes the spatial file of one track (number), or every spatial file that no track uses any more (number None)."""
        self._sp_state()
        if self._is_netmd(index):
            return {'error': 'Only Hi-MD discs hold spatial files.'}
        entries = [dict(e) for e in self._sp_entries]
        if number is None:
            linked = {t['spatial']['file'] for t in self._tracks if t.get('spatial')}
            victims = [n for n in (self._sp_sizes or {}) if n != INDEX_NAME and n not in linked]
        else:
            t = next((t for t in self._tracks if t['number'] == int(number)), None)
            if not t or not t.get('spatial'):
                return {'error': 'This track has no spatial version.'}
            victims = [t['spatial']['file']]
        if not victims:
            return {'ok': True, 'removed': 0}
        for name in victims:
            with self._lock:
                res = self._run_helper('spatial_remove', {'name': name, 'backupDir': os.path.join(BACKUP_DIR, 'spatial_latest')})
            if 'error' in res:
                return res
        entries = [e for e in entries if str(e.get('file', '')).upper() not in victims]
        if entries:
            r = self._sp_write_index(entries)
            if 'error' in r:
                return r
        elif INDEX_NAME in (self._sp_sizes or {}):
            with self._lock:
                res = self._run_helper('spatial_remove', {'name': INDEX_NAME, 'backupDir': os.path.join(BACKUP_DIR, 'spatial_latest')})
            if 'error' in res:
                return res
        return {'ok': True, 'removed': len(victims)}
