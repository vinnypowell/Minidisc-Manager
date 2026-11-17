"""Splitting one long recording into tracks on this PC BEFORE it is added to a disc (the Add window's "split first" option). PresplitMixin is mixed into himd_app.Api.

The file is cut with ffmpeg into one lossless file per track (FLAC; WAV when it has more than 8 channels; an MP3 stays an MP3 by copying), each carrying the source's tags
plus its own title and track number, in a temporary folder. The page then plans the Add again with those files, so spatial (5.1 / 7.1) pieces get their own spatial version
exactly as separate files would. Nothing is written to the disc here and the source file is never changed."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time

from mdm_paths import HERE

FFMPEG = os.path.join(HERE, 'runtime', 'ffmpeg.exe')
NOWIN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
PS_PREFIX = 'mdm-presplit-'
_LAYOUT_CH = {'mono': 1, 'stereo': 2, '2.1': 3, '3.0': 3, '3.1': 4, 'quad': 4, '4.0': 4, '4.1': 5, '5.0': 5, '5.1': 6, '6.0': 6, '6.1': 7, '7.0': 7, '7.1': 8}


def _channels(layout):
    """Channel count from ffmpeg's layout text: 'stereo', '5.1(side)', '7.1.4', '6 channels'."""
    layout = (layout or '').strip()
    m = re.match(r'^(\d+) channels?', layout)
    if m:
        return int(m.group(1))
    base = re.sub(r'\(.*?\)', '', layout)
    if base in _LAYOUT_CH:
        return _LAYOUT_CH[base]
    m = re.match(r'^(\d+)\.(\d+)(?:\.(\d+))?$', base)
    return sum(int(x) for x in m.groups() if x) if m else 2


def _clock(text):
    h = re.match(r'^(\d+):(\d+):(\d+(?:\.\d+)?)$', text)
    if h:
        return int(h.group(1)) * 3600 + int(h.group(2)) * 60 + float(h.group(3))
    return None


def _safe(name):
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', '_', str(name or '')).strip(' .')
    return s[:80] or 'track'


