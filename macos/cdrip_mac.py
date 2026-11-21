"""Audio CDs on macOS: the same calls as the Windows part of cdrip.py (drives / read_toc / cdtext / rip_track), built on what macOS offers
without special rights: `drutil` for the drive and the table of contents, and the volume macOS mounts for an audio CD (file system "cddafs"),
which holds one AIFF file per track with the CD's own 16-bit stereo samples. The "drive letter" is the disc's device name (for example disk4)."""
import os
import re
import struct
import subprocess
import sys
import time

from cdrip import CdError, _wav_header, SECTOR

_MSF = re.compile(r'Track\s+(\d+):\s+(\d+):(\d+)\.(\d+)\s+(.*)')


def _run(args, timeout=30):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ''


def drives():
    """The device names of the CD drives that have a disc in them (a drive without a disc is not listed)."""
    out = ''
    for attempt in range(3):
        out = _run(['/usr/bin/drutil', 'status'])
        if 'Name:' in out:
            break
        time.sleep(1.0)
    m = re.search(r'Name:\s*(/dev/(disk\d+))', out)
    return [m.group(2)] if m else []


def read_toc(letter):
    out = ''
    for attempt in range(4):                       # a drive that is still spinning up answers with nothing at first
        out = _run(['/usr/bin/drutil', 'toc'])
        if 'Lead-out' in out:
            break
        time.sleep(1.5)
    raw = []
    leadout = None
    for line in out.splitlines():
        if 'Lead-out' in line:
            m = re.search(r'(\d+):(\d+)\.(\d+)', line)
            if m:
                leadout = (int(m.group(1)) * 60 + int(m.group(2))) * 75 + int(m.group(3))
        m = _MSF.search(line)
        if m:
            num, mi, se, fr, rest = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), m.group(5)
            raw.append({'num': num, 'data': 'audio' not in rest.lower(), 'start': (mi * 60 + se) * 75 + fr})
    if leadout is None or not raw or all(t['data'] for t in raw):
        raise CdError('There is no audio CD in the drive (or it could not be read).')
    for t in reversed(raw):                        # an enhanced CD ends with a data track after the audio
        if t['data']:
            leadout = min(leadout, t['start'] - 11400)
    audio = [t for t in raw if not t['data']]
    for k, t in enumerate(audio):
        end = audio[k + 1]['start'] if k + 1 < len(audio) else leadout
        t['frames'] = end - t['start']
        t['seconds'] = t['frames'] / 75.0
        t['audio'] = True
    return {'first': audio[0]['num'], 'last': audio[-1]['num'], 'leadout': leadout, 'tracks': audio}


def _volume(letter):
    """The folder macOS has mounted the audio CD at (it is mounted here if it is not yet)."""
    node = '/dev/' + letter.replace('/dev/', '')
    said = ''
    for attempt in range(5):
        mounts = _run(['/sbin/mount'])
        for line in mounts.splitlines():
            if 'cddafs' in line and (line.startswith(node + ' on ') or line.startswith(node + 's')):
                return line.split(' on ', 1)[1].split(' (', 1)[0]
        said = (_run(['/usr/sbin/diskutil', 'mount', node], timeout=60) or '').strip()
        sys.stderr.write('audio CD: not mounted (attempt %d), diskutil said: %s\n' % (attempt + 1, said[:200]))
        time.sleep(1.5)
    raise CdError('macOS has not opened the audio CD (%s). Close the Music app if it opened, and try again.' % (said[:120] or 'no answer'))


def _track_file(vol, num):
    for name in sorted(os.listdir(vol)):
        m = re.match(r'(\d+)\s+(.*)\.aiff?$', name, re.I)
        if m and int(m.group(1)) == num:
            return os.path.join(vol, name), m.group(2)
    return None, None


