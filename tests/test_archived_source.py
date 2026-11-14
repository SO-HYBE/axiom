import hashlib
import unittest
from unittest.mock import MagicMock, patch

from axiom import archived_source as archive
from axiom.source_text import extract_html_sections


def html():
    return (f'''<!doctype html><html><head><link rel="canonical" href="{archive.ORIGINAL_URL}"></head><body>
    <div id="wm-ipp-base">TOOLBAR MUST NOT ENTER EVIDENCE</div><main id="main">
    <article id="post-678" class="post hentry"><header><h1 class="entry-title">{archive.ARTICLE_TITLE}</h1></header>
    <div class="entry-content"><p>Synthetic exact-case 0.5 mW prose with CO2.</p>
    <figure><figcaption>THIRD PARTY CAPTION</figcaption></figure><script>UNTRUSTED SCRIPT</script>
    <div class="wp-caption"><p class="wp-caption-text">LEGACY MEDIA CAPTION</p></div>
    <p>Synthetic source states a bounded observation.</p></div>
    <footer><time class="entry-date published" datetime="{archive.PUBLISHED_AT}">November 25, 2013</time>
    <span class="author vcard">jnimon</span></footer></article>
    <section class="comments-area"><article id="div-comment-416" class="comment-body"><p>PUBLIC COMMENT MUST NOT ENTER EVIDENCE</p></article></section>
    </main></body></html>''').encode('utf-8')


def provenance(blob=None):
    blob = html() if blob is None else blob
    return dict(url=archive.ARCHIVE_URL, final_url=archive.ARCHIVE_URL, method='GET',
        request_body_sha256=None, retrieved_at='2026-11-06T18:00:00+00:00',
        bytes=len(blob), sha256=hashlib.sha256(blob).hexdigest(), content_type='text/html; charset=UTF-8',
        original_url=archive.ORIGINAL_URL, archive_url=archive.ARCHIVE_URL,
        archive_as_of=archive.ARCHIVE_AS_OF, publication_date=archive.PUBLICATION_DATE,
        published_at=archive.PUBLISHED_AT, archive_headers={
            'memento_datetime': 'Sat, 12 Jul 2025 20:27:04 GMT',
            'link': '<' + archive.ORIGINAL_URL + '>; rel="original"'})


