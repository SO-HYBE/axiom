"""Admission of one identified archived NASA article, never arbitrary archives.

The original NASA URL remains the source identity. Internet Archive supplies a
dated copy, not a current NASA canonical page or a publisher signature. The
global NASA downloader and generic HTML extractor are deliberately unchanged.
"""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import re
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .source_text import _Tree, _Node, _events, _plain, _excluded

ORIGINAL_URL = 'https://blogs.nasa.gov/ISS_Science_Blog/2013/11/25/cool-flames-on-the-international-space-station-an-anatomy-of-discovery/'
ARCHIVE_URL = 'https://web.archive.org/web/20250712202704id_/' + ORIGINAL_URL
ARCHIVE_AS_OF = '2025-07-12T20:27:04+00:00'
PUBLICATION_DATE = '2013-11-25'
PUBLISHED_AT = '2013-11-25T16:33:20+00:00'
ARTICLE_TITLE = 'Cool Flames on the International Space Station – An Anatomy of Discovery'
POST_ID = 'post-678'
MAX_BYTES = 2_000_000
MAX_HEADER_CHARS = 10_000


class NoArchiveRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Archived source redirects are not admitted')


def _all_nodes(node):
    """Walk metadata too; ordinary prose walking excludes header/footer nodes."""
    yield node
    for child in node.children:
        if isinstance(child, _Node):
            yield from _all_nodes(child)


def verify_archived_provenance(meta):
    """Require the fixed capture, original identity and Memento response fields."""
    if not isinstance(meta, dict) or any(meta.get(key) != expected for key, expected in (
            ('url', ARCHIVE_URL), ('final_url', ARCHIVE_URL), ('archive_url', ARCHIVE_URL),
            ('original_url', ORIGINAL_URL), ('archive_as_of', ARCHIVE_AS_OF),
            ('publication_date', PUBLICATION_DATE), ('published_at', PUBLISHED_AT))):
        raise ValueError('Archived source identity or capture mismatch')
    if meta.get('method') != 'GET' or meta.get('request_body_sha256') is not None:
        raise ValueError('Archived source must use its fixed public GET')
    content_type = meta.get('content_type')
    if not isinstance(content_type, str) or content_type.split(';', 1)[0].strip().lower() != 'text/html':
        raise ValueError('Archived source must be HTML')
    headers = meta.get('archive_headers')
    if not isinstance(headers, dict) or set(headers) != {'memento_datetime', 'link'}:
        raise ValueError('Archived source Memento provenance is incomplete')
    if any(not isinstance(value, str) or not value or len(value) > MAX_HEADER_CHARS for value in headers.values()):
        raise ValueError('Archived source Memento header exceeds bounds or is missing')
    try:
        captured = parsedate_to_datetime(headers['memento_datetime'])
        if captured.tzinfo is None or captured.astimezone(timezone.utc).isoformat() != ARCHIVE_AS_OF:
            raise ValueError('Wrong capture')
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError('Archived source Memento timestamp mismatch') from exc
    originals = [url for url, relations in re.findall(r'<([^>]+)>\s*;\s*rel="([^"]+)"', headers['link'])
                 if 'original' in relations.split()]
    if originals != [ORIGINAL_URL]:
        raise ValueError('Archived source original Link mismatch')


def _content_events(node):
    """Exclude comments and legacy caption/media wrappers before prose events."""
    classes = set((node.attrs.get('class') or '').lower().split())
    if _excluded(node) or classes & {'comment-body', 'comments-area', 'wp-caption', 'wp-caption-text'}:
        return
    # Boundaries are known to be a paragraph-only WordPress article. Reuse the
    # existing case/units-preserving extraction for each individual paragraph.
    if node.tag in ('p', 'li', 'dt', 'dd', 'blockquote'):
        def filtered(original):
            classes = set((original.attrs.get('class') or '').lower().split())
            if _excluded(original) or classes & {'comment-body', 'comments-area', 'wp-caption', 'wp-caption-text'}:
                return None
            clone = _Node(original.tag, dict(original.attrs), closed=original.closed)
            for child in original.children:
                admitted = child if isinstance(child, str) else filtered(child)
                if admitted is not None:
                    clone.children.append(admitted)
            return clone
        yield from _events(filtered(node))
        return
    for child in node.children:
        if isinstance(child, _Node):
            yield from _content_events(child)