class PresplitMixin:
    _ps_cancel = False
    _ps_proc = None
    _ps_dir = None

    def _ps_say(self, **msg):
        if getattr(self, '_window', None):
            try:
                self._window.evaluate_js('window.onPresplitProgress && window.onPresplitProgress(%s)' % json.dumps(msg))
            except Exception:
                pass

    def _ps_run(self, args, capture=True):
        p = subprocess.Popen([FFMPEG, '-hide_banner'] + args, stdout=subprocess.PIPE if capture else subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=NOWIN)
        self._ps_proc = p
        try:
            out, err = p.communicate()
        finally:
            self._ps_proc = None
        return p.returncode, out, err.decode('utf-8', 'replace')

    def presplit_probe(self, path):
        """What the Add window needs to know about one source file: length, channel count, and the chapters (or CUE tracks) it carries, if any.
        Returns {'seconds', 'channels', 'codec', 'chapters': [{'title', 'start'}]} or {'error'}."""
        if not path or not os.path.isfile(path):
            return {'error': 'That file is not there any more.'}
        _rc, _out, err = self._ps_run(['-i', path])
        m = re.search(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)', err)
        if not m:
            return {'error': 'The length of this file could not be read.'}
        seconds = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        s = re.search(r'Stream #\d+:\d+[^\n]*?: Audio: (\w+)[^,\n]*?, (\d+) Hz, ([^,\n]+)', err)
        chapters, last = [], None
        for line in err.splitlines():
            c = re.match(r'\s*Chapter #\d+:\d+: start ([\d.]+), end ([\d.]+)', line)
            if c:
                chapters.append({'title': '', 'start': float(c.group(1))})
                last = chapters[-1]
                continue
            t = re.match(r'\s*title\s*:\s*(.+)$', line)
            if t and last is not None and not last['title']:
                last['title'] = t.group(1).strip()
        if len(chapters) < 2:
            chapters = []
        return {'seconds': seconds, 'codec': s.group(1) if s else '', 'rate': int(s.group(2)) if s else 0, 'channels': _channels(s.group(3)) if s else 2, 'chapters': chapters}

    def _ps_quiet(self, path, t, window, total):
        """The quietest moment within `window` seconds of time t (the file is decoded there only, as mono 8 kHz). Returns the time, or t when it cannot tell."""
        try:
            import numpy as np
            lo = max(0.0, t - window)
            hi = min(total, t + window)
            if hi - lo < 0.5:
                return t
            rc, out, _err = self._ps_run(['-v', 'error', '-ss', '%.3f' % lo, '-t', '%.3f' % (hi - lo), '-i', path, '-vn', '-ac', '1', '-ar', '8000', '-f', 'f32le', '-'])
            if rc or not out:
                return t
            x = np.frombuffer(out, dtype='<f4')
            frame = 200                                                  # 25 ms
            n = len(x) // frame
            if n < 8:
                return t
            e = np.sqrt((x[:n * frame].reshape(n, frame) ** 2).mean(axis=1))
            k = 4                                                        # a 100 ms stretch, so a single quiet sample does not win
            sm = np.convolve(e, np.ones(k) / k, mode='valid')
            i = int(np.argmin(sm))
            lim = sm[i] * 1.25 + 1e-5                                    # a quiet gap is a flat stretch: cut in the middle of it, not at its edge
            a = b = i
            while a > 0 and sm[a - 1] <= lim:
                a -= 1
            while b < len(sm) - 1 and sm[b + 1] <= lim:
                b += 1
            return lo + ((a + b) / 2.0 + k / 2.0) * frame / 8000.0
        except Exception:
            return t

    def presplit_run(self, path, tracks, mode='lengths', snap=True):
        r = self._ps_work(path, tracks, mode, snap)
        if 'files' not in r:
            self.presplit_clear()                                        # an error or a cancel leaves nothing behind
        return r

    def _ps_work(self, path, tracks, mode, snap):
        """Cuts `path` into the tracks. tracks: [{'title', 'seconds'}] (mode 'lengths': each track's length, the last one may be empty and runs to the end) or
        [{'title', 'start'}] (mode 'starts': where each track starts). snap: move each cut to the quietest moment within 2 s of where the list puts it.
        Returns {'files': [{'path', 'title', 'seconds'}], 'dir'} or {'error'} / {'cancelled'}."""
        self._ps_cancel = False
        info = self.presplit_probe(path)
        if 'error' in info:
            return info
        total = info['seconds']
        n = len(tracks or [])
        if n < 2:
            return {'error': 'Give at least two tracks to split the file into.'}
        self.presplit_clear()
        folder = tempfile.mkdtemp(prefix=PS_PREFIX)
        self._ps_dir = folder
        try:
            # 1. where each cut goes
            cuts = [0.0]
            if mode == 'starts':
                starts = [float(t.get('start') or 0) for t in tracks]
                if starts[0] > 0.5:
                    cuts[0] = starts[0]
                targets = starts[1:]
            else:
                pos, targets = cuts[0], []
                for t in tracks[:-1]:
                    pos += float(t.get('seconds') or 0)
                    targets.append(pos)
            for i, tg in enumerate(targets):
                if self._ps_cancel:
                    return {'cancelled': True}
                self._ps_say(phase='find', n=i, count=n - 1)
                if tg >= total - 1.0:
                    return {'error': 'The list puts the cut after track %d at %s, but the file is only %s long.' % (i + 1, self._ps_len(tg), self._ps_len(total))}
                at = self._ps_quiet(path, tg, 2.0, total) if snap else tg
                if mode == 'lengths':                                    # the next length counts from where this cut really is
                    shift = at - tg
                    targets[i + 1:] = [x + shift for x in targets[i + 1:]]
                if at <= cuts[-1] + 1.0:
                    return {'error': 'Track %d would be shorter than a second. Check the lengths in the list.' % (i + 1)}
                cuts.append(at)
            cuts.append(total)
            # 2. the pieces
            codec = info['codec']
            lossy_copy = codec == 'mp3'
            ext = 'mp3' if lossy_copy else ('wav' if info['channels'] > 8 else 'flac')
            files = []
            for i in range(n):
                if self._ps_cancel:
                    return {'cancelled': True}
                title = (tracks[i].get('title') or '').strip() or 'Track %d' % (i + 1)
                out = os.path.join(folder, '%02d - %s.%s' % (i + 1, _safe(title), ext))
                self._ps_say(phase='cut', n=i, count=n, name=title)
                start, end = cuts[i], cuts[i + 1]
                args = ['-v', 'error', '-y', '-ss', '%.6f' % start, '-i', path, '-t', '%.6f' % (end - start), '-vn', '-map', '0:a:0', '-map_metadata', '0',
                        '-metadata', 'title=%s' % title, '-metadata', 'track=%d/%d' % (i + 1, n)]
                args += ['-c:a', 'copy'] if lossy_copy else (['-c:a', 'pcm_s24le'] if ext == 'wav' else ['-c:a', 'flac'])
                rc, _o, err = self._ps_run(args + [out], capture=False)
                if self._ps_cancel:
                    return {'cancelled': True}
                if rc or not os.path.isfile(out) or os.path.getsize(out) < 100:
                    return {'error': 'Cutting “%s” failed: %s' % (title, err.strip()[-200:] or 'ffmpeg stopped')}
                files.append({'path': out, 'title': title, 'seconds': end - start})
            return {'files': files, 'dir': folder, 'cuts': [round(c, 3) for c in cuts]}
        except Exception as exc:
            return {'error': 'The file could not be split: %s' % exc}

    @staticmethod
    def _ps_len(sec):
        sec = int(round(sec))
        return '%d:%02d:%02d' % (sec // 3600, sec % 3600 // 60, sec % 60) if sec >= 3600 else '%d:%02d' % (sec // 60, sec % 60)

    def presplit_cancel(self):
        self._ps_cancel = True
        p = self._ps_proc
        if p is not None:
            try:
                p.kill()
            except Exception:
                pass
        return {'ok': True}

    def presplit_clear(self):
        """Removes the pieces made earlier (the Add that used them has finished, or a new split starts)."""
        d, self._ps_dir = self._ps_dir, None
        if d:
            shutil.rmtree(d, ignore_errors=True)
        return {'ok': True}
