"""Burning CDs, DVDs and Blu-ray discs on macOS, with macOS's own `drutil`. It answers the same small command set as the Windows helper
(helper/cdburn_plain.ps1), so cd_audio.py needs only to call it instead of PowerShell:

    -List                                  DRIVE <letter>|<name>      one line per writer
                                           DISC <letter>|<type>|<blank>|<minutes>|<rewritable>|<free bytes>|<mounted>   one line per writer with a disc
    -Drive <letter> -Check                 DONE, or ERROR <text>: there is a disc that can be written
    -Drive <letter> -Erase                 DONE: quick-erases the rewritable disc (macOS ejects it afterwards)
    -Drive <letter> -Burn -ListFile <json> TRACK <n> of <m> (progress), DONE: an audio CD from the WAV files listed, in order
    -Drive <letter> -Data -Folder <f> -Label <name>   DONE: the folder's files on a data disc (or copied onto a mounted DVD-RAM)

The "letter" of a writer is "Drive 1", "Drive 2" ... (its number in `drutil list`). Nothing here needs administrator rights."""
import json
import os
import re
import shutil
import subprocess
import threading

DRUTIL = '/usr/bin/drutil'
_BUS = re.compile(r'\s+(USB|FireWire|ATAPI|SATA|SCSI|PCI|Thunderbolt|Firewire)\b.*$', re.I)


def _run(args, timeout=60):
    try:
        r = subprocess.run([DRUTIL] + args, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or '') + (r.stderr or '')
    except (OSError, subprocess.SubprocessError):
        return ''


def _drives():
    """[(number, name)] from `drutil list`."""
    out = []
    for line in _run(['list'], 20).splitlines():
        m = re.match(r'^\s*(\d+)\s+(.+?)\s*$', line)
        if not m:
            continue
        name = _BUS.sub('', m.group(2)).strip()
        name = re.sub(r'\s+\d+\.\d+$', '', name)                      # the firmware revision at the end
        out.append((int(m.group(1)), re.sub(r'\s+', ' ', name)))
    return out


def _msf_blocks(text):
    """'blocks:  359846' from a status line -> 359846, or None."""
    m = re.search(r'blocks:\s*(\d+)', text)
    return int(m.group(1)) if m else None


def _disc(number):
    """What is in drive `number`: {type, blank, minutes, rewritable, free, mounted} or None when there is no disc."""
    out = _run(['-drive', str(number), 'status'], 30)
    m = re.search(r'Type:\s*(.+?)\s{2,}Name:', out) or re.search(r'Type:\s*([^\n]+?)\s*(?:\n|$)', out)
    kind = m.group(1).strip() if m else ''
    if not kind or 'no media' in kind.lower() or 'no media' in out.lower():
        return None
    free_line = next((l for l in out.splitlines() if 'Space Free' in l), '')
    used_line = next((l for l in out.splitlines() if 'Space Used' in l), '')
    free_blocks = _msf_blocks(free_line) or 0
    used_blocks = _msf_blocks(used_line) or 0
    writ = next((l for l in out.splitlines() if 'Writability' in l), '').lower()
    blank = ('blank' in writ) or (used_blocks == 0 and free_blocks > 0)
    kind = kind.replace('CD-ROM', 'CD-ROM')
    rewritable = bool(re.search(r'RW|RAM|BD-RE', kind))
    mounted = False
    if kind == 'DVD-RAM':
        node = re.search(r'/dev/(disk\d+)', out)
        if node:
            mounted = bool(re.search(r'^/dev/%s\S* on ' % node.group(1), subprocess.run(['/sbin/mount'], capture_output=True, text=True).stdout, re.M))
    return {'type': kind, 'blank': blank, 'minutes': free_blocks / 4500.0, 'rewritable': rewritable, 'free': free_blocks * 2048, 'mounted': mounted}


def _number(letter):
    m = re.search(r'(\d+)', str(letter))
    return int(m.group(1)) if m else 1


def _volume_of(number):
    out = _run(['-drive', str(number), 'status'], 30)
    node = re.search(r'/dev/(disk\d+)', out)
    if not node:
        return None
    for line in subprocess.run(['/sbin/mount'], capture_output=True, text=True).stdout.splitlines():
        if line.startswith('/dev/' + node.group(1)) and ' on ' in line:
            return line.split(' on ', 1)[1].split(' (', 1)[0]
    return None


