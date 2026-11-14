import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from axiom.ingest import validate_url, split_text, pdf_chunks, ingest, _artifact, CheckedRedirect, download
from axiom.retrieval import search


class IngestionTests(unittest.TestCase):
    def test_url_boundary(self):
        self.assertEqual(validate_url("https://ntrs.nasa.gov/api/citations/1"), "https://ntrs.nasa.gov/api/citations/1")
        for url in ("http://ntrs.nasa.gov/x", "https://ntrs.nasa.gov.evil.example/x",
                    "https://localhost/x", "file:///C:/x", "https://x@ntrs.nasa.gov/x",
                    "https://ntrs.nasa.gov:8080/x"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_url(url)

    def test_parts_are_bounded_and_deterministic(self):
        text = "Alpha oxygen flame. " * 200
        self.assertEqual(split_text(text), split_text(text))
        self.assertTrue(all(len(c) <= 1800 for c in split_text(text)))
        self.assertEqual(" ".join(split_text(text)), " ".join(text.split()))

    def test_non_pdf_and_empty_pdf_rejected(self):
        with self.assertRaises(ValueError):
            pdf_chunks(b"<html>Access denied</html>", {})
        from pypdf import PdfWriter
        out = io.BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.write(out)
        with self.assertRaisesRegex(ValueError, "no extractable text"):
            pdf_chunks(out.getvalue(), {})

    def test_redirect_cannot_escape_allowlist(self):
        with self.assertRaises(ValueError):
            CheckedRedirect().redirect_request(None, None, 302, "", {}, "https://example.com/document.pdf")

    def test_cache_corruption_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as td:
            raw = Path(td)
            url = "https://ntrs.nasa.gov/test.pdf"
            (raw / "sample.pdf").write_bytes(b"tampered")
            (raw / "sample.pdf.provenance.json").write_text(json.dumps({"url": url, "sha256": "not-the-hash"}))
            with self.assertRaisesRegex(ValueError, "provenance mismatch"):
                _artifact(raw, "sample", "pdf", url, False)

    def test_declared_oversize_download_rejected(self):
        from unittest.mock import MagicMock
        response = MagicMock()
        response.url = "https://ntrs.nasa.gov/test.pdf"
        response.headers = {"Content-Length": "200"}
        response.__enter__.return_value = response
        opener = MagicMock()
        opener.open.return_value = response
        with patch("axiom.ingest.build_opener", return_value=opener), self.assertRaisesRegex(ValueError, "size limit"):
            download(response.url, max_bytes=100)
        response.read.assert_not_called()

    def test_held_source_never_fetches(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as td:
            root = Path(td)
            (root / "data").mkdir()
            (root / "data/sources.json").write_text(json.dumps({"sources": [{
                "source_id": "held", "status": "active", "permission_status": "review_required"
            }]}), encoding="utf-8")
            with patch("axiom.ingest.download") as mock_download:
                result = ingest(root)
                mock_download.assert_not_called()
                self.assertEqual(result["chunk_count"], 0)
                self.assertEqual(result["sources"][0]["status"], "inventory_only")

    def test_download_failure_is_manifested(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as td:
            root = Path(td)
            (root / "data").mkdir()
            (root / "data/sources.json").write_text(json.dumps({"sources": [{
                "source_id": "missing", "status": "active", "permission_status": "allowed",
                "metadata_url": "https://ntrs.nasa.gov/api/citations/1", "ntrs_id": "1"
            }]}), encoding="utf-8")
            with patch("axiom.ingest.download", side_effect=OSError("network unavailable")):
                result = ingest(root)
            self.assertEqual(result["failed_sources"], 1)
            self.assertEqual(result["chunk_count"], 0)
            self.assertIn("network unavailable", result["sources"][0]["error"])

    def test_bm25_returns_match_without_mutating_corpus(self):
        chunks = [{"chunk_id": "b", "text": "oxygen flame", "evidence_tier": 2},
                  {"chunk_id": "a", "text": "oxygen flame", "evidence_tier": 1},
                  {"chunk_id": "c", "text": "water ocean", "evidence_tier": 1}]
        result = search("oxygen", chunks)
        self.assertEqual([r["chunk_id"] for r in result], ["a", "b"])
        self.assertNotIn("score", chunks[0])
        self.assertEqual(search("dinosaurs", chunks), [])


class RealCorpusChecks(unittest.TestCase):
    def test_bundled_hashes_and_physical_locators(self):
        root = Path(__file__).resolve().parents[1]
        path = root / "data/processed/chunks.jsonl"
        if not path.exists():
            self.skipTest("Run ingestion before integration test")
        chunks = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertGreaterEqual(len({c["source_id"] for c in chunks}), 3)
        self.assertEqual(len({c["chunk_id"] for c in chunks}), len(chunks))
        for c in chunks:
            self.assertEqual(c["sha256"], hashlib.sha256(c["text"].encode()).hexdigest())
            self.assertRegex(c["locator"], r"^PDF page \d+, text part \d+$")
            self.assertTrue(all(v is None for v in c["conditions"].values()))


if __name__ == "__main__":
    unittest.main()

