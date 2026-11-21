"""Playing the disc's tracks to a Sonos room: finding the speakers, sending a track to one, and the play / pause / seek / volume controls.
CastMixin is mixed into himd_app.Api (the page calls these methods on it). It uses the Api's play_prepare(), _streams, _tracks and log()."""
import http.server
import json
import os
import subprocess
import threading
import time

import base64
import shutil

import chromecast
import lyricvideo

import mediaserver
import sonos
from mdm_paths import APPDATA, FFMPEG_EXE, HERE, PLAY_DIR, h264_args, ui_font


class CastMixin:
    def _cast_init(self):
        self._cast_server = None       # a second media server, on this PC's network address, while a Sonos room is being played to
        self._cast_ip = None
        self._cast_port = 0
        self._cast_known = {}          # Sonos speakers found by the last search
        self._cast_last = None         # {'ip', 'prefix'}: the room this app last sent music to, and the start of our addresses
        self._cast_seq = 0
        self._lv = None                # the lyric video being made for a Google TV: {'id', 'job', 'start', 'ctx'}
        self._lv_base = 0.0            # seconds into the track the TV's current video starts at (0 unless it was remade mid-track)
        self._cast_video = True        # Google TVs get a lyric video (cover, title, timed lyrics) instead of just the audio
        self._recorder_name = ''     # the connected recorder's model (e.g. MZ-RH1), set when a disc loads
        self._cover_url = None         # the disc's picture as a data: address (set when a Hi-MD disc loads)
        self._cast_tvs = None          # {ip: name} of Google Cast devices (Google TV, Chromecast, Nest) found so far; None = not loaded yet

    # Google Cast devices (a Google TV such as the Philips OLED) are listed next to the Sonos rooms. They are told to play the same web
    # address a Sonos room would be given; see chromecast.py. Their addresses are remembered in chromecast.json so the list is instant.
    _CAST_CACHE = os.path.join(APPDATA, 'chromecast.json')

    def _cast_devices(self, refresh=False):
        if self._cast_tvs is None:
            try:
                with open(self._CAST_CACHE, encoding='utf-8') as f:
                    self._cast_tvs = dict(json.load(f))
            except (OSError, ValueError):
                self._cast_tvs = {}
        if refresh:
            try:
                found = chromecast.discover()
            except OSError:
                found = {}
            if found:
                self._cast_tvs = found
                try:
                    os.makedirs(os.path.dirname(self._CAST_CACHE), exist_ok=True)
                    with open(self._CAST_CACHE, 'w', encoding='utf-8') as f:
                        json.dump(found, f)
                except OSError:
                    pass
        return [{'name': name if name.startswith('Cast device') else '%s (Cast)' % name, 'ip': ip, 'kind': 'cast'} for ip, name in self._cast_tvs.items()]

    def cast_options(self, video=None):
        """The Play on sheet's switch: should a Google TV get the lyric video (True) or just the audio (False)?"""
        if video is not None:
            self._cast_video = bool(video)
        return {'video': self._cast_video}

    def cast_viz(self, style=None, color=None, gain=1, apply=False, peaks=True, accent=None):
        """The visualizer the user has picked in the window. The next lyric video for a Google TV draws it; with apply=True a lyric video that is
        playing now is remade from the current position (a short pause on the TV)."""
        self._cast_viz = {'style': str(style or 'off'), 'color': str(color or 'accent'), 'gain': float(gain or 1), 'peaks': bool(peaks),
                          'accent': str(accent or '#7aa2ff')}
        return self._lv_restart() if apply else {'ok': True}

    def _lv_stop(self):
        lv, self._lv = self._lv, None
        self._lv_base = 0.0
        if lv:
            lv['job'].stop()
            shutil.rmtree(lv['job'].dir, ignore_errors=True)

    def _lv_restart(self, at=None):
        """Remakes the TV's lyric video from where it is now (or from `at` seconds into the track) with the current visualizer, and tells the TV to
        play the new one. The TV counts the new stream from 0, so _lv_base keeps the track position (status adds it back)."""
        lock = self.__dict__.setdefault('_lv_lock', threading.Lock())
        with lock:
            old = self._lv
            if not old or not old.get('ctx') or not self._cast_video :
                return {'ok': True, 'restarted': False}
            c, seq = old['ctx'], self._cast_seq
            try:
                dev = chromecast.Device(c['ip'])
                st = dev.status()
                if st['state'] == 'ready':
                    return {'ok': True, 'restarted': False}                          # nothing is playing on the TV
                pos = float(at) if at is not None else self._lv_base + st['seconds']
                t0 = time.time()
                url = self._lyric_video(c['stream'], c['track'], c['lan'], c['ip'], start=pos)      # replaces self._lv; on failure it stops the new one
                if not url:
                    self._lv, self._lv_base = old, (old.get('start') or 0.0)        # the old one keeps playing (the failed attempt reset the base)
                    return {'ok': True, 'restarted': False}
                new = self._lv
                if seq != self._cast_seq:                                            # another track was started meanwhile: this one is out of date
                    new['job'].stop(); shutil.rmtree(new['job'].dir, ignore_errors=True); self._lv = None
                    return {'ok': True, 'restarted': False}
                self._lv_base = pos
                try:
                    dev.play_url(url, c['track'].get('title'), 'application/x-mpegurl', c['track'].get('artist'), c['track'].get('album'), video=True,
                                 source=self._recorder_name or None)
                except chromecast.CastError:
                    self._lv, self._lv_base = old, (old.get('start') or 0.0)
                    new['job'].stop(); shutil.rmtree(new['job'].dir, ignore_errors=True)
                    raise
                if st['state'] == 'paused':
                    dev.control('pause')
                old['job'].stop(); shutil.rmtree(old['job'].dir, ignore_errors=True)
                self.log('cast: lyric video remade from %.0fs with the new visualizer in %.1fs' % (pos, time.time() - t0))
                return {'ok': True, 'restarted': True}
            except (chromecast.CastError, OSError) as exc:
                return {'error': str(exc)}

    def _spatial_note(self, track):
        """The second line on the TV picture of the stereo lyric video, for a track that has a spatial version."""
        sp = (track or {}).get('spatial')
        if not sp:
            return ''
        kind = 'lossless' if sp.get('codec') != 'opus' else 'Opus ' + (sp.get('quality') or '')
        return 'Spatial ' + (sp.get('layout') or '%s ch' % sp.get('channels')) + ' (' + kind.strip() + ')  ·  the TV gets stereo'

    def _surround_audio(self, track):
        """For a Google TV: the track's spatial audio mixed to 5.1 and encoded as Dolby Digital Plus in an audio-only MP4, which the TV passes straight to a
        soundbar or receiver (decoded by the TV or its Cast player, surround arrived as stereo). Made once per track (about 3 s for 12 minutes) and served
        like any other stream. Returns the stream entry, or None when it cannot be made."""
        src = self.spatial_surround_source(track)
        if not src:
            return None
        import hashlib
        name = 'surround-%s.mp4' % hashlib.sha1((src['path'] + src['filter']).encode('utf-8')).hexdigest()[:14]
        path = os.path.join(PLAY_DIR, name)
        if not (os.path.exists(path) and os.path.getsize(path) > 1000):
            tmp = path + '.part'
            r = subprocess.run([FFMPEG_EXE, '-hide_banner', '-loglevel', 'error', '-y', '-i', src['path'], '-vn', '-af', src['filter'],
                                '-c:a', 'eac3', '-b:a', '640k',
                                '-ar', '48000', '-f', 'mp4', '-movflags', '+faststart', tmp],
                               capture_output=True, text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if r.returncode or not os.path.exists(tmp):
                self.log('surround audio failed: %s' % (r.stderr or '').strip()[-300:])
                return None
            os.replace(tmp, path)
        st = {'key': 'surround-' + name, 'name': name, 'format': 'mp4', 'path': path, 'total': os.path.getsize(path), 'mime': 'audio/mp4', 'done': True,
              'failed': False, 'cancelled': False, 'announced': True, 'error': ''}
        self._streams[name] = st
        return st

    @staticmethod
    def _codec_line(track):
        """What the track really is, for the TV picture: 'HMSA Opus 7.1  (stereo track: ATRAC3plus 352 kbps)', 'ATRAC3plus 352 kbps', 'ATRAC SP 292 kbps', 'PCM' ...
        The same names as the Codec column of the track list."""
        names = {'A3+': 'ATRAC3plus', 'AT3': 'ATRAC3', 'SP': 'ATRAC SP', 'SP mono': 'ATRAC SP mono', 'LP2': 'ATRAC3 LP2', 'LP4': 'ATRAC3 LP4', 'PCM': 'PCM', 'MP3': 'MP3'}
        c = str((track or {}).get('codec') or '').strip()
        stereo = (names.get(c, c) + (' %d kbps' % track['kbps'] if track.get('kbps') else '')).strip()
        sp = (track or {}).get('spatial')
        if sp:
            kind = 'Opus' if sp.get('codec') == 'opus' else 'Lossless'
            lay = sp.get('layout') or ('%s ch' % sp.get('channels') if sp.get('channels') else '')
            return ('HMSA %s %s' % (kind, lay)).strip() + ('  (stereo track: %s)' % stereo if stereo else '')
        return stereo

    def _surround_splash(self, track):
        """A 1280x720 picture for the TV to show while the 5.1 surround SOUND plays (that mode carries no video, and without a picture the TV's player shows
        nothing): the cover, title, artist, album and a line saying it is playing in 5.1. Made once per track and served like any other file.
        Returns the stream entry, or None when it cannot be made (the sound then plays with no picture, as before)."""
        try:
            import hashlib
            import io
            from PIL import Image, ImageDraw, ImageFont
            import lyrics
            cover = None
            if getattr(self, '_loaded_netmd', False):
                import disc_lookup
                cover = disc_lookup.cover_bytes(self._netmd_disc_key(self._tracks))
            else:
                url = self._ga_for_track(track.get('number')) or self._cover_url
                if url and url.startswith('data:'):
                    cover = base64.b64decode(url.split(',', 1)[1])
            title, artist = lyrics._split_title(track)
            title, artist, album = title or 'Track', artist or '', track.get('album') or ''
            line = '5.1 surround  ·  Dolby Digital Plus'
            name = 'splash-%s.jpg' % hashlib.sha1(repr((title, artist, album, line, self._caption(), self._codec_line(track), len(cover or b''))).encode('utf-8')).hexdigest()[:14]
            path = os.path.join(PLAY_DIR, name)
            if not os.path.exists(path):
                W, H = 1280, 720
                img = Image.new('RGB', (W, H), (14, 20, 28))
                d = ImageDraw.Draw(img)
                for y in range(H):                                              # a soft vertical gradient
                    k = y / H
                    d.line([(0, y), (W, y)], fill=(int(14 + 14 * k), int(20 + 18 * k), int(28 + 30 * k)))

                def font(size, bold=False):
                    return ui_font(size, bold)

                def fit(text, f, width):                                         # shorten a line that is too wide
                    while text and d.textlength(text, font=f) > width:
                        text = text[:-2].rstrip() + '…' if not text.endswith('…') else text[:-2] + '…'
                    return text
                x = 70
                if cover:
                    try:
                        c = Image.open(io.BytesIO(cover)).convert('RGB')
                        c.thumbnail((460, 460))
                        img.paste(c, (70, (H - c.height) // 2 - 10))
                        x = 70 + c.width + 60
                    except (OSError, ValueError):
                        pass
                tw = W - x - 60
                y = 210
                d.text((x, y), fit(title, font(58, True), tw), font=font(58, True), fill=(255, 255, 255)); y += 84
                if artist:
                    d.text((x, y), fit(artist, font(38), tw), font=font(38), fill=(210, 220, 232)); y += 56
                if album:
                    d.text((x, y), fit(album, font(30), tw), font=font(30), fill=(150, 165, 182)); y += 64
                d.text((x, y), fit(line, font(30, True), tw), font=font(30, True), fill=(92, 184, 255))
                cod = self._codec_line(track)                                    # the real codec, one line above the recorder line
                if cod:
                    d.text((70, H - 100), fit(cod, font(26, True), W - 140), font=font(26, True), fill=(150, 170, 190))
                cap = self._caption()
                if cap:
                    d.text((70, H - 62), fit(cap, font(24), W - 140), font=font(24), fill=(120, 134, 150))
                os.makedirs(PLAY_DIR, exist_ok=True)
                img.save(path + '.part', 'JPEG', quality=88)
                os.replace(path + '.part', path)
            st = {'key': 'splash-' + name, 'name': name, 'format': 'jpg', 'path': path, 'total': os.path.getsize(path), 'mime': 'image/jpeg', 'done': True,
                  'failed': False, 'cancelled': False, 'announced': True, 'error': ''}
            self._streams[name] = st
            return st
        except Exception as exc:
            self.log('surround splash picture failed: %s' % exc)
            return None

    def _surround_video(self, sound, pic):
        """The 5.1 sound (the stream `sound`, E-AC-3 in an MP4) plus the still splash picture `pic` as an ordinary VIDEO file. A Google TV's player only comes to
        the front for a video; for an audio-only file it stays in the background and shows nothing (which is what the sound-only mode did). The sound is copied
        unchanged, so the surround is exactly the same. Made once per track in a few seconds. Returns the stream entry, or None."""
        try:
            import hashlib
            name = 'surroundvid-%s.mp4' % hashlib.sha1((sound['name'] + pic['name'] + '25fps').encode('utf-8')).hexdigest()[:14]
            path = os.path.join(PLAY_DIR, name)
            if not (os.path.exists(path) and os.path.getsize(path) > 1000):
                tmp = path + '.part'
                ff, nowin = FFMPEG_EXE, getattr(subprocess, 'CREATE_NO_WINDOW', 0)
                # The picture never changes, so only 2 seconds of it are encoded (the same video settings as the lyric video; a Google TV needs them) and that
                # clip is repeated by copying: the whole video is made in well under a second instead of encoding every frame (about 12 s for 8 minutes).
                clip = os.path.join(PLAY_DIR, 'splashclip-%s.mp4' % hashlib.sha1((pic['name'] + '25fps').encode('utf-8')).hexdigest()[:14])
                r = None
                if not (os.path.exists(clip) and os.path.getsize(clip) > 500):
                    r = subprocess.run([ff, '-hide_banner', '-loglevel', 'error', '-y', '-loop', '1', '-framerate', '25', '-i', pic['path'], '-t', '2',
                                        '-vf', 'scale=in_range=full:out_range=tv,format=yuv420p'] + h264_args(25, 50) + ['-f', 'mp4', clip + '.part'], capture_output=True, text=True, creationflags=nowin)
                    if not r.returncode and os.path.exists(clip + '.part'):
                        os.replace(clip + '.part', clip)
                if os.path.exists(clip):
                    r = subprocess.run([ff, '-hide_banner', '-loglevel', 'error', '-y', '-stream_loop', '-1', '-i', clip, '-i', sound['path'], '-map', '0:v', '-map', '1:a',
                                        '-c:v', 'copy', '-c:a', 'copy', '-shortest', '-f', 'mp4', '-movflags', '+faststart', tmp],
                                       capture_output=True, text=True, creationflags=nowin)
                if r is None or r.returncode or not os.path.exists(tmp):          # the looped copy did not work: encode every frame, the slow way
                    r = subprocess.run([ff, '-hide_banner', '-loglevel', 'error', '-y', '-loop', '1', '-framerate', '25', '-i', pic['path'],
                                        '-i', sound['path'], '-map', '0:v', '-map', '1:a', '-vf', 'scale=in_range=full:out_range=tv,format=yuv420p'] + h264_args(25, 50) + [
                                        '-c:a', 'copy', '-shortest', '-f', 'mp4', '-movflags', '+faststart', tmp],
                                       capture_output=True, text=True, creationflags=nowin)
                if r.returncode or not os.path.exists(tmp):
                    self.log('surround picture video failed: %s' % (r.stderr or '').strip()[-300:])
                    return None
                os.replace(tmp, path)
            st = {'key': 'surround-' + name, 'name': name, 'format': 'mp4', 'path': path, 'total': os.path.getsize(path), 'mime': 'video/mp4', 'done': True,
                  'failed': False, 'cancelled': False, 'announced': True, 'error': ''}
            self._streams[name] = st
            return st
        except Exception as exc:
            self.log('surround picture video failed: %s' % exc)
            return None

    def _caption(self):
        """The small line at the bottom of the TV picture: the recorder and the kind of disc, e.g. 'MZ-NH700 - Playing an SP disc'."""
        name = self._recorder_name or ''
        try:
            if getattr(self, '_loaded_netmd', False):             # a standard MiniDisc: SP, LP2 or LP4 (a disc can mix them)
                modes = sorted({str(t.get('codec', '')).replace(' mono', '') for t in (self._tracks or []) if t.get('codec')} & {'SP', 'LP2', 'LP4'})
                if len(modes) == 1:
                    what = 'Playing an %s disc' % modes[0]                 # "an SP", "an LP2", "an LP4"
                else:
                    what = 'Playing a standard MiniDisc' + (' (%s)' % ' / '.join(modes) if modes else '')
            else:
                what = 'Playing a Hi-MD disc'
        except (AttributeError, TypeError):
            return name
        return (name + '  ·  ' if name else '') + what

    def _lyric_video(self, stream, track, lan, ip=None, start=0.0):
        """Starts making the lyric video for `track` (its audio is the file of `stream`) and returns the address the TV should play, or None.
        start: seconds into the track the video begins at (a remake after the visualizer was changed)."""
        try:
            if not stream or not os.path.exists(stream['path']):
                return None
            ly = self.lyrics_get(track.get('number')) if track.get('number') else {'none': True}
            lines = [(s, x) for s, x in ly.get('lines', []) if s is not None] if ly.get('synced') else []
            cover = None
            if getattr(self, '_loaded_netmd', False):                               # standard disc: the album art found online and kept on this PC (disc_lookup.py)
                import disc_lookup
                cover = disc_lookup.cover_bytes(self._netmd_disc_key(self._tracks))
            else:                                                                   # the picture of the track's group, else the disc's own picture
                url = self._ga_for_track(track.get('number')) or self._cover_url
                if url and url.startswith('data:'):
                    cover = base64.b64decode(url.split(',', 1)[1])
            import lyrics
            title, artist = lyrics._split_title(track)                              # "ARTIST - TITLE" titles of commercial discs: the artist is shown once
            vid = '%d' % int(time.time() * 1000)
            num, tracks = track.get('number'), self._tracks or []                   # the deck's track number / time display on the TV picture
            deck = {'pos': sum(1 for t in tracks if t['number'] <= num), 'count': len(tracks), 'length': float(track.get('seconds') or 0)} if num is not None and tracks else None
            note = self._spatial_note(track)
            job = lyricvideo.Job(FFMPEG_EXE, stream['path'], os.path.join(PLAY_DIR, 'lyricvideo-' + vid),
                                 title or 'Track', artist or '', lines, float(ly.get('offset') or 0), float(track.get('seconds') or 0),
                                 cover, self.log, growing=not stream.get('done'), caption=self._caption(), album=track.get('album') or '',
                                 viz=getattr(self, '_cast_viz', None), start=start, deck=deck, note=note)
            self._lv = {'id': vid, 'job': job, 'start': start, 'ctx': {'stream': stream, 'track': track, 'lan': lan, 'ip': ip}}
            ready = job.wait_ready()
            if not ready:
                self.log('lyric video: not ready (%s); playing the audio only' % (job.error or 'timed out'))
                self._lv_stop()
                return None
            return 'http://%s:%d/%s/lv/%s/%s' % (lan, self._cast_port, self._token, vid, 'index.m3u8')
        except (OSError, ValueError) as exc:
            self.log('lyric video failed: %s' % exc)
            self._lv_stop()
            return None

    def _is_cast_device(self, ip):
        self._cast_devices()
        return ip in self._cast_tvs

    def _cast_to_device(self, action, device_index, track_index, seconds, ip):
        """Same contract as cast(), for a Google Cast device."""
        try:
            dev = chromecast.Device(ip)
            viz_url = None
            if action == 'play':
                self._cast_seq += 1
                mine, t0 = self._cast_seq, time.time()
                tr0 = next((t for t in self._tracks if t['number'] == int(track_index) + 1), None) or {}
                r = None
                surround = bool(tr0.get('spatial')) and bool(self._app_setting('spatialTvSurround')) and not getattr(self, '_loaded_netmd', False)
                if surround:
                    early = {}                                                       # the TV's files, started the moment the disc read is over (while the headphone picture renders)
                    tr_e = dict(tr0)

                    def _early():
                        def work():
                            try:
                                te = time.time()
                                s_ = self._surround_audio(tr_e)
                                p_ = self._surround_splash(tr_e) if s_ else None
                                early.update(sound=s_, pic=p_, vid=self._surround_video(s_, p_) if s_ and p_ else None, secs=time.time() - te)
                            except Exception as exc:
                                self.log('spatial surround (early) failed: %s' % exc)
                        early['thread'] = threading.Thread(target=work, daemon=True)
                        early['thread'].start()
                    tp = time.time()
                    r = self.play_spatial(int(device_index), int(track_index) + 1, on_pulled=_early)    # also pulls the spatial file, and gives a stereo picture of it for the visualizer
                    self.log('cast: disc read + headphone picture took %.1fs' % (time.time() - tp))
                    self.log('cast: play_spatial for the TV -> %s' % ('error: ' + r['error'] if 'error' in r else 'ok'))
                    if 'error' in r:
                        self.log('cast: spatial version not used (%s)' % r['error'])
                        r, surround = None, False
                if r is None:
                    r = self.play_prepare(int(device_index), int(track_index) + 1)
                if r.get('superseded') or mine != self._cast_seq:
                    return {'superseded': True}
                if 'error' in r:
                    return r
                viz_url = r.get('url')                                              # the window runs a silent copy of this track so its visualizer keeps moving
                t1 = time.time()
                lan = sonos.local_ip_towards(ip)
                self._ensure_cast_server(lan)
                path = r['url'].split('//', 1)[1].split('/', 1)[1]
                name = path.rsplit('/', 1)[-1]
                st = next((s for s in self._streams.values() if s['name'] == name), None)
                track = dict(next((t for t in self._tracks if t['number'] == int(track_index) + 1), None) or {})
                if getattr(self, '_loaded_netmd', False):                           # standard disc: no artist / album stored, so use what the disc is called
                    dt = getattr(self, '_netmd_disc_title', '') or track.get('group') or ''
                    if dt and not track.get('album'):
                        track['album'] = dt
                url, mime = 'http://%s:%d/%s' % (lan, self._cast_port, path), st['mime'] if st else 'audio/wav'
                self._lv_stop()
                sur_st, pic, vid = None, None, None
                if surround:                                                        # sound only: a Google TV shows no picture while it passes surround on, so no lyric video is made
                    try:
                        if early.get('thread'):                                     # already being made since the disc read finished
                            early['thread'].join()
                            sur_st, pic, vid = early.get('sound'), early.get('pic'), early.get('vid')
                            if early.get('secs') is not None:
                                self.log('cast: TV surround files made in %.1fs' % early['secs'])
                        if not sur_st:
                            sur_st = self._surround_audio(track)
                    except Exception as exc:
                        self.log('spatial surround failed: %s' % exc)
                if sur_st:
                    if not pic:
                        pic = self._surround_splash(track)
                    if not vid:
                        vid = self._surround_video(sur_st, pic) if pic else None        # sound + still picture as a video: the TV's player then comes to the front
                    fu, fm = ((vid['name'], 'video/mp4') if vid else (sur_st['name'], 'audio/mp4'))
                    album = ((track.get('album') or '') + '  ·  ' if track.get('album') else '') + 'Spatial 5.1 (Dolby Digital Plus)'
                    tq = time.time()
                    dev.play_url('http://%s:%d/%s/%s' % (lan, self._cast_port, self._token, fu), track.get('title'), fm, track.get('artist'), album,
                                 video=bool(vid), source=self._recorder_name or None, confirm=True)
                    self.log('cast: the TV took %.1fs to start playing' % (time.time() - tq))
                    kind = 'surround video with splash picture' if vid else 'surround audio (no picture)'
                else:
                    if self._cast_video:
                        vurl = self._lyric_video(st, track, lan, ip)               # None when it could not be made: the TV then just gets the audio
                        if vurl:
                            url, mime = vurl, 'application/x-mpegurl'
                    video = mime.startswith('application/x-mpegurl')
                    dev.play_url(url, track.get('title'), mime, track.get('artist'), track.get('album'), video=video,
                                 source=self._recorder_name or None)
                    kind = 'lyric video' if video else 'audio only'
                self._cast_last = {'ip': ip, 'prefix': 'http://%s:%d/' % (lan, self._cast_port), 'cast': True}
                self.log('cast (Google Cast) play track %d (%s): track ready after %.1fs, device told in %.1fs' % (int(track_index) + 1, kind, t1 - t0, time.time() - t1))
                if kind.startswith('surround'):                                     # read the next spatial track ahead while this one plays
                    self._sp_prefetch_next(int(track_index) + 1, mine)
            elif action in ('pause', 'resume', 'stop', 'seek'):
                if action == 'stop':
                    self._lv_stop()
                base = getattr(self, '_lv_base', 0.0)
                if action == 'seek' and base and float(seconds) < base:             # before where the remade video starts: remake it from there
                    r = self._lv_restart(at=float(seconds))
                    if 'error' in r:
                        return r
                else:
                    dev.control({'resume': 'play'}.get(action, action), max(0, float(seconds) - base) if action == 'seek' else seconds)
            elif action != 'status':
                return {'error': 'Unknown action: %s' % action}
            st = dev.status()
            base = getattr(self, '_lv_base', 0.0)                                    # the TV counts a remade video from 0; the page counts the track
            out = {'result': {'state': st['state'], 'track': int(track_index), 'seconds': st['seconds'] + int(base) if st['state'] != 'ready' else 0,
                              'duration': st['duration'] + int(base) if st['duration'] > 0 else st['duration']}}
            if viz_url:
                out['viz_url'] = viz_url
            return out
        except (chromecast.CastError, OSError) as exc:
            return {'error': str(exc)}

    # The speaker fetches the track itself from a small web server on this PC (the same files the window plays, behind the same
    # secret in the address). The page controls it like the NetMD remote: play, pause, seek, position, volume.
    _SONOS_CACHE = os.path.join(APPDATA, 'sonos.json')

    def _remembered_speakers(self):
        if not self._cast_known:
            try:
                with open(self._SONOS_CACHE, encoding='utf-8') as f:
                    self._cast_known = {ip: None for ip in json.load(f)}
            except (OSError, ValueError):
                pass
        return self._cast_known

    def cast_rooms(self, refresh=True):
        """The Sonos rooms. refresh=False asks speakers found last time (instant); refresh=True searches the network (a few seconds)."""
        devices = self._cast_devices(refresh)
        try:
            rooms = []
            if not refresh:
                known = self._remembered_speakers()
                rooms = sonos.rooms(known) if known else []
                return {'rooms': [{'name': r['name'], 'ip': r['ip']} for r in rooms] + devices, 'cached': True}
            found = sonos.discover()
            if found:
                self._cast_known = found
                try:
                    os.makedirs(os.path.dirname(self._SONOS_CACHE), exist_ok=True)
                    with open(self._SONOS_CACHE, 'w', encoding='utf-8') as f:
                        json.dump(sorted(found), f)
                except OSError:
                    pass                                          # only means the next list is not instant
            rooms = sonos.rooms(found)
        except (sonos.SonosError, OSError) as exc:
            if devices:
                return {'rooms': devices}                         # no Sonos answered, but a TV or Cast speaker did
            return {'error': 'Could not search for Sonos speakers: %s' % exc}
        allrooms = [{'name': r['name'], 'ip': r['ip']} for r in rooms] + devices
        if not allrooms:
            return {'rooms': [], 'note': 'No Sonos speakers or Google TV / Chromecast devices answered. They must be on the same network as this PC, and Windows Firewall must allow this app on private networks.'}
        return {'rooms': allrooms}

    def _ensure_cast_server(self, lan_ip):
        if self._cast_server is not None and self._cast_ip == lan_ip:
            return
        if self._cast_server is not None:
            self._cast_server.shutdown()
            self._cast_server.server_close()
        self._cast_server = http.server.ThreadingHTTPServer((lan_ip, 0), mediaserver.media_handler(self))
        self._cast_server.daemon_threads = True
        self._cast_ip, self._cast_port = lan_ip, self._cast_server.server_address[1]
        threading.Thread(target=self._cast_server.serve_forever, daemon=True).start()

    def cast(self, action, device_index, track_index, seconds, ip):
        """Controls the Sonos room whose coordinator is at `ip`. Answers like remote(): {'result': {state, track, seconds}}."""
        if self._is_cast_device(ip):
            return self._cast_to_device(action, device_index, track_index, seconds, ip)
        try:
            sp = sonos.Speaker(ip)
            if action == 'play':
                self._cast_seq += 1
                mine, t0 = self._cast_seq, time.time()
                r = self.play_prepare(int(device_index), int(track_index) + 1)           # starts reading the track, gives its local address
                if r.get('superseded') or mine != self._cast_seq:
                    return {'superseded': True}                                       # the user already chose another track
                if 'error' in r:
                    return r
                t1 = time.time()
                lan = sonos.local_ip_towards(ip)
                self._ensure_cast_server(lan)
                path = r['url'].split('//', 1)[1].split('/', 1)[1]
                name = path.rsplit('/', 1)[-1]
                st = next((s for s in self._streams.values() if s['name'] == name), None)
                track = next((t for t in self._tracks if t['number'] == int(track_index) + 1), None)
                sp.play_url('http://%s:%d/%s' % (lan, self._cast_port, path), (track or {}).get('title'), st['mime'] if st else 'audio/wav')
                self._cast_last = {'ip': ip, 'prefix': 'http://%s:%d/' % (lan, self._cast_port)}
                t2 = time.time()
                for _ in range(10):                            # the speaker says "stopped" for a moment before it starts to fetch
                    if sp.status()['state'] != 'ready':
                        break
                    time.sleep(0.4)
                self.log('cast play track %d: track ready after %.1fs, speaker told in %.1fs, speaker started %.1fs later' % (int(track_index) + 1, t1 - t0, t2 - t1, time.time() - t2))
            elif action == 'pause':
                sp.pause()
            elif action == 'resume':
                sp.play()
            elif action == 'stop':
                sp.stop()
            elif action == 'seek':
                sp.seek(seconds)
            elif action != 'status':
                return {'error': 'Unknown action: %s' % action}
            st = sp.status()
            out = {'result': {'state': st['state'], 'track': int(track_index), 'seconds': st['seconds'], 'duration': st['duration']}}
            if action == 'play':
                out['viz_url'] = r['url']                      # the window runs a silent copy of this track so its visualizer keeps moving
            return out
        except sonos.SonosError as exc:
            return {'error': str(exc)}

    def stop_cast(self):
        """Stops the room this app was playing to - but only if it is still playing one of our tracks, never something else."""
        last = self._cast_last
        self._lv_stop()
        if not last:
            return False
        try:
            if last.get('cast'):
                dev = chromecast.Device(last['ip'])
                st = dev.status()
                if st['uri'].startswith(last['prefix']) and st['state'] != 'ready':
                    dev.control('stop')
                    return True
                return False
            sp = sonos.Speaker(last['ip'])
            if sp.current_uri().startswith(last['prefix']) and sp.status()['state'] != 'ready':
                sp.stop()
                return True
        except (sonos.SonosError, chromecast.CastError, OSError):
            pass                                                # the speaker is gone: nothing to stop
        finally:
            self._cast_last = None
        return False

    def cast_volume(self, ip, value=None):
        try:
            sp = chromecast.Device(ip) if self._is_cast_device(ip) else sonos.Speaker(ip)
            if value is not None:
                t0 = time.time()
                sp.set_volume(value)
                if time.time() - t0 > 0.25:
                    self.log('volume: one step took %.2fs (%s)' % (time.time() - t0, ip))      # a new connection to the TV; steps on a kept connection take milliseconds
                return {'volume': max(0, min(100, int(round(float(value)))))}      # no read-back: it cost a second round trip per step
            return {'volume': sp.volume()}
        except (sonos.SonosError, chromecast.CastError, OSError) as exc:
            return {'error': str(exc)}
