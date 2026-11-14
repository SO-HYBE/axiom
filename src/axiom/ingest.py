"""Bounded, content-addressed ingestion of explicitly inventoried NASA PDFs.

No text in documents is executed. Only selected sources with permission status
`allowed` are fetched; catalog-only and rights-review entries remain inventory.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

ALLOWED_HOSTS = frozenset({"ntrs.nasa.gov", "psi.nasa.gov", "science.nasa.gov", "www.nasa.gov"})
MAX_BYTES = 25 * 1024 * 1024
TIMEOUT_SECONDS = 30
CHUNK_CHARS = 1800
CONDITION_KEYS = ("gravity", "fuel", "oxygen_percent", "pressure_kpa", "flow_cm_s")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_url(url: str) -> str:
    p = urlparse(url)
    if (p.scheme != "https" or p.hostname not in ALLOWED_HOSTS
            or p.username or p.password or p.port not in (None, 443)):
        raise ValueError(f"Source URL is not an allowlisted HTTPS NASA URL: {url}")
    return url


class CheckedRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url: str, max_bytes: int = MAX_BYTES) -> tuple[bytes, dict]:
    validate_url(url)
    req = Request(url, headers={"User-Agent": "AXIOM-research-prototype/0.1", "Accept-Encoding": "identity"})
    with build_opener(CheckedRedirect()).open(req, timeout=TIMEOUT_SECONDS) as response:
        validate_url(response.url)
        declared = response.headers.get("Content-Length")
        if declared and int(declared) > max_bytes:
            raise ValueError("Download exceeds size limit")
        blob = response.read(max_bytes + 1)
        if len(blob) > max_bytes:
            raise ValueError("Download exceeds size limit")
        return blob, {"url": url, "final_url": response.url,
                      "retrieved_at": utc_now(), "sha256": sha256(blob),
                      "bytes": len(blob), "content_type": response.headers.get("Content-Type", "")}


def normalize(text: str) -> str:
    # Preserve words, numbers, symbols and sentence punctuation. Whitespace is
    # normalized for repeatable span matching; tables are NOT treated as rows.
    return re.sub(r"\s+", " ", text.replace("\x00", "")).strip()


def split_text(text: str, limit: int = CHUNK_CHARS) -> list[str]:
    text = normalize(text)
    parts = []
    while text:
        if len(text) <= limit:
            parts.append(text)
            break
        end = text.rfind(". ", limit // 2, limit)
        end = end + 1 if end >= 0 else text.rfind(" ", limit // 2, limit)
        if end < 0:
            end = limit
        parts.append(text[:end].strip())
        text = text[end:].strip()
    return parts


def pdf_chunks(blob: bytes, source: dict) -> tuple[list[dict], dict]:
    if not blob.startswith(b"%PDF-"):
        raise ValueError("Expected a PDF, received another format")
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(blob))
    if reader.is_encrypted:
        raise ValueError("Encrypted PDF cannot be ingested")
    chunks = []
    empty_pages = []
    for page_no, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        if not normalize(text):
            empty_pages.append(page_no)
        for part_no, text_part in enumerate(split_text(text), 1):
            digest = sha256(text_part.encode("utf-8"))
            chunks.append({
                "chunk_id": f"{source['source_id']}-p{page_no:03d}-c{part_no:02d}-{digest[:10]}",
                "source_id": source["source_id"], "title": source["title"],
                "url": source["url"], "locator": f"PDF page {page_no}, text part {part_no}",
                "text": text_part, "sha256": digest,
                "source_kind": source["source_kind"], "experiment": source["experiment"],
                "conditions": {key: None for key in CONDITION_KEYS},
                "evidence_tier": source["evidence_tier"],
            })
    if not chunks:
        raise ValueError("PDF has no extractable text; OCR review required")
    return chunks, {"physical_pages": len(reader.pages), "empty_text_pages": empty_pages,
                    "chunks": len(chunks), "extraction": "pypdf text only; tables/figures not validated"}


def _safe_id(source_id: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", source_id):
        raise ValueError("Unsafe source_id")
    return source_id


def _artifact(raw: Path, source_id: str, kind: str, url: str, refresh: bool) -> tuple[bytes, dict]:
    validate_url(url)
    suffix = "pdf" if kind == "pdf" else "json"
    path = raw / f"{_safe_id(source_id)}.{suffix}"
    provenance = raw / f"{source_id}.{suffix}.provenance.json"
    if path.exists() and provenance.exists() and not refresh:
        blob = path.read_bytes()
        meta = json.loads(provenance.read_text(encoding="utf-8"))
        if meta["sha256"] != sha256(blob) or meta["url"] != url:
            raise ValueError(f"Cached provenance mismatch for {source_id}; investigate before refresh")
        if len(blob) > MAX_BYTES:
            raise ValueError("Cached file exceeds size limit")
        return blob, dict(meta, cache_hit=True)
    blob, meta = download(url)
    # Validate before saving a misleading .pdf or .json file.
    if kind == "pdf" and not blob.startswith(b"%PDF-"):
        raise ValueError("Download was not a PDF")
    if kind != "pdf":
        json.loads(blob)
    path.write_bytes(blob)
    provenance.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return blob, dict(meta, cache_hit=False)


def ingest(root: Path, *, refresh: bool = False) -> dict:
    """Fetch missing approved documents, re-extract cached bytes, and audit outputs.

    The default never replaces existing valid source bytes. Use refresh=True only
    for an intentional corpus update; the manifest identifies the new version.
    A source failure is reported and excluded, never replaced with invented data.
    """
    root = Path(root).resolve()
    inventory = json.loads((root / "data/sources.json").read_text(encoding="utf-8"))
    raw, processed = root / "data/raw", root / "data/processed"
    raw.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    records, chunks = [], []
    seen = set()
    for source in inventory["sources"]:
        source_id = _safe_id(source["source_id"])
        if source_id in seen:
            raise ValueError(f"Duplicate source_id: {source_id}")
        seen.add(source_id)
        record = {"source_id": source_id, "status": "inventory_only", "reason": source.get("status", "")}
        if source.get("status") != "active" or source.get("permission_status") != "allowed":
            records.append(record)
            continue
        try:
            metadata_blob, metadata_provenance = _artifact(raw, source_id, "metadata", source["metadata_url"], refresh)
            nasa = json.loads(metadata_blob)
            if str(nasa.get("id")) != source["ntrs_id"]:
                raise ValueError("NASA metadata identifier mismatch")
            determination = nasa.get("copyright", {}).get("determinationType", "")
            if determination not in {"PUBLIC_USE_PERMITTED", "GOV_PUBLIC_USE_PERMITTED"}:
                raise ValueError(f"NASA rights status needs review: {determination}")
            if nasa.get("distribution") != "PUBLIC":
                raise ValueError("NASA distribution status is not public")
            blob, provenance = _artifact(raw, source_id, "pdf", source["download_url"], refresh)
            extracted, report = pdf_chunks(blob, source)
            chunks.extend(extracted)
            record = {"source_id": source_id, "status": "ingested", "provenance": provenance,
                      "metadata_provenance": metadata_provenance, "rights_determination": determination,
                      "raw_data_downloaded": False, **report}
        except Exception as exc:
            record = {"source_id": source_id, "status": "failed", "error": f"{type(exc).__name__}: {exc}"}
        records.append(record)
    chunks.sort(key=lambda c: c["chunk_id"])
    serialized = "".join(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n" for c in chunks)
    # One atomic corpus replacement after all sources have been processed.
    temporary = processed / "chunks.jsonl.tmp"
    temporary.write_text(serialized, encoding="utf-8", newline="\n")
    temporary.replace(processed / "chunks.jsonl")
    manifest = {"schema_version": "1.0", "generated_at": utc_now(),
                "sources_inventory_sha256": sha256((root / "data/sources.json").read_bytes()),
                "corpus_sha256": sha256(serialized.encode("utf-8")), "chunk_count": len(chunks),
                "ingested_sources": sum(r["status"] == "ingested" for r in records),
                "failed_sources": sum(r["status"] == "failed" for r in records),
                "raw_experimental_datasets_downloaded": 0,
                "sources": records}
    (processed / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
