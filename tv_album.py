"""Gapless 5.1 on a Google TV: the tracks of an album are joined into ONE video (one continuous Dolby Digital Plus sound + one lyric screen per track), so the TV
never has to stop and start a new file between two tracks (that pause - the TV and the soundbar re-locking on a new stream - was about 7 seconds).
AlbumMixin is mixed into himd_app.Api next to CastMixin. The tracks stay separate on the disc and in the app's list: the track marks are only used to cut the
album picture and to follow where the TV is, so the page still shows track 1, track 2 ... as the TV passes them."""
import base64
import hashlib
import os
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import lyricvideo
from mdm_paths import HERE, PLAY_DIR


def _nowin():
    return getattr(subprocess, 'CREATE_NO_WINDOW', 0)


class _HlsJob:
    """The album's growing HLS stream, in the shape the media server and _lv_stop expect (`dir`, `stop()`)."""

    def __init__(self, out_dir):
        self.dir, self.proc, self.stopped, self.error = out_dir, None, False, ''

    def watch(self, log):
        err = self.proc.stderr.read().decode('utf-8', 'replace').strip()
        self.proc.wait()
        if self.proc.returncode not in (0, None) and err and not self.stopped:
            self.error = err.splitlines()[-1][:300]
            log('album stream ffmpeg failed: ' + err[-600:])

    def segments(self):
        try:
            with open(os.path.join(self.dir, 'index.m3u8'), encoding='utf-8') as f:
                return f.read().count('#EXTINF')
        except OSError:
            return 0

    def stop(self):
        self.stopped = True
        try:
            if self.proc and self.proc.poll() is None:
                self.proc.kill()
        except OSError:
            pass