def extract_archived_blog(blob):
    """Extract only the uniquely identified post body, excluding its comments.

    Exact title/canonical/publication metadata is checked separately from the
    archive's HTTP provenance. Locators identify original body paragraphs, not
    PDF pages. No wording, units, punctuation or scientific conditions are inferred.
    """
    if not isinstance(blob, (bytes, bytearray)) or not blob or len(blob) > MAX_BYTES:
        raise ValueError('Expected bounded archived HTML bytes')
    try:
        text = bytes(blob).decode('utf-8-sig')
    except UnicodeError as exc:
        raise ValueError('Archived source must be valid UTF-8') from exc
    tree = _Tree()
    tree.feed(text)
    tree.close()
    nodes = list(_all_nodes(tree.root))
    canonicals = [node.attrs.get('href') for node in nodes if node.tag == 'link'
                  and 'canonical' in (node.attrs.get('rel') or '').split()]
    if canonicals != [ORIGINAL_URL]:
        raise ValueError('Archived article canonical identity mismatch')
    posts = [node for node in nodes if node.tag == 'article' and node.attrs.get('id') == POST_ID]
    if len(posts) != 1 or not posts[0].closed or _excluded(posts[0]):
        raise ValueError('Archived article post identity or closing boundary mismatch')
    article_nodes = list(_all_nodes(posts[0]))
    titles = [_plain(node) for node in article_nodes if node.tag == 'h1'
              and 'entry-title' in (node.attrs.get('class') or '').split()]
    if titles != [ARTICLE_TITLE]:
        raise ValueError('Archived article title mismatch')
    dates = [node.attrs.get('datetime') for node in article_nodes if node.tag == 'time'
             and 'published' in (node.attrs.get('class') or '').split()]
    if dates != [PUBLISHED_AT]:
        raise ValueError('Archived article publication timestamp mismatch')
    entries = [node for node in article_nodes if 'entry-content' in (node.attrs.get('class') or '').split()]
    if len(entries) != 1 or not entries[0].closed or _excluded(entries[0]):
        raise ValueError('Archived article body is missing or ambiguous')
    rows = []
    for kind, _, value in _content_events(entries[0]):
        if kind != 'paragraph':
            continue
        number = len(rows) + 1
        rows.append(dict(section='Article, 2013-11-25', text=value,
            locator=f'Original NASA article; article#{POST_ID} > div.entry-content; paragraph {number}; archived as of {ARCHIVE_AS_OF}'))
    if not rows or sum(len(row['text']) for row in rows) > 300_000:
        raise ValueError('Archived article has no bounded prose')
    return rows


def fetch_archived_blog(url=ARCHIVE_URL):
    """Fetch only the pinned public replay URL, without following redirects."""
    if url != ARCHIVE_URL:
        raise ValueError('Only the fixed archived NASA capture may be fetched')
    request = Request(url, headers={'User-Agent': 'IGNIS-source-verification/0.1', 'Accept-Encoding': 'identity'})
    with build_opener(NoArchiveRedirect()).open(request, timeout=30) as response:
        if response.status != 200 or response.url != ARCHIVE_URL:
            raise ValueError('Archived source response or final URL mismatch')
        declared = response.headers.get('Content-Length')
        if declared and int(declared) > MAX_BYTES:
            raise ValueError('Archived source exceeds size limit')
        blob = response.read(MAX_BYTES + 1)
        if len(blob) > MAX_BYTES:
            raise ValueError('Archived source exceeds size limit')
        meta = dict(url=url, final_url=response.url, method='GET', request_body_sha256=None,
            retrieved_at=datetime.now(timezone.utc).isoformat(), bytes=len(blob),
            sha256=hashlib.sha256(blob).hexdigest(), content_type=response.headers.get('Content-Type', ''),
            original_url=ORIGINAL_URL, archive_url=ARCHIVE_URL, archive_as_of=ARCHIVE_AS_OF,
            publication_date=PUBLICATION_DATE, published_at=PUBLISHED_AT,
            archive_headers={'memento_datetime': response.headers.get('Memento-Datetime', ''),
                             'link': response.headers.get('Link', '')})
    verify_archived_provenance(meta)
    extract_archived_blog(blob)
    return blob, meta
