"""Spatial (multichannel / Dolby Atmos bed) sidecars: the "HMSA" container (Hi-MD Spatial Audio), its lossless (WavPack) / Opus encoding, and the binaural renderer.

A spatial track on a Hi-MD disc is TWO things: an ordinary stereo downmix track (which the recorder plays by itself) and one hidden file in the
disc's root folder (SPnnnnnn.HMS) that holds every channel of the original mix. The recorder ignores the file; this program plays it.

Container (all numbers little-endian):
    'HMSA' | version u8 (=1) | codec u8 (1 lossless WavPack, 2 Opus) | channels u8 | 0 | sample rate u32 | duration in ms u32 | JSON length u32 | JSON | payload
The JSON holds the channel names in file order (FL FR FC LFE ...), the layout name, the title, the bit rate and the source name. The payload is
a complete .wv (WavPack) file or Ogg Opus file made by the bundled ffmpeg, so playing back is just "ffmpeg -i payload".

Only channel-based mixes are handled (a bed of 5.1 / 7.1 / 5.1.4 / 7.1.4 / 9.1.6 channels). Dolby's object metadata and its encrypted streams are
not touched: a file this program cannot decode with its own ffmpeg is simply refused.

SpatialMixin is mixed into himd_app.Api; the rest is plain functions so they can be tested alone."""
import json
import math
import os
import re
import struct
import subprocess
import threading

import numpy as np

from mdm_paths import HERE

MAGIC = b'HMSA'                                   # what new files start with
OLD_MAGIC = b'HMSP'                               # the first test files were written with this name; they are still read
VERSION = 1
CODEC_LOSSLESS, CODEC_OPUS = 1, 2                     # lossless is WavPack: FLAC cannot hold more than 8 channels, WavPack can hold the 12 of a 7.1.4 mix
CODEC_NAMES = {CODEC_LOSSLESS: 'lossless', CODEC_OPUS: 'opus'}
FFMPEG = os.path.join(HERE, 'runtime', 'ffmpeg.exe')
NOWIN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

# Channel names in the order ffmpeg (and a WAV file's channel mask) store them.
ORDER = ['FL', 'FR', 'FC', 'LFE', 'BL', 'BR', 'FLC', 'FRC', 'BC', 'SL', 'SR', 'TC', 'TFL', 'TFC', 'TFR', 'TBL', 'TBC', 'TBR', 'WL', 'WR', 'TSL', 'TSR']
LAYOUTS = {                                              # ffmpeg's layout names
    '5.1': 'FL FR FC LFE BL BR', '5.1(side)': 'FL FR FC LFE SL SR', '7.1': 'FL FR FC LFE BL BR SL SR', '5.1.2': 'FL FR FC LFE SL SR TFL TFR',
    '5.1.4': 'FL FR FC LFE SL SR TFL TFR TBL TBR', '7.1.2': 'FL FR FC LFE BL BR SL SR TFL TFR', '7.1.4': 'FL FR FC LFE BL BR SL SR TFL TFR TBL TBR',
    '9.1.4': 'FL FR FC LFE BL BR FLC FRC SL SR TFL TFR TBL TBR', '9.1.6': 'FL FR FC LFE BL BR FLC FRC SL SR TFL TFR TBL TBR TSL TSR',
}
LAYOUTS = {k: v.split() for k, v in LAYOUTS.items()}
DEFAULT_BY_COUNT = {6: '5.1', 8: '7.1', 10: '7.1.2', 12: '7.1.4', 14: '9.1.4', 16: '9.1.6'}      # when a file does not say which layout it is
OPUS_KBPS = {'low': 256, 'medium': 512, 'high': 768}        # total for all channels; ~21 / 43 / 64 kbps per channel for 12 channels
MAX_CHANNELS = 16
SPATIAL_MIN_CHANNELS = 6


class SpatialError(RuntimeError):
    pass


def _run(args, stdin=None, capture=True, timeout=None):
    if not os.path.exists(FFMPEG):
        raise SpatialError('The bundled decoder is missing (%s).' % FFMPEG)
    return subprocess.run([FFMPEG, '-hide_banner'] + args, capture_output=capture, stdin=stdin, timeout=timeout, creationflags=NOWIN)


