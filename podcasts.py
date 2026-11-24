"""Podcasts: find a show, list its episodes, download the ones you pick, ready for "Add to disc".

Search uses the free public iTunes podcast directory (no account, no key; it only lists shows and their feed
addresses, no audio comes from it). Episodes come from the show's own RSS feed, which any show publishes openly; the audio files are
ordinary MP3 / M4A downloads from the publisher. Nothing here touches copy-protected material. A feed address can also be pasted directly.

PodcastMixin is mixed into himd_app.Api (the page calls these methods on it). Downloads go to a scratch folder that is deleted on exit.
"""
import atexit
import json
import os
import re
import shutil
import tempfile
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

UA = 'MiniDiscManager (personal use)'
POD_DIR = os.path.join(tempfile.gettempdir(), 'MiniDiscManager-podcasts')
MAX_EPISODES = 200
AUDIO_EXT = {'audio/mpeg': '.mp3', 'audio/mp3': '.mp3', 'audio/x-m4a': '.m4a', 'audio/mp4': '.m4a', 'audio/aac': '.aac', 'audio/ogg': '.ogg', 'audio/x-wav': '.wav', 'audio/wav': '.wav', 'audio/flac': '.flac'}
ITUNES = '{http://www.itunes.com/dtds/podcast-1.0.dtd}'


def _get(url, timeout=25, limit=None):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(limit) if limit else r.read()


def search(query, limit=25):
    """Shows matching the words: [{name, author, feed, art}]."""
    url = 'https://itunes.apple.com/search?' + urllib.parse.urlencode({'term': query, 'media': 'podcast', 'entity': 'podcast', 'limit': limit})
    data = json.loads(_get(url).decode('utf-8', 'replace'))
    out = []
    for r in data.get('results', []):
        if r.get('feedUrl'):
            out.append({'name': r.get('collectionName') or r.get('trackName') or '?', 'author': r.get('artistName') or '', 'feed': r['feedUrl'], 'art': r.get('artworkUrl100') or ''})
    return out


GENRES = [('1301', 'Arts'), ('1321', 'Business'), ('1303', 'Comedy'), ('1304', 'Education'), ('1483', 'Fiction and drama'), ('1512', 'Health and fitness'),
          ('1487', 'History'), ('1305', 'Kids and family'), ('1502', 'Leisure and hobbies'), ('1310', 'Music'), ('1489', 'News'), ('1314', 'Religion and spirituality'),
          ('1533', 'Science'), ('1324', 'Society and culture'), ('1545', 'Sports'), ('1318', 'Technology'), ('1309', 'TV and film'), ('1488', 'True crime')]
COUNTRIES = [('gb', 'United Kingdom'), ('us', 'United States'), ('ie', 'Ireland'), ('au', 'Australia'), ('ca', 'Canada'), ('nl', 'Netherlands'), ('de', 'Germany'), ('fr', 'France'), ('es', 'Spain')]


def charts(genre='', country='gb', limit=30):
    """The most popular shows now, overall or in one genre (the public iTunes top charts), as [{name, author, feed, art}]."""
    if genre and genre not in dict(GENRES) or country not in dict(COUNTRIES):
        raise ValueError('Unknown genre or country.')
    url = 'https://itunes.apple.com/%s/rss/toppodcasts/limit=%d%s/json' % (country, limit, '/genre=' + genre if genre else '')
    entries = json.loads(_get(url).decode('utf-8', 'replace')).get('feed', {}).get('entry', [])
    ids = [e['id']['attributes']['im:id'] for e in (entries if isinstance(entries, list) else [entries])]
    if not ids:
        return []
    look = json.loads(_get('https://itunes.apple.com/lookup?entity=podcast&id=' + ','.join(ids)).decode('utf-8', 'replace')).get('results', [])
    by = {str(r.get('collectionId')): r for r in look if r.get('feedUrl')}
    return [{'name': by[i].get('collectionName') or '?', 'author': by[i].get('artistName') or '', 'feed': by[i]['feedUrl'], 'art': by[i].get('artworkUrl100') or ''} for i in ids if i in by]


def search_episodes(query, limit=50):
    """Single episodes whose title matches the words (the iTunes episode search): [{name, author (the show), feed, episode, info}]."""
    url = 'https://itunes.apple.com/search?' + urllib.parse.urlencode({'term': query, 'media': 'podcast', 'entity': 'podcastEpisode', 'limit': limit})
    out = []
    for r in json.loads(_get(url).decode('utf-8', 'replace')).get('results', []):
        if r.get('feedUrl') and r.get('trackName'):
            ms = r.get('trackTimeMillis') or 0
            out.append({'name': 'Episode: ' + r['trackName'], 'author': r.get('collectionName') or '', 'feed': r['feedUrl'], 'episode': r['trackName'],
                        'info': ' · '.join(x for x in ((r.get('releaseDate') or '')[:10], '%d min' % round(ms / 60000) if ms else '') if x)})
    words = [w for w in re.findall(r'\w+', query.lower()) if len(w) >= 3]
    good = [x for x in out if all(w in x['episode'].lower() for w in words)]          # the directory also returns episodes that only mention the words in their notes: those with every word in the TITLE come first
    return good + [x for x in out if x not in good]


