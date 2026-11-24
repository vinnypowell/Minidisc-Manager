"""LibriVox audiobooks: free, public-domain recordings read by volunteers.

LibriVox's own web service was not reachable when this was written, so the books are found through the Internet Archive, which hosts every
LibriVox recording (collection "librivoxaudio") and lists each book's chapter files openly. Chapters are the Archive's ordinary 64 kbps MP3
files (the same audio LibriVox offers), downloaded one by one with podcasts.download() and added to the disc like any other file.

LibriVoxMixin is mixed into himd_app.Api. Its results have the same shape as the podcast ones, so the page reuses the same dialog.
"""
import json
import re
import urllib.parse

import podcasts

ARCHIVE = 'https://archive.org'


def _first(v):
    return (v[0] if isinstance(v, list) and v else v) or ''


def search(query, limit=30):
    """Books matching the words in the title or author, most downloaded first: [{name, author, feed (the Archive id), info}]."""
    words = re.sub(r'[^\w\s\'-]', ' ', query, flags=re.U).strip()
    if not words:
        return []
    return _query('collection:librivoxaudio AND (title:(%s) OR creator:(%s) OR subject:(%s))' % (words, words, words), limit)


def _query(q, limit):
    url = ARCHIVE + '/advancedsearch.php?' + urllib.parse.urlencode(
        [('q', q), ('fl[]', 'identifier'), ('fl[]', 'title'), ('fl[]', 'creator'), ('fl[]', 'runtime'), ('fl[]', 'language'),
         ('sort[]', 'downloads desc'), ('rows', limit), ('output', 'json')])
    docs = json.loads(podcasts._get(url).decode('utf-8', 'replace')).get('response', {}).get('docs', [])
    out = []
    for d in docs:
        info = ' · '.join(x for x in (str(_first(d.get('runtime'))), str(_first(d.get('language')))) if x)
        out.append({'name': str(_first(d.get('title'))) or d['identifier'], 'author': str(_first(d.get('creator'))), 'feed': d['identifier'], 'info': info})
    return out


SUBJECTS = [('fiction', 'Fiction'), ('mystery', 'Mystery and detective'), ('science fiction', 'Science fiction'), ('adventure', 'Adventure'), ('romance', 'Romance'),
            ('horror', 'Horror and ghost stories'), ('short stories', 'Short stories'), ('children', 'Children'), ('humor', 'Humour'), ('poetry', 'Poetry'),
            ('philosophy', 'Philosophy'), ('history', 'History'), ('biography', 'Biography'), ('religion', 'Religion')]


def browse(subject='', limit=40):
    """The most downloaded books overall or in one subject, same shape as search()."""
    if subject and subject not in dict(SUBJECTS):
        raise ValueError('Unknown subject.')
    q = 'collection:librivoxaudio' + (' AND subject:(%s)' % subject if subject else '')
    return _query(q, limit)


def _length(v):
    """The Archive gives a length as seconds ("1133.07") or as "18:52" / "1:02:03"."""
    if v is None:
        return 0
    s = str(v)
    return podcasts._seconds(s) if ':' in s else int(float(s)) if re.match(r'^[\d.]+$', s) else 0


def chapters(ident):
    """{show, author, episodes} for one book, in reading order (same shape as podcasts.episodes)."""
    if not re.match(r'^[\w.\-]+$', ident or ''):
        raise ValueError('Not a valid book.')
    meta = json.loads(podcasts._get(ARCHIVE + '/metadata/' + ident, timeout=40).decode('utf-8', 'replace'))
    md, files = meta.get('metadata', {}), meta.get('files', [])
    mp3 = [f for f in files if 'MP3' in (f.get('format') or '') and f.get('name', '').lower().endswith('.mp3')]
    small = [f for f in mp3 if f['format'].startswith('64Kbps')]
    use = small or [f for f in mp3 if f['format'] == 'VBR MP3'] or mp3
    order = {}                                           # the full-quality files carry the chapter numbers ("3/37")
    for f in mp3:
        m = re.match(r'^(\d+)/\d+$', str(f.get('track') or ''))
        if m:
            order[re.sub(r'_64kb\.mp3$|\.mp3$', '', f['name'])] = int(m.group(1))
    use.sort(key=lambda f: (order.get(re.sub(r'_64kb\.mp3$|\.mp3$', '', f['name']), 10 ** 6), f['name']))
    eps = []
    for i, f in enumerate(use, 1):
        try:
            size = int(f.get('size') or 0)
        except ValueError:
            size = 0
        eps.append({'title': (f.get('title') or '').strip() or ('Part %d' % i), 'url': '%s/download/%s/%s' % (ARCHIVE, ident, urllib.parse.quote(f['name'])),
                    'date': '', 'seconds': _length(f.get('length')), 'bytes': size, 'ext': '.mp3'})
    if not eps:
        raise ValueError('This book has no MP3 chapters.')
    show = str(_first(md.get('title')))
    return {'show': show, 'author': str(_first(md.get('creator'))) or show, 'episodes': eps}


class LibriVoxMixin:
    def librivox_search(self, query):
        query = (query or '').strip()
        if not query:
            return {'error': 'Type a book title or an author.'}
        try:
            return {'shows': search(query)}
        except Exception as exc:
            self.log('librivox_search failed: %r' % (exc,))
            return {'error': 'The audiobook directory could not be reached: %s' % exc}

    def librivox_lists(self):
        return {'genres': [{'id': k, 'name': v} for k, v in SUBJECTS]}

    def librivox_browse(self, subject=''):
        try:
            return {'shows': browse(subject or '')}
        except Exception as exc:
            self.log('librivox_browse failed: %r' % (exc,))
            return {'error': 'The audiobook directory could not be reached: %s' % exc}

    def librivox_book(self, ident):
        try:
            return chapters(ident)
        except Exception as exc:
            self.log('librivox_book failed: %r' % (exc,))
            return {'error': 'Could not read that book: %s' % exc}
