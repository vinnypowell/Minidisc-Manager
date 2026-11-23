"""Tells the user when a newer MiniDisc Manager has been released (0.35.2). Notice only: nothing is downloaded or installed by itself.

The program asks GitHub's public "latest release" page of the project, at most once a day (and when the user picks Help > Check for updates). Nothing about the
user or the computer is sent: it is a plain request with a generic client name. The answer is kept in update-check.json in USER_DIR (last check time, the newest
version seen, and the version the user chose to skip). It never raises: any problem (no internet, GitHub busy, odd answer) just means "no update known".
"""
import json
import os
import re
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
    return {'available': True, 'current': current, 'version': st['latest'], 'url': st.get('url', PAGE_PREFIX + 'releases/latest')}


def skip(version):
    st = _read()
    st['skipped'] = str(version)
    _write(st)
    return {'ok': True}