# ---------------------------------------------------------------------------------------------------------------------------------------
# Looking at a source file
# ---------------------------------------------------------------------------------------------------------------------------------------
def probe(path):
    """{'channels', 'layout' (a name from LAYOUTS or ''), 'rate', 'seconds', 'spatial': True when it has 6+ channels}, or {'error': ...}."""
    try:
        r = _run(['-i', path], timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return {'error': str(exc)}
    text = (r.stderr or b'').decode('utf-8', 'replace')
    m = re.search(r'Stream #\d+:\d+[^:]*: Audio: ([^,]+), (\d+) Hz, ([^,]+)', text)
    if not m:
        return {'error': 'No audio was found in this file.'}
    rate, lay = int(m.group(2)), m.group(3).strip()
    n = _channel_count(lay)
    d = re.search(r'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)', text)
    secs = int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3)) if d else 0.0
    name = lay if lay in LAYOUTS else ''
    if not name and n in DEFAULT_BY_COUNT:
        name = DEFAULT_BY_COUNT[n]
    if lay == '5.1(side)' or lay == '5.1':
        name = lay
    return {'channels': n, 'layout': name, 'declared': lay in LAYOUTS or lay in ('stereo', 'mono'), 'rate': rate, 'seconds': round(secs, 2),
            'spatial': n >= SPATIAL_MIN_CHANNELS and n <= MAX_CHANNELS, 'codec': m.group(1).split()[0],
            'choices': [k for k, v in LAYOUTS.items() if len(v) == n]}


def _channel_count(lay):
    m = re.match(r'(\d+) channels', lay)
    if m:
        return int(m.group(1))
    if lay in LAYOUTS:
        return len(LAYOUTS[lay])
    if lay == 'mono':
        return 1
    if lay == 'stereo':
        return 2
    m = re.match(r'(\d+)\.(\d)(?:\.(\d+))?', lay)                    # an unlisted "x.y.z" name
    return int(m.group(1)) + int(m.group(2)) + int(m.group(3) or 0) if m else 0


def channel_names(layout):
    if layout not in LAYOUTS:
        raise SpatialError('The channel layout "%s" is not one this program can handle.' % layout)
    return sorted(LAYOUTS[layout], key=ORDER.index)


# ---------------------------------------------------------------------------------------------------------------------------------------
# The container
# ---------------------------------------------------------------------------------------------------------------------------------------
def peek(path):
    """The header of a spatial file (no payload): codec, channels, rate, seconds, names, layout, quality."""
    return unpack(path, want_payload=False)[0]