def cdtext(letter):
    """Disc and track titles as macOS shows them (taken from CD-Text where the disc has it): {title, artist, tracks: {n: {title, artist}}}."""
    try:
        vol = _volume(letter)
    except CdError:
        return None
    tracks = {}
    for name in os.listdir(vol):
        m = re.match(r'(\d+)\s+(.*)\.aiff?$', name, re.I)
        if m:
            tracks[int(m.group(1))] = {'title': m.group(2), 'artist': ''}
    title = os.path.basename(vol)
    if not tracks:
        return None
    return {'title': title if not re.match(r'(?i)audio cd$', title) else '', 'artist': '', 'tracks': tracks}


def _aiff_pcm(path):
    """(offset, size, big_endian) of the sound data in an AIFF / AIFF-C file of 16-bit stereo audio."""
    with open(path, 'rb') as f:
        head = f.read(12)
        if head[:4] != b'FORM':
            raise CdError('The track file macOS made is not in the expected format.')
        little = False
        while True:
            h = f.read(8)
            if len(h) < 8:
                raise CdError('The track file macOS made has no sound data.')
            cid, size = h[:4], struct.unpack('>I', h[4:])[0]
            if cid == b'COMM':
                body = f.read(size + (size & 1))
                ch, _frames, bits = struct.unpack('>HIH', body[:8])
                if ch != 2 or bits != 16:
                    raise CdError('The track file macOS made is not 16-bit stereo.')
                if len(body) >= 22 and body[18:22] == b'sowt':
                    little = True
            elif cid == b'SSND':
                off, _blk = struct.unpack('>II', f.read(8))
                start = f.tell() + off
                return start, size - 8 - off, not little
            else:
                f.seek(size + (size & 1), 1)


def rip_track(letter, toc, num, out_path, progress=None, cancel=None):
    try:
        return _rip_track(letter, toc, num, out_path, progress, cancel)
    except OSError as exc:                         # the drive went away or stopped answering part-way (often a bus-powered drive running short of power)
        raise CdError('The CD drive stopped answering while the track was being read (' + str(exc) + '). Unplug the drive, plug it straight into the Mac '
                      '(not into a hub; use both plugs of a two-plug cable), put the disc back in, and try again.')


def _rip_track(letter, toc, num, out_path, progress=None, cancel=None):
    t = next((x for x in toc['tracks'] if x['num'] == num), None)
    if t is None:
        raise CdError('There is no audio track %d on this disc.' % num)
    path, _name = _track_file(_volume(letter), num)
    if not path:
        raise CdError('macOS has no file for track %d of this disc.' % num)
    off, size, big = _aiff_pcm(path)
    size -= size % 4
    stats = {'retries': 0, 'suspect': 0, 'bad': 0}
    chunk = 588 * 4 * 50
    src = open(path, 'rb')
    try:
        with open(out_path, 'wb') as dst:
            dst.write(_wav_header(size))
            src.seek(off)
            done = 0
            while done < size:
                if cancel and cancel():
                    return None
                try:
                    data = src.read(min(chunk, size - done))
                except OSError:
                    # The drive hiccuped (or dropped off the bus for a moment): wait, find the disc again, and carry on from the same place.
                    stats['retries'] += 1
                    if stats['retries'] > 6:
                        raise
                    try:
                        src.close()
                    except OSError:
                        pass
                    time.sleep(3)
                    path, _name = _track_file(_volume(letter), num)
                    if not path:
                        raise
                    src = open(path, 'rb')
                    src.seek(off + done)
                    continue
                if not data:
                    break
                if big:                                  # big-endian samples: swap each pair of bytes
                    b = bytearray(data)
                    b[0::2], b[1::2] = data[1::2], data[0::2]
                    data = bytes(b)
                dst.write(data)
                done += len(data)
                if progress:
                    progress(done // SECTOR, max(1, size // SECTOR))
    finally:
        try:
            src.close()
        except OSError:
            pass
    return {'seconds': size / 176400.0, 'bytes': size, **stats}
