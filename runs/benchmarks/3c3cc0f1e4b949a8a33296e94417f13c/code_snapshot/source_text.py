"""Bounded text extraction from a single HTML article, never scientific parsing.

Only text in an explicitly located article/main body is admitted. Page identity,
download provenance and reuse permission are the caller's separate obligations.
Images, captions, tables and other non-prose content are deliberately omitted.
"""
from dataclasses import dataclass, field
from html.parser import HTMLParser
import re


MAX_HTML_BYTES = 2_000_000
MAX_NODES = 100_000
MAX_DEPTH = 160
MAX_TEXT_CHARS = 300_000
VOID = frozenset({'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
                  'link', 'meta', 'param', 'source', 'track', 'wbr'})
EXCLUDED_TAGS = frozenset({'nav', 'header', 'footer', 'aside', 'script', 'style',
                           'noscript', 'form', 'figure', 'figcaption', 'table',
                           'svg', 'canvas', 'math', 'iframe', 'object', 'video',
                           'video-js', 'audio', 'picture', 'template'})
EXCLUDED_CLASSES = frozenset({'screen-reader-text', 'sr-only', 'vjs-no-js',
                              'wp-block-post-author', 'wp-block-post-author-name',
                              'wp-block-post-author-biography'})
BOILERPLATE_HEADINGS = frozenset({'related links', 'related articles', 'related news',
                                  'read more', 'explore more', 'keep exploring',
                                  'about the author', 'media contacts', 'share'})
BLOCKS = frozenset({'p', 'li', 'dt', 'dd', 'blockquote'})
TEXT_BOUNDARIES = BLOCKS | frozenset({'div', 'section', 'ul', 'ol', 'br'})


@dataclass
class _Node:
    tag: str
    attrs: dict
    children: list = field(default_factory=list)
    closed: bool = False


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node('document', {}, closed=True)
        self.stack = [self.root]
        self.nodes = 0

    def handle_starttag(self, tag, attrs):
        self.nodes += 1
        if self.nodes > MAX_NODES or len(self.stack) >= MAX_DEPTH:
            raise ValueError('HTML source structure exceeds extraction limits')
        node = _Node(tag, dict(attrs), closed=tag in VOID)
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                self.stack[index].closed = True
                del self.stack[index:]
                return

    def handle_data(self, text):
        if text:
            self.stack[-1].children.append(text)


def _excluded(node):
    attrs = node.attrs
    classes = set((attrs.get('class') or '').lower().split())
    style = re.sub(r'\s+', '', (attrs.get('style') or '').lower())
    return (node.tag in EXCLUDED_TAGS or 'hidden' in attrs
            or (attrs.get('aria-hidden') or '').lower() == 'true'
            or bool(classes & EXCLUDED_CLASSES)
            or (attrs.get('role') or '').lower() in ('navigation', 'contentinfo', 'complementary')
            or 'display:none' in style or 'visibility:hidden' in style
            or any('cookie' in value or 'consent-banner' in value or 'related-content' in value
                   for value in classes))


def _nodes(node):
    if _excluded(node):
        return
    yield node
    for child in node.children:
        if isinstance(child, _Node):
            yield from _nodes(child)


def _normalize(text):
    return re.sub(r'\s+', ' ', text.replace('\x00', '')).strip()


def _plain(node):
    if _excluded(node):
        return ''
    parts = []
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
        else:
            text = _plain(child)
            if child.tag in TEXT_BOUNDARIES:
                parts.extend((' ', text, ' '))
            else:
                parts.append(text)
    return _normalize(''.join(parts))


def _body(tree):
    nodes = list(_nodes(tree))
    mains = [node for node in nodes if node.tag == 'main' or node.attrs.get('role') == 'main']
    if len(mains) > 1:
        raise ValueError('HTML source has ambiguous main content')
    candidate = mains[0] if mains else tree
    articles = [node for node in _nodes(candidate) if node.tag == 'article']
    if len(articles) > 1:
        raise ValueError('HTML source is an article listing, not a single source body')
    if articles:
        candidate = articles[0]
    elif not mains:
        raise ValueError('HTML source has no explicitly located article or main body')
    identity = ' '.join(str(candidate.attrs.get(key) or '') for key in ('id', 'class')).lower()
    if any(token in identity for token in ('archive', 'search-results', 'content-feed')):
        raise ValueError('HTML source is a listing, not a single source body')
    entries = [node for node in _nodes(candidate) if 'entry-content' in (node.attrs.get('class') or '').split()]
    if len(entries) > 1:
        raise ValueError('HTML source has ambiguous article bodies')
    body = entries[0] if entries else candidate
    if not body.closed:
        raise ValueError('HTML source body has no explicit closing boundary')
    return body


def _events(node):
    if _excluded(node):
        return
    if re.fullmatch(r'h[1-6]', node.tag):
        text = _plain(node)
        if text:
            yield ('heading', int(node.tag[1]), text)
        return
    if node.tag in BLOCKS:
        text = _plain(node)
        if text:
            yield ('paragraph', None, text)
        return
    # Prose sometimes sits directly in a main/div rather than a p. Collect only
    # contiguous inline runs; block boundaries still prevent merged words.
    inline = []
    for child in node.children:
        if isinstance(child, str):
            inline.append(child)
        elif not _excluded(child) and (child.tag in BLOCKS or re.fullmatch(r'h[1-6]', child.tag)
                                       or child.tag in ('div', 'section', 'ul', 'ol', 'main', 'article')):
            text = _normalize(''.join(inline))
            if text:
                yield ('paragraph', None, text)
            inline = []
            yield from _events(child)
        elif not _excluded(child):
            inline.append(_plain(child))
    text = _normalize(''.join(inline))
    if text:
        yield ('paragraph', None, text)


def extract_html_sections(blob):
    """Return exact-case prose grouped by actual heading paths.

    ``section`` is an existing heading path or an empty string for unheaded
    prose. ``locator`` describes the extraction boundary, never a PDF page or
    an invented source heading. Paragraph whitespace and HTML entities are
    normalized; numerical values, units and punctuation are not interpreted.
    A listing, missing body, malformed UTF-8 or empty result fails closed.
    """
    if not isinstance(blob, (bytes, bytearray)) or not blob or len(blob) > MAX_HTML_BYTES:
        raise ValueError('Expected bounded nonempty HTML bytes')
    try:
        text = bytes(blob).decode('utf-8-sig')
    except UnicodeError as exc:
        raise ValueError('HTML source must be valid UTF-8') from exc
    parser = _Tree()
    parser.feed(text)
    parser.close()
    body = _body(parser.root)
    headings, paragraphs, rows = [], [], []
    skip_level = None
    extracted = 0

    def flush():
        if paragraphs:
            section = ' / '.join(title for _, title in headings)
            number = len(rows) + 1
            locator = 'Article body; ' + ('heading: ' + section + '; ' if section else '') + f'block {number}'
            rows.append({'section': section, 'text': '\n\n'.join(paragraphs), 'locator': locator})
            paragraphs.clear()

    for kind, level, value in _events(body):
        if kind == 'heading':
            flush()
            headings = [(old_level, title) for old_level, title in headings if old_level < level]
            headings.append((level, value))
            if skip_level is not None and level > skip_level:
                continue
            skip_level = level if value.casefold().strip(': ') in BOILERPLATE_HEADINGS else None
        elif skip_level is None:
            extracted += len(value)
            if extracted > MAX_TEXT_CHARS:
                raise ValueError('HTML body text exceeds extraction limit')
            paragraphs.append(value)
    flush()
    if not rows:
        raise ValueError('HTML source has no supported prose in its article/main body')
    return rows