class ArchivedSourceTests(unittest.TestCase):
    def test_exact_post_body_preserves_case_units_and_excludes_comments_media_toolbar(self):
        rows = archive.extract_archived_blog(html())
        self.assertEqual([row['text'] for row in rows], [
            'Synthetic exact-case 0.5 mW prose with CO2.', 'Synthetic source states a bounded observation.'])
        self.assertTrue(all(row['section'] == 'Article, 2013-11-25' for row in rows))
        self.assertIn('paragraph 1', rows[0]['locator'])
        self.assertIn('2025-07-12', rows[0]['locator'])
        # Generic extraction remains strict about article listings; the archive
        # adapter performs its own exact identity/body selection.
        with self.assertRaises(ValueError):
            extract_html_sections(html())

    def test_wrong_canonical_title_publication_post_or_ambiguous_body_fail(self):
        for before, after in [
                (archive.ORIGINAL_URL, 'https://example.invalid/unrelated'),
                (archive.ARTICLE_TITLE, 'An unrelated source'),
                (archive.PUBLISHED_AT, '2014-11-25T16:33:20+00:00'),
                ('id="post-678"', 'id="post-679"'),
                ('<div class="entry-content">', '<div class="entry-content"></div><div class="entry-content">'),
                ('<article id="post-678"', '<article id="post-678"></article><article id="post-678"')]:
            with self.subTest(before=before):
                modified = html().decode().replace(before, after).encode()
                with self.assertRaises(ValueError):
                    archive.extract_archived_blog(modified)

    def test_nested_legacy_captions_and_comments_cannot_enter_prose(self):
        blob = html().replace(b'0.5 mW prose', b'0.5 mW <span class="comment-body">COMMENT</span><span class="wp-caption-text">CAPTION</span>prose')
        rows = archive.extract_archived_blog(blob)
        self.assertEqual(rows[0]['text'], 'Synthetic exact-case 0.5 mW prose with CO2.')

    def test_missing_explicit_body_boundary_and_hidden_body_fail(self):
        for value in [html().replace(b'</div>', b'', 2),
                      html().replace(b'class="entry-content"', b'class="entry-content" hidden')]:
            with self.assertRaises(ValueError):
                archive.extract_archived_blog(value)

    def test_invalid_utf8_and_input_size_fail(self):
        for value in (b'\xff', b'', b'x' * (archive.MAX_BYTES + 1)):
            with self.assertRaises(ValueError):
                archive.extract_archived_blog(value)

    def test_pinned_capture_original_identity_and_memento_fields_are_required(self):
        archive.verify_archived_provenance(provenance())
        for changes in [dict(final_url='https://www.nasa.gov/blogs/'),
                        dict(original_url='https://example.invalid/'), dict(archive_as_of='2025-01-01'),
                        dict(archive_url=archive.ARCHIVE_URL + '?other'), dict(publication_date='2014-01-01'),
                        dict(method='POST'), dict(content_type='application/json')]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                archive.verify_archived_provenance(dict(provenance(), **changes))
        for headers in [dict(memento_datetime='bad timestamp', link=provenance()['archive_headers']['link']),
                        dict(memento_datetime='Sat, 12 Jul 2025 20:27:05 GMT', link=provenance()['archive_headers']['link']),
                        dict(memento_datetime='Sat, 12 Jul 2025 20:27:04 GMT', link='<https://example.invalid/>; rel="original"'),
                        dict(memento_datetime='Sat, 12 Jul 2025 20:27:04 GMT', link='x' * 10_001)]:
            with self.subTest(headers_kind=list(headers)), self.assertRaises(ValueError):
                archive.verify_archived_provenance(dict(provenance(), archive_headers=headers))

    def test_arbitrary_urls_and_redirects_are_refused_before_fetch(self):
        with patch('axiom.archived_source.build_opener') as opener:
            for url in [archive.ORIGINAL_URL, 'https://web.archive.org/web/20260101/https://example.invalid/',
                        archive.ARCHIVE_URL + '?changed=1', 'file:///local']:
                with self.assertRaises(ValueError):
                    archive.fetch_archived_blog(url)
            opener.assert_not_called()
        with self.assertRaises(ValueError):
            archive.NoArchiveRedirect().redirect_request(None, None, 302, None, {}, archive.ARCHIVE_URL)

    def mocked_response(self, blob=None):
        blob = html() if blob is None else blob
        response = MagicMock()
        response.status = 200
        response.url = archive.ARCHIVE_URL
        response.headers = {'Content-Type': 'text/html; charset=UTF-8',
            'Content-Length': str(len(blob)), 'Memento-Datetime': 'Sat, 12 Jul 2025 20:27:04 GMT',
            'Link': provenance()['archive_headers']['link']}
        response.read.return_value = blob
        return response

    def test_download_records_provenance_only_after_identity_validation(self):
        response = self.mocked_response()
        with patch('axiom.archived_source.build_opener') as opener:
            opener.return_value.open.return_value.__enter__.return_value = response
            blob, meta = archive.fetch_archived_blog()
        self.assertEqual(blob, html())
        self.assertEqual(meta['sha256'], hashlib.sha256(blob).hexdigest())
        self.assertEqual(meta['original_url'], archive.ORIGINAL_URL)
        self.assertEqual(meta['archive_as_of'], archive.ARCHIVE_AS_OF)
        self.assertEqual(opener.call_args.args[0].__class__, archive.NoArchiveRedirect)

    def test_wrong_final_response_missing_headers_or_oversize_download_fails(self):
        for kind in ('final', 'memento', 'size', 'body'):
            response = self.mocked_response()
            if kind == 'final': response.url = 'https://www.nasa.gov/blogs/'
            if kind == 'memento': response.headers.pop('Memento-Datetime')
            if kind == 'size': response.headers['Content-Length'] = str(archive.MAX_BYTES + 1)
            if kind == 'body': response.read.return_value = b'x' * (archive.MAX_BYTES + 1)
            with self.subTest(kind=kind), patch('axiom.archived_source.build_opener') as opener:
                opener.return_value.open.return_value.__enter__.return_value = response
                with self.assertRaises(ValueError): archive.fetch_archived_blog()


if __name__ == '__main__':
    unittest.main()