def pack(payload, codec, names, rate, seconds, meta):
    head = dict(meta or {})
    head['names'] = names
    js = json.dumps(head, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return MAGIC + struct.pack('<BBBBIII', VERSION, codec, len(names), 0, int(rate), int(round(seconds * 1000)), len(js)) + js + payload


def unpack(data_or_path, want_payload=True):
    """Returns (info dict, payload bytes). info: codec ('lossless'|'opus'), channels, rate, seconds, names, plus whatever the JSON holds."""
    if isinstance(data_or_path, (bytes, bytearray)):
        data = bytes(data_or_path)
    else:
        with open(data_or_path, 'rb') as f:
            data = f.read() if want_payload else f.read(1 << 16)
    if data[:4] not in (MAGIC, OLD_MAGIC) or len(data) < 24:
        raise SpatialError('This is not a spatial audio file.')
    ver, codec, ch, _, rate, ms, jl = struct.unpack('<BBBBIII', data[4:20])
    if ver != VERSION or codec not in CODEC_NAMES:
        raise SpatialError('This spatial file was made by a newer version of the program.')
    head = json.loads(data[20:20 + jl].decode('utf-8'))
    info = dict(head)
    info.update({'codec': CODEC_NAMES[codec], 'channels': ch, 'rate': rate, 'seconds': ms / 1000.0, 'payloadOffset': 20 + jl})
    return info, (data[20 + jl:] if want_payload else b'')


# ---------------------------------------------------------------------------------------------------------------------------------------
# Making one
# ---------------------------------------------------------------------------------------------------------------------------------------
DOWNMIX_L = {'FL': 1.0, 'FC': .707, 'BL': .707, 'SL': .707, 'TFL': .5, 'TBL': .5, 'TSL': .5, 'FLC': .707, 'TC': .35, 'BC': .5, 'LFE': .5, 'WL': .707}
DOWNMIX_R = {'FR': 1.0, 'FC': .707, 'BR': .707, 'SR': .707, 'TFR': .5, 'TBR': .5, 'TSR': .5, 'FRC': .707, 'TC': .35, 'BC': .5, 'LFE': .5, 'WR': .707}


def downmix_filter(names):
    """An ffmpeg pan filter that folds the channels to stereo (heights into the sides and fronts, LFE kept low), scaled so a full mix cannot clip."""
    def side(table):
        terms = [(table[n], i) for i, n in enumerate(names) if n in table]
        norm = 1.0 / max(1.0, sum(c for c, _ in terms) * 0.55)
        return '+'.join('%.4f*c%d' % (c * norm, i) for c, i in terms)
    return 'pan=stereo|c0=%s|c1=%s' % (side(DOWNMIX_L), side(DOWNMIX_R))


def downmix(src, out, layout, cancel=None):
    """Writes the stereo 16-bit 44.1 kHz WAV `out` (the part of a spatial track the recorder plays) from the multichannel file `src`."""
    names = channel_names(layout)
    r = _run(['-y', '-loglevel', 'error', '-i', src, '-vn', '-map', '0:a:0', '-map_metadata', '-1', '-af', downmix_filter(names), '-ar', '44100',
              '-c:a', 'pcm_s16le', '-f', 'wav', out], timeout=3600)
    if r.returncode:
        raise SpatialError('Could not make the stereo version: %s' % (r.stderr.decode('utf-8', 'replace').strip()[-300:] or 'unknown error'))


SURROUND_FOLD = {                                         # output channel -> {input channel: gain}: floor channels pass, heights are folded in
    'FL': {'FL': 1.0, 'FLC': .707, 'TFL': .707, 'WL': .5}, 'FR': {'FR': 1.0, 'FRC': .707, 'TFR': .707, 'WR': .5},
    'FC': {'FC': 1.0, 'TFC': .707, 'TC': .5}, 'LFE': {'LFE': 1.0},
    'SL': {'SL': 1.0, 'TSL': .707}, 'SR': {'SR': 1.0, 'TSR': .707},
    'BL': {'BL': 1.0, 'TBL': .707, 'BC': .707}, 'BR': {'BR': 1.0, 'TBR': .707, 'BC': .707},
}


def surround_filter(names, mode):
    """An ffmpeg pan filter that mixes the channels down to a 5.1 or 7.1 bed for a TV (heights folded into the floor channels, since a TV cannot take
    more than 7.1 from an app). Returns (filter, mode actually used, channel count); a source without both side and back pairs can only give 5.1."""
    has = set(names)
    if mode == '7.1' and not ({'SL', 'SR'} <= has and {'BL', 'BR'} <= has):
        mode = '5.1'
    outs = ['FL', 'FR', 'FC', 'LFE', 'BL', 'BR', 'SL', 'SR'] if mode == '7.1' else ['FL', 'FR', 'FC', 'LFE', 'BL', 'BR']
    terms = []
    for o in outs:
        src = dict(SURROUND_FOLD[o])
        if mode == '5.1' and o in ('BL', 'BR'):                # the side and back channels share the two rear speakers
            src.update(SURROUND_FOLD['SL' if o == 'BL' else 'SR'])
        pairs = [(g, names.index(n)) for n, g in src.items() if n in has]
        if not pairs:
            terms.append('%s=0*c0' % o)
            continue
        norm = 1.0 / max(1.0, 0.75 * sum(g for g, _ in pairs))
        terms.append('%s=%s' % (o, '+'.join('%.4f*c%d' % (g * norm, i) for g, i in pairs)))
    return 'pan=%s|%s' % (mode, '|'.join(terms)), mode, len(outs)


def unpack_audio(hms_path, out_path):
    """Writes the audio inside a spatial file (an Ogg Opus or WavPack file) to out_path, for ffmpeg to read. Returns the file's info dict."""
    info, payload = unpack(hms_path)
    with open(out_path, 'wb') as f:
        f.write(payload)
    return info


def encode(src, out, codec='opus', quality='medium', layout='', title='', progress=None, cancel=None):
    """Writes the spatial container `out` from the multichannel file `src`. codec 'lossless' | 'opus'; quality 'low' | 'medium' | 'high' (Opus only).
    Returns {'bytes', 'seconds', 'channels', 'layout', 'codec'}."""
    info = probe(src)
    if 'error' in info:
        raise SpatialError(info['error'])
    if not info['spatial']:
        raise SpatialError('This file has %d channel(s); spatial audio needs 6 to %d (5.1, 7.1, 5.1.4, 7.1.4, ...).' % (info['channels'], MAX_CHANNELS))
    layout = layout or info['layout']
    names = channel_names(layout)
    if len(names) != info['channels']:
        raise SpatialError('The layout %s has %d channels but the file has %d.' % (layout, len(names), info['channels']))
    codec = 'lossless' if codec in ('lossless', 'flac', 'wavpack') else 'opus'
    tmp = out + '.part'
    rate = 48000 if codec == 'opus' else (info['rate'] if info['rate'] in (44100, 48000, 88200, 96000) else 48000)
    args = ['-y', '-loglevel', 'error', '-i', src, '-vn', '-map', '0:a:0', '-map_metadata', '-1', '-ar', str(rate)]
    if codec == 'lossless':
        args += ['-c:a', 'wavpack', '-compression_level', '3', '-f', 'wv']
        kbps = 0
    else:
        kbps = OPUS_KBPS.get(quality, OPUS_KBPS['medium']) * len(names) // 12
        args += ['-c:a', 'libopus', '-b:a', '%dk' % kbps, '-vbr', 'on', '-application', 'audio', '-mapping_family', '255', '-f', 'opus']
    args += [tmp]
    try:
        p = subprocess.Popen([FFMPEG, '-hide_banner'] + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NOWIN)
        err = []
        t = threading.Thread(target=lambda: err.append(p.stderr.read()), daemon=True)
        t.start()
        while p.poll() is None:
            if cancel is not None and cancel.is_set():
                p.kill()
                raise SpatialError('Cancelled.')
            try:
                p.wait(0.3)
            except subprocess.TimeoutExpired:
                pass
        t.join(2)
        if p.returncode:
            raise SpatialError('Could not encode the spatial audio: %s' % ((err[0] if err else b'').decode('utf-8', 'replace').strip()[-300:] or 'unknown error'))
        with open(tmp, 'rb') as f:
            payload = f.read()
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    data = pack(payload, CODEC_OPUS if codec == 'opus' else CODEC_LOSSLESS, names, rate, info['seconds'],
                {'layout': layout, 'title': title, 'kbps': kbps, 'quality': quality if codec == 'opus' else 'lossless', 'source': os.path.basename(src)})
    with open(out, 'wb') as f:
        f.write(data)
    return {'bytes': len(data), 'seconds': info['seconds'], 'channels': len(names), 'layout': layout, 'codec': codec}


def estimate_bytes(seconds, channels, codec, quality='medium'):
    """A rough size of the spatial file, for the "does it fit" line."""
    if codec != 'opus':
        return int(seconds * channels * 48000 * 2 * 0.55)           # about 55 % of 16-bit PCM
    return int(seconds * OPUS_KBPS.get(quality, 512) * 1000 / 8 * channels / 12)


# ---------------------------------------------------------------------------------------------------------------------------------------
# Binaural rendering: every channel is placed at its speaker position round the listener's head and filtered for the two ears (a spherical-head
# model: the delay between the ears, the head's shadow for the far ear, a little shelf for sounds from behind and a lift for sounds from above).
# It is an approximation, not a measured head response, and it is made for headphones.
# ---------------------------------------------------------------------------------------------------------------------------------------
POSITIONS = {'FL': (30, 0), 'FR': (-30, 0), 'FC': (0, 0), 'FLC': (15, 0), 'FRC': (-15, 0), 'SL': (90, 0), 'SR': (-90, 0), 'BC': (180, 0),
             'TC': (0, 90), 'TFL': (45, 45), 'TFR': (-45, 45), 'TFC': (0, 45), 'TBL': (135, 45), 'TBR': (-135, 45), 'TBC': (180, 45),
             'TSL': (90, 45), 'TSR': (-90, 45), 'WL': (60, 0), 'WR': (-60, 0)}
HEAD_RADIUS, SOUND_SPEED = 0.0875, 343.0


def _ear_filters(names, rate, nfft):
    """For each channel the two complex responses (left ear, right ear) on the rfft grid of `nfft` points, and a gain."""
    f = np.fft.rfftfreq(nfft, 1.0 / rate)
    w = 2 * np.pi * f
    w0 = SOUND_SPEED / HEAD_RADIUS
    out = []
    has_side = 'SL' in names
    for n in names:
        if n == 'LFE':
            lp = 1.0 / np.sqrt(1.0 + (f / 120.0) ** 4)                # a low-pass at 120 Hz, the same in both ears
            h = lp.astype(np.complex128) * 0.7
            out.append((h, h))
            continue
        az, el = POSITIONS.get(n, (0, 0))
        if n in ('BL', 'BR'):
            az = (150 if has_side else 110) * (1 if n == 'BL' else -1)
        a, e = math.radians(az), math.radians(el)
        x, y, z = math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)          # x forward, y left, z up
        resp = []
        for side in (1.0, -1.0):                                                            # the left ear sits at +y, the right at -y
            toward = side * y                                                               # > 0: the sound is on this ear's side of the head
            axis = (math.cos(math.radians(100)), side * math.sin(math.radians(100)), 0.0)  # the ear's own axis, a little behind the middle
            theta = math.acos(max(-1.0, min(1.0, x * axis[0] + y * axis[1])))             # the angle between the sound's direction and that axis
            delay = 0.0
            if toward < 0:                                                                  # the far ear hears it later (Woodworth's spherical head)
                lat = math.asin(min(1.0, -toward))
                delay = HEAD_RADIUS / SOUND_SPEED * (lat + math.sin(lat))
            alpha = 1.05 + 0.95 * math.cos(theta / math.radians(150) * math.pi)          # Brown & Duda's head shadow: 2 on the near side, 0.1 far behind the head
            shadow = (1.0 + 1j * alpha * w / (2 * w0)) / (1.0 + 1j * w / (2 * w0))
            g = shadow * np.exp(-1j * w * delay)
            if abs(az) > 90:                                                                # behind: the ear flap takes off some top
                g = g * (1.0 / (1.0 + (f / 9000.0) ** 2)) ** (0.25 * (abs(az) - 90) / 90.0)
            if el > 0:                                                                       # above: a lift around 7 kHz
                g = g * (1.0 + 0.5 * math.sin(e) * np.exp(-((np.log2(np.maximum(f, 1.0) / 7000.0)) ** 2) / 0.5))
            resp.append(g)
        out.append((resp[0], resp[1]))
    return out