class AlbumMixin:
    _album = None                    # the album video made last: {'cfg', 'numbers', 'offs', 'durs', 'name', 'viz_url', 'total'}
    _album_on = None                 # the name of the album video the TV was last told to play (None: the TV plays something else, or nothing)

    @staticmethod
    def _ffmpeg_path():
        return os.path.join(HERE, 'runtime', 'ffmpeg.exe')

    def _media_seconds(self, path):
        """The length of an audio file in seconds (ffmpeg's own report, to a hundredth of a second), or 0.0."""
        r = subprocess.run([self._ffmpeg_path(), '-hide_banner', '-i', path], capture_output=True, text=True, creationflags=_nowin())
        m = re.search(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)', r.stderr or '')
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0

    def _album_screen(self, track, lyrics_on):
        """What the lyric screen of one track shows (the same as the single-track 5.1 screen; a track without timed lyrics gets the heading and cover only)."""
        import lyrics
        lines, offset = [], 0.0
        if lyrics_on and track.get('number'):
            ly = self.lyrics_get(track.get('number'))
            if ly.get('synced'):
                lines = [(s, x) for s, x in ly.get('lines', []) if s is not None]
                offset = float(ly.get('offset') or 0)
        cover = None
        if getattr(self, '_loaded_netmd', False):
            import disc_lookup
            cover = disc_lookup.cover_bytes(self._netmd_disc_key(self._tracks))
        else:
            url = self._ga_for_track(track.get('number')) or self._cover_url
            if url and url.startswith('data:'):
                cover = base64.b64decode(url.split(',', 1)[1])
        title, artist = lyrics._split_title(track)
        return {'title': title or 'Track', 'artist': artist or '', 'album': track.get('album') or '', 'lines': lines, 'offset': offset, 'cover': cover,
                'note': '5.1 surround  ·  Dolby Digital Plus|' + (self._codec_line(track) or '')}

    def _album_build(self, numbers, mine):
        """Makes the album video for the tracks `numbers` (in order). Reads each track's spatial file from the disc when it is not on this PC yet (the slow part:
        about 30 seconds a track), then joins the sound of all of them in ONE encode (no padding or silence between tracks), draws one lyric screen per track and
        joins those too. Returns the album dict, None when a newer request replaced this one, or raises."""
        tracks = [next(t for t in self._tracks if t['number'] == n) for n in numbers]
        lyrics_on = bool(self._app_setting('spatialTvLyrics'))
        font = self._app_setting('tvFont')
        ff = self._ffmpeg_path()
        srcs = []
        for i, t in enumerate(tracks):
            if mine != self._cast_seq:
                return None
            self._sp_say(phase='album', i=i + 1, n=len(tracks), num=t['number'], first=numbers[0], last=numbers[-1], name=t.get('title') or '', stage='read')
            src = self.spatial_surround_source(t)                       # reads the spatial file from the disc (kept on this PC until the program closes)
            if not src:
                raise RuntimeError('The spatial file of track %d could not be read.' % t['number'])
            srcs.append(src)
        if mine != self._cast_seq:
            return None
        self._sp_say(phase='album', i=len(tracks), n=len(tracks), name='', stage='build')
        durs = [self._media_seconds(s['path']) for s in srcs]
        if not all(d > 0.5 for d in durs):
            raise RuntimeError('The length of a track could not be read.')
        cum = [0.0]
        for d in durs:
            cum.append(cum[-1] + d)
        shots = [self._album_screen(t, lyrics_on) for t in tracks]
        key = hashlib.sha1(repr((self._disc_key, numbers, [s['path'] for s in srcs], [round(d, 2) for d in durs], font, 'album1',
                                 [(x['title'], x['artist'], x['album'], x['note'], x['offset'], x['lines'], len(x['cover'] or b'')) for x in shots])).encode('utf-8')).hexdigest()[:14]
        name, vname = 'album-%s.mp4' % key, 'albumviz-%s.m4a' % key
        path, vpath = os.path.join(PLAY_DIR, name), os.path.join(PLAY_DIR, vname)
        work = os.path.join(PLAY_DIR, 'album-%s.work' % key)
        os.makedirs(PLAY_DIR, exist_ok=True)
        if not (os.path.exists(path) and os.path.exists(vpath) and os.path.getsize(path) > 1000):
            shutil.rmtree(work, ignore_errors=True)
            os.makedirs(work, exist_ok=True)
            try:
                # 1. the sound: every track mixed to 5.1, joined sample for sample, encoded once (the second output is a stereo copy for the window's visualizer)
                n = len(srcs)
                cmd = [ff, '-hide_banner', '-loglevel', 'error', '-y']
                for s in srcs:
                    cmd += ['-i', s['path']]
                parts = ['[%d:a]%s,aresample=48000[a%d]' % (i, s['filter'], i) for i, s in enumerate(srcs)]
                graph = ';'.join(parts) + ';' + ''.join('[a%d]' % i for i in range(n)) + 'concat=n=%d:v=0:a=1,asplit=2[o1][o2]' % n
                audio = os.path.join(work, 'sound.mp4')
                cmd += ['-filter_complex', graph, '-map', '[o1]', '-c:a', 'eac3', '-b:a', '640k', '-ar', '48000', '-ac', '6', '-f', 'mp4', audio,      # -ac 6 on purpose: without it the -ac 2 of the second output also made this one stereo
                        '-map', '[o2]', '-ac', '2', '-c:a', 'aac', '-b:a', '160k', '-f', 'mp4', '-movflags', '+faststart', vpath + '.part']
                r = subprocess.run(cmd, capture_output=True, text=True, creationflags=_nowin())
                if r.returncode or not os.path.exists(audio) or not os.path.exists(vpath + '.part'):
                    raise RuntimeError('The album sound could not be made: ' + (r.stderr or '').strip()[-300:])
                os.replace(vpath + '.part', vpath)
                if mine != self._cast_seq:
                    return None
                # 2. the picture: one lyric screen per track, each cut to the frames its track covers (rounded on the album's own time line, so the screens
                #    never drift away from the sound however many tracks there are)
                fps = lyricvideo.FPS
                bounds = [int(round(c * fps)) for c in cum]
                caption = self._caption()

                def seg(i):
                    x, frames = shots[i], bounds[i + 1] - bounds[i]
                    sp = os.path.join(work, 'seg%03d.mp4' % i)
                    ok = lyricvideo.make_surround_mp4(ff, None, sp, x['title'], x['artist'], x['lines'], x['offset'], durs[i], x['cover'], caption, x['album'],
                                                      x['note'], self.log, font, frames=frames)
                    return sp if ok else None
                with ThreadPoolExecutor(max_workers=3) as ex:
                    segs = list(ex.map(seg, range(n)))
                if not all(segs):
                    raise RuntimeError('The lyric screens could not be made.')
                lst = os.path.join(work, 'list.txt')
                with open(lst, 'w', encoding='utf-8') as f:
                    for sp in segs:
                        f.write("file '%s'\n" % sp.replace('\\', '/').replace("'", "'\\''"))
                r = subprocess.run([ff, '-hide_banner', '-loglevel', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', lst, '-i', audio, '-map', '0:v', '-map', '1:a',
                                    '-c', 'copy', '-shortest', '-f', 'mp4', '-movflags', '+faststart', path + '.part'], capture_output=True, text=True, creationflags=_nowin())
                if r.returncode or not os.path.exists(path + '.part'):
                    raise RuntimeError('The album video could not be joined: ' + (r.stderr or '').strip()[-300:])
                os.replace(path + '.part', path)
            finally:
                shutil.rmtree(work, ignore_errors=True)
        st = {'key': 'album-' + name, 'name': name, 'format': 'mp4', 'path': path, 'total': os.path.getsize(path), 'mime': 'video/mp4', 'done': True,
              'failed': False, 'cancelled': False, 'announced': True, 'error': ''}
        sv = {'key': 'album-' + vname, 'name': vname, 'format': 'm4a', 'path': vpath, 'total': os.path.getsize(vpath), 'mime': 'audio/mp4', 'done': True,
              'failed': False, 'cancelled': False, 'announced': True, 'error': ''}
        self._streams[name], self._streams[vname] = st, sv
        alb = {'cfg': (self._disc_key, lyrics_on, font), 'numbers': list(numbers), 'offs': {n: cum[i] for i, n in enumerate(numbers)},
               'durs': {n: durs[i] for i, n in enumerate(numbers)}, 'name': name, 'viz_url': self._play_reply(sv)['url'], 'total': cum[-1]}
        return alb

    def _album_where(self, alb, pos):
        """(track number, seconds into that track, track length) for a position `pos` on the album's time line. The TV reports whole seconds (rounded down), so
        a track counts as started up to a second early: right after a move to the start of a track the TV still says "second 5" for a track that starts at 5.57."""
        nums = [n for n in alb['numbers'] if n in alb['offs']]            # a growing stream only knows the tracks made so far
        cur = nums[0]
        for n in nums:
            if alb['offs'][n] <= pos + 0.99:
                cur = n
        return cur, max(0.0, pos + 0.5 - alb['offs'][cur]), alb['durs'][cur]

    # ---- Sonos: queue the next track so the room carries on by itself --------------------------------------------------------------------------------------
    _sq = None                       # the running queue of a Sonos room: {'mine', 'ip', 'index', 'cur', 'cur_name', 'chain', 'next'}
    _pin = None                      # names of the track files in PLAY_DIR a room still needs (the playing one and the queued one)

    def _sonos_queue_start(self, mine, ip, device_index, number, cur_name, chain):
        sq = {'mine': mine, 'ip': ip, 'index': int(device_index), 'cur': number, 'cur_name': cur_name, 'chain': list(chain), 'next': None}
        self._sq, self._pin = sq, {cur_name}
        self._sonos_queue_prepare(sq)

    def _sonos_queue_prepare(self, sq):
        if sq['chain']:
            threading.Thread(target=self._sonos_queue_work, args=(sq, sq['cur'], sq['cur_name']), daemon=True).start()

    def _sonos_queue_alive(self, sq, cur):
        return self._sq is sq and sq['mine'] == self._cast_seq and sq['cur'] == cur

    def _sonos_queue_work(self, sq, cur, cur_name):
        """Gets the track after `cur` ready and tells the room to play it next. It waits until the playing track has been read completely (reading another
        track must not disturb it), reads the next one (a standard disc has it read ahead already) and hands the room its address."""
        import sonos
        try:
            nxt = sq['chain'][0]
            end = time.time() + 1800
            while time.time() < end and self._sonos_queue_alive(sq, cur):
                st = next((s for s in list(self._streams.values()) if s['name'] == cur_name), None)
                if st is None or st.get('done') or st.get('failed'):
                    break
                time.sleep(1)
            if not self._sonos_queue_alive(sq, cur):
                return
            r = self.play_prepare(sq['index'], nxt)
            if r.get('superseded') or 'error' in r or not self._sonos_queue_alive(sq, cur):
                if 'error' in r:
                    self.log('sonos queue: track %d not queued (%s)' % (nxt, r['error']))
                return
            path = r['url'].split('//', 1)[1].split('/', 1)[1]
            name = path.rsplit('/', 1)[-1]
            self._pin = {cur_name, name}
            st = next((s for s in list(self._streams.values()) if s['name'] == name), None)
            track = next((t for t in self._tracks if t['number'] == nxt), None) or {}
            lan = sonos.local_ip_towards(sq['ip'])
            self._ensure_cast_server(lan)
            url = 'http://%s:%d/%s' % (lan, self._cast_port, path)
            sp = sonos.Speaker(sq['ip'])
            sp.set_next(url, track.get('title'), st['mime'] if st else 'audio/wav')
            sq['next'] = {'number': nxt, 'url': url, 'name': name, 'viz': r['url']}
            self.log('sonos queue: track %d queued after track %d%s' % (nxt, cur, '' if sp.next_uri() == url else ' (the room did not confirm it)'))
        except Exception as exc:
            self.log('sonos queue: not queued (%s)' % exc)

    def _sonos_queue_check(self, sp, sq, st):
        """Called with every status of the room: has it moved on into the queued track? Returns (extra result fields, viz url or None)."""
        import sonos
        viz = None
        if sq['next'] and st['state'] != 'ready':
            try:
                uri = sp.current_uri()
            except sonos.SonosError:
                uri = ''
            if uri == sq['next']['url']:
                n = sq['next']
                sq['cur'], sq['cur_name'], sq['next'] = n['number'], n['name'], None
                if sq['chain'] and sq['chain'][0] == n['number']:
                    sq['chain'].pop(0)
                self._pin = {n['name']}
                viz = n['viz']
                self.log('sonos queue: the room went on to track %d by itself' % n['number'])
                self._sonos_queue_prepare(sq)
        return {'album': {'track': sq['cur'], 'off': 0}}, viz

    # ---- The album as a growing HLS stream: the TV starts after the first track and the rest is read and added while it plays ------------------------------
    @staticmethod
    def _free_port():
        import socket
        s = socket.socket()
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
        s.close()
        return port

    def _pcm_samples(self, path, flt):
        """The exact number of samples (per channel, 48000 Hz) the track's 5.1 mix has (decoded once and counted, about a second a track)."""
        p = subprocess.Popen([self._ffmpeg_path(), '-hide_banner', '-loglevel', 'error', '-i', path, '-af', flt + ',aresample=48000', '-f', 'f32le', '-ac', '6', 'pipe:1'],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=_nowin())
        n = 0
        while True:
            chunk = p.stdout.read(1 << 22)
            if not chunk:
                break
            n += len(chunk)
        p.stdout.close()
        p.wait()
        return n // 24

    def _album_viz_copy(self, alb, number, src, flt, vid):
        """A stereo copy of one track for the window's visualiser (and so the pop-out's): in the growing stream there is no finished album sound to copy, so each
        track gets its own small file. The page is given the address of the current track's file when the TV passes into that track."""
        try:
            name = 'albumviz-%s-%d.m4a' % (vid, number)
            path = os.path.join(PLAY_DIR, name)
            r = subprocess.run([self._ffmpeg_path(), '-hide_banner', '-loglevel', 'error', '-y', '-i', src['path'], '-af', flt + ',aresample=48000', '-ac', '2',
                                '-c:a', 'aac', '-b:a', '160k', '-f', 'mp4', '-movflags', '+faststart', path + '.part'], capture_output=True, text=True, creationflags=_nowin())
            if r.returncode or not os.path.exists(path + '.part'):
                return
            os.replace(path + '.part', path)
            st = {'key': 'album-' + name, 'name': name, 'format': 'm4a', 'path': path, 'total': os.path.getsize(path), 'mime': 'audio/mp4', 'done': True,
                  'failed': False, 'cancelled': False, 'announced': True, 'error': ''}
            self._streams[name] = st
            alb['viz'][number] = self._play_reply(st)['url']
        except Exception as exc:
            self.log('album stream: no visualiser copy of track %d (%s)' % (number, exc))

    def _album_hls_start(self, numbers, mine):
        """Starts making the album as an HLS stream and returns the album dict as soon as the TV can start (a few seconds of picture and sound exist). The rest of
        the tracks are read from the disc and added by a background thread while the TV plays. One encoder makes the sound of all the tracks in one go (so the
        joins are exact), the lyric screens of the tracks follow each other into the same encoder. Returns None when a newer request replaced this one; raises
        when it cannot be started."""
        import queue
        import socket
        tracks = [next(t for t in self._tracks if t['number'] == n) for n in numbers]
        lyrics_on = bool(self._app_setting('spatialTvLyrics'))
        font, caption, ff = self._app_setting('tvFont'), self._caption(), self._ffmpeg_path()
        self._lv_stop()
        vid = '%d' % int(time.time() * 1000)
        out_dir = os.path.join(PLAY_DIR, 'lyricvideo-' + vid)
        os.makedirs(out_dir, exist_ok=True)
        port = self._free_port()
        W, H, FPS = lyricvideo.W, lyricvideo.H, lyricvideo.FPS
        cmd = [ff, '-hide_banner', '-loglevel', 'error', '-y', '-f', 'f32le', '-ar', '48000', '-ch_layout', '5.1', '-i', 'pipe:0',
               '-f', 'rawvideo', '-pix_fmt', 'yuv420p', '-video_size', '%dx%d' % (W, H), '-framerate', str(FPS), '-i', 'tcp://127.0.0.1:%d?listen=1' % port,
               '-map', '1:v', '-map', '0:a'] + lyricvideo.video_opts() + ['-c:a', 'eac3', '-b:a', '640k', '-ar', '48000', '-ac', '6',
               '-f', 'hls', '-hls_time', '4', '-hls_list_size', '0', '-hls_playlist_type', 'event', '-hls_segment_filename', 'seg%05d.ts', 'index.m3u8']
        job = _HlsJob(out_dir)
        job.proc = subprocess.Popen(cmd, cwd=out_dir, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=_nowin())
        threading.Thread(target=job.watch, args=(self.log,), daemon=True).start()
        alb = {'cfg': None, 'numbers': list(numbers), 'offs': {}, 'durs': {}, 'name': 'lv/%s/index.m3u8' % vid, 'viz_url': None, 'viz': {}, 'total': 0.0, 'hls': True, 'id': vid, 'job': job}
        self._lv = {'id': vid, 'job': job, 'start': 0.0, 'ctx': None}
        screens = queue.Queue()

        def dead():
            return job.stopped or mine != self._cast_seq or job.proc.poll() is not None

        def video():                                              # the lyric screens, in order, into the encoder's second input
            sock = None
            try:
                for _ in range(100):
                    try:
                        sock = socket.create_connection(('127.0.0.1', port), timeout=5)
                        break
                    except OSError:
                        if dead():
                            return
                        time.sleep(0.2)
                if sock is None:
                    raise RuntimeError('the encoder did not open its picture input')
                sock.settimeout(None)
                while True:
                    item = screens.get()
                    if item is None:
                        break
                    x, frames, dur = item
                    ok = lyricvideo.stream_surround_raw(ff, sock.sendall, x['title'], x['artist'], x['lines'], x['offset'], dur, x['cover'], caption, x['album'], x['note'],
                                                        self.log, font, frames, stop=dead)
                    if not ok:
                        raise RuntimeError('a lyric screen could not be made')
            except Exception as exc:
                if not dead():
                    job.error = str(exc)
                    self.log('album stream: pictures stopped (%s)' % exc)
                    job.stop()
            finally:
                try:
                    if sock:
                        sock.close()
                except OSError:
                    pass

        def audio():
            cum_samples, cum_frames = 0, 0
            try:
                for t in tracks:
                    if dead():
                        return
                    self._sp_say(phase='album', i=numbers.index(t['number']) + 1, n=len(tracks), num=t['number'], first=numbers[0], last=numbers[-1], name=t.get('title') or '', stage='read')
                    src = self.spatial_surround_source(t)
                    if not src:
                        raise RuntimeError('The spatial file of track %d could not be read.' % t['number'])
                    flt = src['filter']
                    n = self._pcm_samples(src['path'], flt)
                    if n < 48000:
                        raise RuntimeError('Track %d has no audio.' % t['number'])
                    end_frames = int(round((cum_samples + n) / 48000.0 * FPS))
                    screens.put((self._album_screen(t, lyrics_on), end_frames - cum_frames, n / 48000.0))
                    self._album_viz_copy(alb, t['number'], src, flt, vid)
                    alb['offs'][t['number']], alb['durs'][t['number']] = cum_samples / 48000.0, n / 48000.0
                    alb['total'] = (cum_samples + n) / 48000.0
                    cum_samples, cum_frames = cum_samples + n, end_frames
                    p = subprocess.Popen([ff, '-hide_banner', '-loglevel', 'error', '-i', src['path'], '-af', flt + ',aresample=48000', '-f', 'f32le', '-ac', '6', 'pipe:1'],
                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=_nowin())
                    try:
                        while True:
                            chunk = p.stdout.read(1 << 20)
                            if not chunk or dead():
                                break
                            job.proc.stdin.write(chunk)
                    finally:
                        p.stdout.close()
                        p.kill()
                    job.proc.stdin.flush()
                self._sp_say(phase='album', i=len(tracks), n=len(tracks), name='', stage='done')
            except Exception as exc:
                if not dead():
                    job.error = str(exc)
                    self.log('album stream: stopped (%s)' % exc)
                    job.stop()
            finally:
                screens.put(None)
                try:
                    job.proc.stdin.close()
                except (OSError, ValueError):
                    pass
        threading.Thread(target=video, daemon=True).start()
        threading.Thread(target=audio, daemon=True).start()
        end = time.time() + 900
        while time.time() < end:
            if mine != self._cast_seq:
                job.stop()
                return None
            if job.segments() >= 3 or (job.proc.poll() == 0 and job.segments() > 0):
                alb['cfg'] = (self._disc_key, lyrics_on, font)
                return alb
            if job.proc.poll() not in (None, 0) or job.error:
                raise RuntimeError(job.error or 'the album stream stopped')
            time.sleep(0.3)
        job.stop()
        raise RuntimeError('the album stream did not start in time')


    def _album_reusable(self, numbers):
        a = self._album
        if not a or not all(n in a['offs'] for n in numbers):
            return False
        if a.get('hls'):                                             # a growing stream: still there, and not stopped
            lv = self._lv
            return bool(lv and lv['id'] == a['id'] and not a['job'].stopped and not a['job'].error and os.path.isdir(a['job'].dir))
        cfg = (self._disc_key, bool(self._app_setting('spatialTvLyrics')), self._app_setting('tvFont'))
        return a['cfg'] == cfg and os.path.exists(os.path.join(PLAY_DIR, a['name']))
