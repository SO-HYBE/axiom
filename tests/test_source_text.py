"""Synthetic HTML source boundaries; fixtures are not NASA science evidence."""
import unittest

from axiom.source_text import extract_html_sections, MAX_HTML_BYTES


class SourceTextTests(unittest.TestCase):
    def extract(self, html):
        return extract_html_sections(html.encode('utf-8'))

    def test_entry_content_excludes_page_header_and_article_metadata(self):
        html = '''<html><header><p>Navigation.</p></header><main><article>
          <h1>Page title</h1><p>Author biography outside body.</p>
          <div class="entry-content"><p>Named source prose.</p></div>
          <footer>Article footer.</footer></article><p>More page widgets.</p></main></html>'''
        self.assertEqual(self.extract(html), [{'section': '', 'text': 'Named source prose.',
                         'locator': 'Article body; block 1'}])

    def test_heading_path_preserves_parent_section_and_case(self):
        html = '<main><article><div class="entry-content"><h1>RTDFS</h1><h3>Science Objectives</h3><p>Proposed 0.5 mm.</p><h4>Scope</h4><p>Fuel A.</p><h3>Status</h3><p>Delivered.</p></div></article></main>'
        rows = self.extract(html)
        self.assertEqual([r['section'] for r in rows], ['RTDFS / Science Objectives', 'RTDFS / Science Objectives / Scope', 'RTDFS / Status'])
        self.assertIn('heading: RTDFS / Science Objectives', rows[0]['locator'])
        self.assertEqual(rows[0]['text'], 'Proposed 0.5 mm.')

    def test_inline_entities_numbers_units_and_paragraph_order_are_preserved(self):
        html = '<article><p>Cotton<strong>-</strong>fiberglass &amp; O<sub>2</sub>: 75%, 25%; 0–5 cm/s.</p><p>“Literal” <em>scope</em>.</p></article>'
        row, = self.extract(html)
        self.assertEqual(row['text'], 'Cotton-fiberglass & O2: 75%, 25%; 0–5 cm/s.\n\n“Literal” scope.')

    def test_navigation_hidden_text_tables_and_figures_never_become_prose(self):
        html = '''<main><p>Allowed prose.</p><nav><p>Navigation.</p></nav>
        <aside><p>Related sidebar.</p></aside><table><tr><td>False row value.</td></tr></table>
        <figure><img alt="Image number"><figcaption>Image credit.</figcaption></figure>
        <script>arbitrary_code()</script><style>.hidden{}</style><p hidden>Hidden.</p>
        <p aria-hidden="true">Hidden ARIA.</p><p style="display: none">Hidden style.</p>
        <div class="cookie-notice"><p>Cookies.</p></div><p class="screen-reader-text">Reader link.</p>
        <video-js><p class="vjs-no-js">Enable JavaScript.</p></video-js></main>'''
        row, = self.extract(html)
        self.assertEqual(row['text'], 'Allowed prose.')

    def test_related_link_heading_excludes_its_subsections_only(self):
        html = '<article><h2>Science</h2><p>Science prose.</p><h2>Related Links</h2><p>Unrelated link.</p><h3>More links</h3><p>Another link.</p><h2>Research status</h2><p>Status prose.</p></article>'
        rows = self.extract(html)
        self.assertEqual([r['text'] for r in rows], ['Science prose.', 'Status prose.'])
        self.assertEqual(rows[1]['section'], 'Research status')

    def test_main_fallback_and_direct_text_are_supported(self):
        self.assertEqual(self.extract('<main><h2>Objectives</h2>Direct <b>body</b> prose.<div>Second block.</div></main>')[0]['text'], 'Direct body prose.\n\nSecond block.')

    def test_multiple_articles_archive_and_ambiguous_bodies_are_rejected(self):
        for html in ('<main><article><p>One.</p></article><article><p>Two.</p></article></main>',
                     '<main id="blog-archive-content-feed"><p>Archive.</p></main>',
                     '<article><div class="entry-content"><p>One.</p></div><div class="entry-content"><p>Two.</p></div></article>',
                     '<main><p>One.</p></main><main><p>Two.</p></main>'):
            with self.subTest(html=html), self.assertRaises(ValueError):
                self.extract(html)

    def test_missing_unclosed_or_empty_body_is_rejected(self):
        for html in ('<div><p>Unscoped text.</p></div>', '<article><p>Unclosed body.</p>',
                     '<article><figure>Image only.</figure></article>'):
            with self.subTest(html=html), self.assertRaises(ValueError):
                self.extract(html)

    def test_input_encoding_size_and_depth_are_bounded(self):
        for blob in ('<main>text</main>', b'', b'\xff', b'x' * (MAX_HTML_BYTES + 1),
                     ('<main>' + '<div>' * 170 + 'text' + '</div>' * 170 + '</main>').encode()):
            with self.subTest(kind=type(blob).__name__), self.assertRaises(ValueError):
                extract_html_sections(blob)

    def test_hidden_article_is_not_selected_as_a_fallback(self):
        with self.assertRaises(ValueError):
            self.extract('<article hidden><p>Hidden article.</p></article>')

    def test_extraction_is_deterministic_without_mutating_bytes(self):
        blob = b'<main><p>First<br>second.</p><p>Third.</p></main>'
        first = extract_html_sections(blob)
        first[0]['text'] = 'Changed returned result.'
        self.assertEqual(extract_html_sections(blob)[0]['text'], 'First second.\n\nThird.')


if __name__ == '__main__':
    unittest.main()
