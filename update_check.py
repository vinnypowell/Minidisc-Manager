"""Tells the user when a newer MiniDisc Manager has been released (0.36.0), and (0.36.1, Windows installed copy only) can fetch and install it on request.

The program asks GitHub's public "latest release" page of the project, at most once a day (and when the user picks Help > Check for updates). Nothing about the
user or the computer is sent: it is a plain request with a generic client name. Nothing is downloaded or installed unless the user presses Update now. The answer is kept in update-check.json in USER_DIR (last check time, the newest
version seen, and the version the user chose to skip). It never raises: any problem (no internet, GitHub busy, odd answer) just means "no update known".
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

from mdm_paths import USER_DIR

API = 'https://api.github.com/repos/vinnypowell/Minidisc-Manager/releases/latest'
PAGE_PREFIX = 'https://github.com/vinnypowell/Minidisc-Manager/'
STATE_FILE = os.path.join(USER_DIR, 'update-check.json')
EVERY = 24 * 3600


def parse(v):
    """'v_0_35_2', 'v0.35.2' or '0.35.2' -> (0, 35, 2); None when there are not three numbers."""
    m = re.search(r'(\d+)\D+(\d+)\D+(\d+)', str(v or ''))
    return tuple(int(x) for x in m.groups()) if m else None


def _read():
    try:
        with open(STATE_FILE, encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(d):
    try:
        os.makedirs(USER_DIR, exist_ok=True)
        tmp = STATE_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, indent=1)
        os.replace(tmp, STATE_FILE)
    except OSError:
        pass


def _fetch():
    req = urllib.request.Request(API, headers={'User-Agent': 'MiniDiscManager-update-check', 'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(req, timeout=8) as r:
        data = json.loads(r.read(400000).decode('utf-8', 'replace'))
    ver = parse(data.get('tag_name'))
    url = str(data.get('html_url') or '')
    if not ver or not url.startswith(PAGE_PREFIX):
        return None
    return {'version': '%d.%d.%d' % ver, 'url': url}


def check(current, force=False):
    """-> {'available': bool, 'version', 'url', 'current'} or {'available': False, 'error': text} when a forced check could not be made.
    Not forced: asks GitHub only when the last check is a day old, otherwise answers from what was kept. A version the user skipped is not offered again
    (a forced check still reports it)."""
    st = _read()
    now = time.time()
    if force or now - float(st.get('checked') or 0) >= EVERY:
        try:
            got = _fetch()
        except Exception as exc:                                   # offline, rate limited, bad answer: stay quiet unless the user asked
            if force:
                return {'available': False, 'current': current, 'error': 'Could not reach the download page (%s).' % exc}
            got = None
        if got:
            st.update({'checked': now, 'latest': got['version'], 'url': got['url']})
            _write(st)
        elif not force:
            st['checked'] = now - EVERY + 3600                     # try again in an hour, not at every start
            _write(st)
    latest, cur = parse(st.get('latest')), parse(current)
    if not latest or not cur or latest <= cur:
        return {'available': False, 'current': current, 'version': st.get('latest', '')}
    if not force and st.get('skipped') == st.get('latest'):
        return {'available': False, 'current': current, 'version': st.get('latest', ''), 'skipped': True}
    return {'available': True, 'current': current, 'version': st['latest'], 'url': st.get('url', PAGE_PREFIX + 'releases/latest'), 'can_install': can_install()}


def skip(version):
    st = _read()
    st['skipped'] = str(version)
    _write(st)
    return {'ok': True}


# ---------------------------------------------------------------------------------------------------------------------------------------
# Update now (Windows, installed copy only): download the Setup of the newest release, check it against the SHA-256 GitHub lists for that file, then run it
# silently from a small script that starts the program again afterwards. Nothing happens until the user presses the button.
# ---------------------------------------------------------------------------------------------------------------------------------------
DOWNLOAD_PREFIX = PAGE_PREFIX + 'releases/download/'


def installed_exe():
    """The program's exe when this is the INSTALLED Windows copy (the Setup's own uninstaller sits next to it), else None (portable zip, source, Mac)."""
    if sys.platform != 'win32' or not getattr(sys, 'frozen', False):
        return None
    exe = sys.executable
    return exe if os.path.isfile(os.path.join(os.path.dirname(exe), 'unins000.exe')) else None


def can_install():
    return installed_exe() is not None


def find_setup(version):
    """-> {'url', 'name', 'size', 'sha256'} of the Setup file of release `version` on the project's page. Raises ValueError when there is none or it cannot be checked."""
    req = urllib.request.Request(API, headers={'User-Agent': 'MiniDiscManager-update-check', 'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read(2000000).decode('utf-8', 'replace'))
    if parse(data.get('tag_name')) != parse(version):
        raise ValueError('The newest release is no longer %s; check again.' % version)
    want = 'MiniDisc-Manager-Setup-%s.exe' % version
    for a in data.get('assets') or []:
        url = str(a.get('browser_download_url') or '')
        if a.get('name') == want and url.startswith(DOWNLOAD_PREFIX):
            m = re.fullmatch(r'sha256:([0-9a-fA-F]{64})', str(a.get('digest') or ''))
            if not m:
                raise ValueError('The download page gives no checksum for the Setup, so it cannot be verified.')
            return {'url': url, 'name': want, 'size': int(a.get('size') or 0), 'sha256': m.group(1).lower()}
    raise ValueError('The release has no Setup file for Windows.')


def download(info, progress=None, cancel=None):
    """Downloads the Setup into a fresh folder in Temp, checks size and SHA-256, returns its path (raises ValueError / OSError). The partial file is removed on any failure."""
    root = os.path.join(tempfile.gettempdir(), 'MiniDiscManager-update')
    shutil.rmtree(root, ignore_errors=True)                        # an earlier attempt's leftovers
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, info['name'])
    h = hashlib.sha256()
    done = 0
    try:
        req = urllib.request.Request(info['url'], headers={'User-Agent': 'MiniDiscManager-update-check'})
        with urllib.request.urlopen(req, timeout=30) as r, open(path, 'wb') as f:
            if not str(r.geturl()).startswith('https://'):
                raise ValueError('The download was redirected to an insecure address.')
            while True:
                if cancel is not None and cancel.is_set():
                    raise ValueError('Cancelled.')
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, info['size'])
        if info['size'] and done != info['size']:
            raise ValueError('The download is incomplete (%d of %d bytes).' % (done, info['size']))
        if h.hexdigest() != info['sha256']:
            raise ValueError('The downloaded file does not match its checksum, so it was not used.')
        return path
    except BaseException:
        shutil.rmtree(root, ignore_errors=True)
        raise


def run_setup(setup_path):
    """Starts the Setup silently and then the program again, from a small script that outlives this process. The caller must close the program right after."""
    exe = installed_exe()
    if not exe:
        raise ValueError('Automatic update works only for the installed copy.')
    cmd = os.path.join(os.path.dirname(setup_path), 'update.cmd')
    lines = ['@echo off',
             'ping -n 3 127.0.0.1 >nul',                              # let the program finish closing
             'start "" /wait "%s" /SILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS' % setup_path,
             'start "" "%s"' % exe]
    with open(cmd, 'w', encoding='mbcs', newline='') as f:
        f.write(('\r\n').join(lines) + '\r\n')
    flags = 0x00000008 | 0x00000200 | 0x08000000                    # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    subprocess.Popen(['cmd', '/c', cmd], creationflags=flags, close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