def genres_for(query):
    """Genres the typed words point at ("crime" -> True crime, "tech" -> Technology): [(id, name)], and whether the words are only genre words."""
    words = [w for w in re.findall(r"[a-z]+", query.lower()) if len(w) >= 3 and w not in ('and', 'the', 'for')]
    hits, used = [], set()
    for gid, name in GENRES:
        parts = [x for x in re.findall(r'[a-z]+', name.lower()) if x != 'and']
        for w in words:
            if any(w == x or (len(w) >= 4 and (x.startswith(w) or w.startswith(x))) for x in parts):
                hits.append((gid, name)); used.add(w); break
    return hits, bool(words) and used == set(words)


def search_with_genres(query, country='gb'):
    """The words searched as a show name or author, plus the popular shows of any genre the words name (a search for "crime" lists True crime)."""
    shows = search(query)
    try:
        episodes_found = search_episodes(query)
    except Exception:
        episodes_found = []
    hits, only_genre = genres_for(query)
    extra = []
    for gid, name in hits[:2]:
        try:
            extra += [dict(x, author=(x['author'] + ' · ' if x['author'] else '') + name) for x in charts(gid, country if country in dict(COUNTRIES) else 'gb', 20)]
        except Exception:
            pass
    first, second = (extra, shows) if only_genre else (shows, extra)
    seen, out = set(), []
    for x in first + second + episodes_found:
        key = (x['feed'], x.get('episode', ''))
        if key not in seen:
            seen.add(key)
            out.append(x)
    return out


def _seconds(text):
    """itunes:duration is seconds, mm:ss or hh:mm:ss."""
    try:
        parts = [float(p) for p in (text or '').strip().split(':')]
    except ValueError:
        return 0
    n = 0.0
    for p in parts:
        n = n * 60 + p
    return int(n)


def episodes(feed_url, limit=MAX_EPISODES):
    """The show's name and its newest episodes: {show, author, episodes: [{title, url, date, seconds, bytes, ext}]}."""
    root = ET.fromstring(_get(feed_url, timeout=30))
    ch = root.find('channel')
    if ch is None:
        raise ValueError('That address is not a podcast feed.')
    show = (ch.findtext('title') or '').strip()
    author = (ch.findtext(ITUNES + 'author') or '').strip()
    eps = []
    for it in ch.findall('item'):
        enc = it.find('enclosure')
        if enc is None or not enc.get('url'):
            continue
        typ = (enc.get('type') or '').lower()
        path = urllib.parse.urlparse(enc.get('url')).path
        ext = AUDIO_EXT.get(typ) or os.path.splitext(path)[1].lower()
        if ext not in ('.mp3', '.m4a', '.aac', '.ogg', '.wav', '.flac'):
            if typ.startswith('video'):
                continue
            ext = '.mp3'
        try:
            size = int(enc.get('length') or 0)
        except ValueError:
            size = 0
        eps.append({'title': (it.findtext('title') or '').strip() or 'Episode', 'url': enc.get('url'), 'date': (it.findtext('pubDate') or '')[:16],
                    'seconds': _seconds(it.findtext(ITUNES + 'duration')), 'bytes': size, 'ext': ext})
        if len(eps) >= limit:
            break
    return {'show': show, 'author': author or show, 'episodes': eps}


def _safe(name):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', name).strip(' .')
    return (name or 'episode')[:90]


def download(url, title, ext, show=''):
    """Fetch one episode into the scratch folder and return its path."""
    os.makedirs(POD_DIR, exist_ok=True)
    base = _safe((show + ' - ' if show else '') + title)
    path = os.path.join(POD_DIR, base + ext)
    n = 1
    while os.path.exists(path):
        n += 1
        path = os.path.join(POD_DIR, '%s (%d)%s' % (base, n, ext))
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    tmp = path + '.part'
    try:
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, 'wb') as f:
            shutil.copyfileobj(r, f, 1 << 18)
        if os.path.getsize(tmp) < 10000:
            raise ValueError('The download is empty or is not audio.')
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return path


def clear():
    shutil.rmtree(POD_DIR, ignore_errors=True)


atexit.register(clear)


def podcasts_genres():
    return [{'id': k, 'name': v} for k, v in GENRES]


class PodcastMixin:
    def podcast_search(self, query, country='gb'):
        query = (query or '').strip()
        if not query:
            return {'error': 'Type the name of a podcast.'}
        try:
            return {'shows': search_with_genres(query, country)}
        except Exception as exc:
            self.log('podcast_search failed: %r' % (exc,))
            return {'error': 'The podcast directory could not be reached: %s' % exc}

    def podcast_lists(self):
        return {'genres': podcasts_genres(), 'countries': [{'id': k, 'name': v} for k, v in COUNTRIES]}

    def podcast_top(self, genre='', country='gb'):
        """The most popular shows now, overall or in one genre."""
        try:
            return {'shows': charts(genre or '', country or 'gb')}
        except Exception as exc:
            self.log('podcast_top failed: %r' % (exc,))
            return {'error': 'The podcast charts could not be reached: %s' % exc}

    def podcast_feed(self, url):
        url = (url or '').strip()
        if not url.lower().startswith(('http://', 'https://')):
            return {'error': 'A feed address starts with http:// or https://.'}
        try:
            return episodes(url)
        except Exception as exc:
            self.log('podcast_feed failed: %r' % (exc,))
            return {'error': 'Could not read that feed: %s' % exc}

    def podcast_download(self, url, title, ext, show=''):
        try:
            return {'path': download(url, title, ext, show)}
        except Exception as exc:
            self.log('podcast_download failed: %r' % (exc,))
            return {'error': 'Could not download "%s": %s' % (title, exc)}

    def podcast_clear(self):
        clear()
        return {'ok': True}