def run(args, timeout, on_line=None, ffmpeg=None):
    """Same contract as cd_audio.CdMixin._burn_ps: returns {'lines': [...]} or {'error': text, 'lines': [...]}."""
    lines = []

    def say(text):
        lines.append(text)
        if on_line:
            on_line(text)

    def get(flag):
        return args[args.index(flag) + 1] if flag in args and args.index(flag) + 1 < len(args) else None

    if not os.path.exists(DRUTIL):
        return {'error': 'macOS\'s disc tool (drutil) was not found.', 'lines': lines}
    try:
        if '-List' in args:
            for number, name in _drives():
                letter = 'Drive %d' % number
                say('DRIVE %s|%s' % (letter, name))
                d = _disc(number)
                if d:
                    say('DISC %s|%s|%s|%.2f|%s|%d|%s' % (letter, d['type'], d['blank'], d['minutes'], d['rewritable'], d['free'], d['mounted']))
            say('DONE')
            return {'lines': lines}
        letter = get('-Drive')
        number = _number(letter)
        d = _disc(number)
        if '-Check' in args:
            if not d:
                return {'error': 'There is no disc in the writer.', 'lines': lines}
            if not (d['blank'] or d['mounted']):
                return {'error': 'The disc in the writer is not blank.', 'lines': lines}
            say('DONE')
            return {'lines': lines}
        if '-Erase' in args:
            if not d:
                return {'error': 'There is no disc in the writer.', 'lines': lines}
            if not d['rewritable']:
                return {'error': 'This disc cannot be erased (it is not rewritable).', 'lines': lines}
            out = _run(['-drive', str(number), 'erase', 'quick'], timeout)
            if re.search(r'fail|error|unable|could not', out, re.I):
                return {'error': 'The disc could not be erased: ' + out.strip()[-200:], 'lines': lines}
            say('DONE')
            return {'lines': lines}
        if '-Burn' in args:
            files = json.load(open(get('-ListFile'), encoding='utf-8'))
            if not d or not d['blank']:
                return {'error': 'Put a blank CD-R or CD-RW in the writer.', 'lines': lines}
            stage = os.path.join(os.path.dirname(get('-ListFile')), 'audio-stage')
            shutil.rmtree(stage, ignore_errors=True)
            os.makedirs(stage)
            sizes = []
            for i, f in enumerate(files, 1):                          # drutil makes the tracks in alphabetical order: name them 01, 02 ...
                dst = os.path.join(stage, '%02d.wav' % i)
                try:
                    os.link(f, dst)
                except OSError:
                    shutil.copyfile(f, dst)
                sizes.append(max(1, os.path.getsize(f)))
            return _burn(['-drive', str(number), 'burn', '-audio', '-noappendable', stage], timeout, say, lines, sizes)
        if '-Data' in args:
            folder, label = get('-Folder'), (get('-Label') or 'MiniDisc')
            if not d:
                return {'error': 'There is no disc in the writer.', 'lines': lines}
            named = os.path.join(os.path.dirname(folder), label)
            if named != folder:
                shutil.rmtree(named, ignore_errors=True)
                os.rename(folder, named)                              # drutil names the disc after the folder
            if d['mounted']:                                          # a formatted DVD-RAM behaves like a disk: copy the files into a folder on it
                vol = _volume_of(number)
                if not vol:
                    return {'error': 'The DVD-RAM is not mounted.', 'lines': lines}
                shutil.copytree(named, os.path.join(vol, label), dirs_exist_ok=True)
                say('DONE')
                return {'lines': lines}
            if not d['blank']:
                return {'error': 'The disc in the writer is not blank.', 'lines': lines}
            return _burn(['-drive', str(number), 'burn', '-nohfsplus', '-iso9660', '-joliet', '-udf', '-noappendable', named], timeout, say, lines, [])
        return {'error': 'Unknown burn request.', 'lines': lines}
    except (OSError, ValueError) as exc:
        return {'error': 'The disc could not be written: %s' % exc, 'lines': lines}


def _burn(cmd, timeout, say, lines, sizes):
    """Runs drutil burn, turns its progress into 'TRACK n of m' lines (audio) and returns the result dict."""
    proc = subprocess.Popen([DRUTIL] + cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace', bufsize=1)
    timed_out = []
    timer = threading.Timer(timeout, lambda: (timed_out.append(1), proc.kill()))
    timer.start()
    out_lines, last_track = [], 0
    total = float(sum(sizes)) if sizes else 0.0
    try:
        buf = ''
        while True:
            ch = proc.stdout.read(1)
            if not ch:
                break
            if ch in '\r\n':
                text, buf = buf.strip(), ''
                if not text:
                    continue
                out_lines.append(text)
                m = re.search(r'(\d{1,3})\s*%', text)
                if m and sizes and 'verif' not in ' '.join(out_lines[-2:]).lower():
                    done = total * min(100, int(m.group(1))) / 100.0
                    acc, n = 0.0, len(sizes)
                    for i, s in enumerate(sizes):
                        acc += s
                        if done < acc:
                            n = i + 1
                            break
                    if n != last_track:
                        last_track = n
                        say('TRACK %d of %d' % (n, len(sizes)))
            else:
                buf += ch
        proc.wait()
    finally:
        timer.cancel()
    if timed_out:
        return {'error': 'The disc writer did not finish in time. Take the disc out and check it before trying again.', 'lines': lines}
    text = '\n'.join(out_lines)
    if proc.returncode or re.search(r'\b(fail|failed|error|unable|could not|not supported)\b', text, re.I):
        return {'error': 'The disc could not be written: ' + (out_lines[-1] if out_lines else 'the writer reported an error') + ' (' + text[-300:].replace('\n', ' | ') + ')', 'lines': lines}
    if sizes and not last_track:
        say('TRACK 1 of %d' % len(sizes))
    say('DONE')
    return {'lines': lines}