def render_binaural(src_hms, out_wav, progress=None, cancel=None, gain=0.55):
    """Decodes the spatial file and writes a stereo 16-bit WAV for headphones. Returns {'seconds'}. Streams in blocks, so long files are fine."""
    info, payload = unpack(src_hms)
    names, n, rate = info['names'], info['channels'], info['rate']
    ext = '.opus' if info['codec'] == 'opus' else '.wv'
    tmp_in = out_wav + '.in' + ext
    with open(tmp_in, 'wb') as f:
        f.write(payload)
    nfft = 1 << 16
    block = nfft - 4096
    filt = _ear_filters(names, rate, nfft)
    tail_l = np.zeros(nfft, dtype=np.float64)
    tail_r = np.zeros(nfft, dtype=np.float64)
    total = 0
    p = subprocess.Popen([FFMPEG, '-hide_banner', '-loglevel', 'error', '-i', tmp_in, '-vn', '-f', 'f32le', '-acodec', 'pcm_f32le', '-ac', str(n), 'pipe:1'],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NOWIN)
    try:
        with open(out_wav, 'wb') as w:
            w.write(b'\0' * 44)
            want = block * n * 4
            while True:
                if cancel is not None and cancel.is_set():
                    raise SpatialError('Cancelled.')
                raw = p.stdout.read(want)
                while len(raw) < want:
                    more = p.stdout.read(want - len(raw))
                    if not more:
                        break
                    raw += more
                if not raw:
                    break
                frames = len(raw) // (n * 4)
                x = np.frombuffer(raw[:frames * n * 4], dtype='<f4').reshape(frames, n).astype(np.float64)
                yl = np.zeros(nfft // 2 + 1, dtype=np.complex128)
                yr = np.zeros(nfft // 2 + 1, dtype=np.complex128)
                for c in range(n):
                    X = np.fft.rfft(x[:, c], nfft)
                    yl += X * filt[c][0]
                    yr += X * filt[c][1]
                bl, br = np.fft.irfft(yl, nfft) + tail_l, np.fft.irfft(yr, nfft) + tail_r
                tail_l = np.concatenate([bl[frames:], np.zeros(frames)])[:nfft]
                tail_r = np.concatenate([br[frames:], np.zeros(frames)])[:nfft]
                st = np.stack([bl[:frames], br[:frames]], axis=1) * gain
                st = np.tanh(st * 0.9) / 0.9 if np.abs(st).max() > 0.8 else st                # a soft limiter only when it would otherwise clip
                w.write((np.clip(st, -1, 1) * 32767).astype('<i2').tobytes())
                total += frames
                if progress:
                    progress(total / float(rate))
                if frames < block:
                    break
            tail = np.stack([tail_l[:2048], tail_r[:2048]], axis=1) * gain
            w.write((np.clip(tail, -1, 1) * 32767).astype('<i2').tobytes())
            total += 2048
            data_len = total * 4
            w.seek(0)
            w.write(b'RIFF' + struct.pack('<I', 36 + data_len) + b'WAVEfmt ' + struct.pack('<IHHIIHH', 16, 1, 2, rate, rate * 4, 4, 16) + b'data' + struct.pack('<I', data_len))
    finally:
        try:
            p.kill()
        except OSError:
            pass
        try:
            os.remove(tmp_in)
        except OSError:
            pass
    return {'seconds': total / float(rate), 'rate': rate}
