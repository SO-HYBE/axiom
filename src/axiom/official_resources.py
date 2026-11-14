"""Resource inventory and source-aware processing helpers for the challenge set.

The inventory describes supplied URLs; it does not assert that they were
acquired. PSI catalog snapshots are explicitly kept distinct from raw data.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener


INVENTORY = "data/official_resources.json"
REPORT = "data/official_resource_report.json"
CATEGORY_TIERS = {
        "primary_experimental_data": 0,
    "scientific_publication": 1,
    "scientific_background": 2,
    "repository_catalog": 3,
    "historical_safety_incident": 4,
    "educational_multimedia": 5,
    "technology_transfer": 6,
}


def _read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key: " + key)
            result[key] = value
        return result
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Invalid JSON number")))


def load_inventory(root):
    value = _read_json(Path(root) / INVENTORY)
    rows = value.get("resources")
    if value.get("schema_version") != "axiom-official-resources-v1" or not isinstance(rows, list) or len(rows) != 10:
        raise ValueError("Official resource inventory must contain ten supplied resources")
    ids = [row.get("resource_id") for row in rows]
    if ids != [f"R{i}" for i in range(1, 11)]:
        raise ValueError("Official resource IDs must be the ordered R1-R10 set")
    for row in rows:
        if not all(isinstance(row.get(key), str) and row[key] for key in ("title", "category", "provider", "url", "access_method")):
            raise ValueError("Official resource has incomplete identity")
    return value


def _resource_content(root, row):
    chunks_path = Path(root) / "data/processed/chunks.jsonl"
    chunks = []
    if chunks_path.is_file():
        for line in chunks_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                chunk = json.loads(line)
                if chunk.get("source_id") in row.get("source_ids", []):
                    chunks.append(chunk)
    named_path = Path(root) / "data/processed/named_sources"
    if named_path.is_dir():
        for source_id in row.get("source_ids", []):
            path = named_path / (source_id + ".json")
            if path.is_file():
                data = _read_json(path)
                chunks.extend(data if isinstance(data, list) else data.get("chunks", []))
    official_path = Path(root) / "data/processed/official_resources"
    if official_path.is_dir():
        for path in official_path.glob("*.json"):
            data = _read_json(path)
            if data.get("resource_id") == row["resource_id"]:
                chunks.extend(data.get("chunks", []))
    return chunks


def build_report(root):
    """Build truthful live counts from indexed files and the supplied inventory."""
    root = Path(root)
    inventory = load_inventory(root)
    prior_named = {}
    named_manifest = root / "data/benchmark_sources.json"
    if named_manifest.is_file():
        named_value = _read_json(named_manifest)
        prior_named = {record.get("source_id"): record for record in named_value.get("sources", [])}
    results = []
    for row in inventory["resources"]:
        chunks = _resource_content(root, row)
        unique = {chunk.get("chunk_id"): chunk for chunk in chunks if chunk.get("chunk_id")}
        acquired = bool(unique)
        official_dir = root / "data/raw/official" / row["resource_id"]
        asset_records = [_read_json(sidecar) for sidecar in sorted(official_dir.glob("*.provenance.json"))] if official_dir.is_dir() else []
        if row["resource_id"] == "R1":
            # PSI `files` snapshots are JSON directory listings, not dataset
            # bytes. Raw experimental file count stays zero until file assets
            # themselves are acquired and recorded separately.
            raw_data_count = 0
            acquisition_status = "catalog_metadata_acquired_raw_datasets_not_acquired" if acquired else ("guide_acquired_catalog_unmapped" if asset_records else "not_acquired")
            processing_status = "catalog_descriptions_indexed_raw_datasets_not_processed" if acquired else "not_processed"
        elif acquired:
            raw_data_count = 0
            acquisition_status = "acquired_and_indexed"
            processing_status = "indexed"
        elif asset_records:
            raw_data_count = 0
            acquisition_status = "asset_acquired_not_indexed"
            processing_status = "not_processed"
        else:
            raw_data_count = 0
            acquisition_status = "acquired" if acquired else "not_acquired"
            processing_status = "indexed" if acquired else "not_processed"
        metadata_fields = sum(1 for chunk in unique.values() for value in (chunk.get("conditions") or {}).values() if value is not None)
        related_source_records = []
        for source_id in row.get("source_ids", []):
            source = prior_named.get(source_id)
            if source:
                related_source_records.append({key: source.get(key) for key in
                    ("source_id", "title", "url", "source_kind", "status", "permission_status",
                     "rights", "sections", "assets", "derived_path", "derived_sha256", "chunk_count")})
        evidence_preview = [{"evidence_id": c.get("chunk_id"), "source_id": c.get("source_id"),
                             "title": c.get("title"), "canonical_url": c.get("url"),
                             "locator": c.get("locator"), "text": c.get("text"),
                             "resource_id": row["resource_id"],
                             "source_category": "repository_catalog" if c.get("source_kind") == "dataset_catalog" else row["category"],
                             "evidence_role": c.get("evidence_role"),
                             "conditions": c.get("conditions") or {}}
                            for c in sorted(unique.values(), key=lambda item: item.get("chunk_id", ""))]
        results.append(dict(row, acquisition_status=acquisition_status,
                            processing_status=processing_status,
                            acquired_source_assets=[{key: item.get(key) for key in ("url", "final_url", "retrieved_at", "http_status", "content_type", "bytes", "sha256")} for item in asset_records],
                            acquired_source_asset_count=len(asset_records),
                            indexed_documents=len({c.get("document_url") or c.get("url") for c in unique.values()}),
                            indexed_chunks=len(unique), extracted_records=0,
                            raw_experimental_files=raw_data_count,
                            extracted_nonnull_condition_fields=metadata_fields,
                            indexed_evidence=evidence_preview,
                            related_existing_source_records=related_source_records,
                            metadata_validation_status="not_human_reviewed" if metadata_fields else "not_available"))
    return {
        "schema_version": "axiom-resource-report-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "resource_count": len(results),
        "acquired_resource_count": sum(r["acquired_source_asset_count"] > 0 or r["indexed_chunks"] > 0 for r in results),
        "indexed_resource_count": sum(r["indexed_chunks"] > 0 for r in results),
        "processed_resource_count": sum(r["indexed_chunks"] > 0 for r in results),
        "raw_experimental_file_count": sum(r["raw_experimental_files"] for r in results),
        "indexed_chunk_count": sum(r["indexed_chunks"] for r in results),
        "extracted_experiment_record_count": sum(r["extracted_records"] for r in results),
        "limitations": ["URL inventory does not mean acquisition.", "Existing PSI snapshots are investigation catalog metadata, not experimental data files.", "R3 official English caption endpoint returned an empty response; only the watch page is retained, without transcript or indexing.", "NASA Spinoff R8-R10 passages are stored with rights review required and are excluded from retrieval.", "No scientific or metadata field has human-reviewed status."],
        "resources": results,
    }


def write_report(root, destination=None):
    """Persist a timestamped snapshot; never overwrite source acquisition assets."""
    root = Path(root)
    target = Path(destination) if destination else root / "data/official_resource_report.json"
    if not target.is_absolute():
        target = root / target
    target.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(build_report(root), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    target.write_text(body, encoding="utf-8")
    return {"report_path": str(target), "resource_count": 10}


def ingest_events(resource_id, stages):
    """Create a separate versioned acquisition ledger; it does not assert truth.

    Event hashes detect accidental modification only. This is not the AXIOM
    claim-monitor trace and parse success is not scientific validation.
    """
    allowed = {"RESOURCE_DISCOVERED", "RESOURCE_ACQUIRED", "RESOURCE_PARSE_STARTED",
               "RESOURCE_PARSE_COMPLETED", "RESOURCE_PARSE_FAILED", "METADATA_EXTRACTED",
               "METADATA_VALIDATED", "EVIDENCE_INDEXED", "EVIDENCE_RETRIEVED"}
    events = []
    run_id = "resource-" + resource_id
    for seq, stage in enumerate(stages, 1):
        if stage.get("type") not in allowed or stage.get("resource_id", resource_id) != resource_id:
            raise ValueError("Invalid resource ingestion event")
        body = {"event_id": f"{run_id}-{seq:04d}", "schema_version": "axiom-resource-events-v1",
                "run_id": run_id, "seq": seq, "timestamp": stage.get("timestamp") or datetime.now(timezone.utc).isoformat(),
                "resource_id": resource_id, "type": stage["type"], "payload": stage.get("payload", {})}
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        body["content_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        events.append(body)
    return {"schema_version": "axiom-resource-events-v1", "run_id": run_id,
            "events": events, "manifest": {"event_count": len(events), "last_seq": len(events)}}


def process_structured(blob, media_type):
    """Preserve structured values and columns; never normalize scientific data."""
    if len(blob) > 20_000_000:
        raise ValueError("Structured source exceeds 20 MB processing limit")
    text = blob.decode("utf-8-sig")
    kind = media_type.lower().split(";", 1)[0].strip()
    if kind in ("text/csv", "application/csv"):
        rows = list(csv.DictReader(io.StringIO(text, newline="")))
        return {"format": "csv", "columns": list(rows[0].keys()) if rows else [], "records": rows}
    if kind in ("application/json", "text/json"):
        return {"format": "json", "value": json.loads(text, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Invalid JSON number")))}
    if kind in ("application/xml", "text/xml") or text.lstrip().startswith("<?xml"):
        root = ET.fromstring(text)
        def node(element):
            return {"tag": element.tag, "attributes": dict(element.attrib),
                    "text": element.text, "children": [node(child) for child in element]}
        return {"format": "xml", "value": node(root)}
    raise ValueError("Unsupported structured media type")


def parse_webvtt(blob):
    """Parse supplied captions with timestamps; no transcription is attempted."""
    text = blob.decode("utf-8-sig")
    cues = []
    for block in text.replace("\r", "").split("\n\n"):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        timing = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing is None:
            continue
        if timing + 1 >= len(lines):
            raise ValueError("Caption cue has no text")
        cues.append({"start": lines[timing].split("-->", 1)[0].strip(),
                     "end": lines[timing].split("-->", 1)[1].strip().split()[0],
                     "text": " ".join(lines[timing + 1:])})
    return cues


MAX_RESOURCE_BYTES = 12_000_000
OFFICIAL_HOSTS = frozenset({"www.nasa.gov", "nasa.gov", "sma.nasa.gov", "spinoff.nasa.gov", "assets.science.nasa.gov", "www.youtube.com"})


def _official_url(url):
    from urllib.parse import urlparse
    parsed = urlparse(url)
    return (parsed.scheme == "https" and parsed.hostname in OFFICIAL_HOSTS
            and not parsed.username and not parsed.password and not parsed.port)


def _atomic_bytes(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _extract_sma_sections(blob):
    """Extract only named SMA incident sections; their role stays historical."""
    from html.parser import HTMLParser
    class Sections(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.current = None
            self.buffers = {}
            self.skip = 0
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag in ("script", "style", "noscript"):
                self.skip += 1
            if tag == "div" and attrs.get("id") in ("history", "accident", "investigation", "lessons"):
                self.current = attrs["id"]
                self.buffers.setdefault(self.current, [])
            if self.current and tag in ("p", "h1", "h2", "h3", "li", "br"):
                self.buffers[self.current].append("\n")
        def handle_endtag(self, tag):
            if tag in ("script", "style", "noscript") and self.skip:
                self.skip -= 1
            if self.current and tag == "div":
                self.buffers[self.current].append("\n")
            if tag in ("p", "h1", "h2", "h3", "li") and self.current:
                self.buffers[self.current].append("\n")
        def handle_data(self, data):
            if self.current and not self.skip and data.strip():
                self.buffers[self.current].append(data.strip())
    parser = Sections()
    parser.feed(blob.decode("utf-8-sig"))
    output = []
    for section, parts in parser.buffers.items():
        text = re.sub(r"\s+", " ", " ".join(parts)).strip()
        if text:
            output.append({"section": section, "locator": "NASA SMA page section: " + section,
                           "text": text})
    if not output:
        raise ValueError("NASA SMA incident page has no supported history/investigation sections")
    return output


def _fetch_official(url, limit=MAX_RESOURCE_BYTES):
    if not _official_url(url):
        raise ValueError("Resource URL is outside the exact official-host allowlist")
    request = Request(url, headers={"User-Agent": "AXIOM-research/0.1 (source acquisition; contact via project repository)",
                                    "Accept-Encoding": "identity"})
    with build_opener().open(request, timeout=30) as response:
        if not _official_url(response.url):
            raise ValueError("Official resource redirected to an unapproved host")
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
        length = response.headers.get("Content-Length")
        if length and int(length) > limit:
            raise ValueError("Official resource exceeds configured byte limit")
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError("Official resource exceeds configured byte limit")
        if not data:
            raise ValueError("Official resource response is empty")
        return data, {"url": url, "final_url": response.url,
                      "retrieved_at": datetime.now(timezone.utc).isoformat(),
                      "http_status": response.status, "content_type": content_type,
                      "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def _acquire_youtube_captions(root, row):
    import html
    video_id = "W1oXykoz9zg"
    watch_url = row["url"]
    page, page_meta = _fetch_official(watch_url, 3_000_000)
    source = page.decode("utf-8", "replace")
    match = re.search(r'"playerCaptionsTracklistRenderer":', source)
    if not match:
        raise ValueError("Official video page exposes no caption track list")
    start = source.find("{", match.end())
    tracks, _ = json.JSONDecoder().raw_decode(source[start:])
    track = next((item for item in tracks.get("captionTracks", [])
                  if item.get("languageCode") == "en" and item.get("baseUrl")), None)
    if track is None:
        raise ValueError("No official English caption track is available")
    caption_url = track["baseUrl"]
    if not caption_url.startswith("https://www.youtube.com/api/timedtext?"):
        raise ValueError("Caption track endpoint is not the official YouTube timed-text endpoint")
    caption_blob, caption_meta = _fetch_official(caption_url, 4_000_000)
    root_path = Path(root)
    asset_dir = root_path / "data/raw/official/R3"
    page_path = asset_dir / "page.html"
    caption_path = asset_dir / "captions-en.xml"
    def save_asset(path, blob, meta):
        sidecar = path.with_suffix(path.suffix + ".provenance.json")
        _atomic_bytes(path, blob)
        safe_meta = {"url": watch_url, "final_url": meta["final_url"], "retrieved_at": meta["retrieved_at"],
                     "http_status": meta["http_status"], "content_type": meta["content_type"],
                     "bytes": meta["bytes"], "sha256": meta["sha256"], "asset_role": meta.get("asset_role")}
        _atomic_bytes(sidecar, (json.dumps(safe_meta, sort_keys=True, indent=2) + "\n").encode())
        return dict(safe_meta, path=str(path.relative_to(root_path)).replace("\\", "/"), filename=path.name)
    page_asset = save_asset(page_path, page, dict(page_meta, asset_role="official_video_page"))
    caption_meta = dict(caption_meta, asset_role="official_english_captions")
    caption_asset = save_asset(caption_path, caption_blob, caption_meta)
    cues = parse_webvtt(caption_blob) if caption_blob.lstrip().startswith(b"WEBVTT") else []
    if not cues:
        xml_root = ET.fromstring(caption_blob)
        for node in xml_root.findall("text"):
            try:
                begin = float(node.attrib["start"])
                duration = float(node.attrib.get("dur", "0"))
            except (KeyError, ValueError):
                continue
            cues.append({"start": begin, "end": begin + duration,
                         "text": html.unescape("".join(node.itertext())).strip()})
    if not cues:
        raise ValueError("Official English caption file contains no timestamped cues")
    chunks = []
    for cue in cues:
        text = cue["text"]
        if not text:
            continue
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        chunks.append({"chunk_id": f"r3-{len(chunks)+1:03d}-{digest[:16]}",
                       "resource_id": "R3", "source_id": "r3-video",
                       "source_category": row["category"], "title": row["title"],
                       "url": watch_url, "document_url": watch_url,
                       "text": text, "sha256": digest, "source_kind": row["category"],
                       "evidence_tier": CATEGORY_TIERS[row["category"]], "locator": f"Video {cue['start']}–{cue['end']} seconds",
                       "timestamp_start": cue["start"], "timestamp_end": cue["end"],
                       "conditions": {}, "permission_status": "review_required", "status": "active",
                       "evidence_role": "educational_narration", "source_asset_sha256": caption_asset["sha256"],
                       "notice": "Official English caption track; educational narration, not primary experimental evidence. Rights review pending."})
    derived = root_path / "data/processed/official_resources/r3.json"
    _atomic_bytes(derived, (json.dumps({"resource_id": "R3", "generated_at": datetime.now(timezone.utc).isoformat(),
                                         "assets": [page_asset, caption_asset], "chunks": chunks},
                                        ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"))
    return {"resource_id": "R3", "assets": [page_asset, caption_asset]}


def acquire_official_resources(root, resource_ids=None):
    """Acquire allowlisted challenge HTML and the linked R4 guide PDF.

    PSI raw data files require record/file-level review. Existing source assets
    are preserved and reused only after sidecar/hash checks.
    """
    root = Path(root)
    wanted = set(resource_ids or {f"R{i}" for i in (2, 3, 4, 5, 6, 7, 8, 9, 10)})
    inventory = load_inventory(root)
    selected = [row for row in inventory["resources"] if row["resource_id"] in wanted]
    acquired = []
    for row in selected:
        if row["resource_id"] == "R3":
            acquired.append(_acquire_youtube_captions(root, row))
            continue
        url = row["url"]
        assets = [("page.html", url)]
        if row["resource_id"] == "R4":
            # This exact PDF URL is published as the guide's linked document.
            assets.append(("researchers-guide.pdf", "https://www.nasa.gov/wp-content/uploads/2016/05/np-2015-10-034-jsc_combustion_in_reduced_gravity-iss-mini-book-011116-508.pdf"))
        row_assets = []
        for filename, asset_url in assets:
            if not _official_url(asset_url):
                raise ValueError("Asset URL is outside the official-host allowlist")
            path = root / "data/raw/official" / row["resource_id"] / filename
            sidecar = path.with_suffix(path.suffix + ".provenance.json")
            if path.exists() or sidecar.exists():
                if not path.is_file() or not sidecar.is_file():
                    raise ValueError("Existing official asset is incomplete; preserved without overwrite")
                data = path.read_bytes()
                meta = _read_json(sidecar)
                if meta.get("url") != asset_url or meta.get("sha256") != hashlib.sha256(data).hexdigest() or meta.get("bytes") != len(data):
                    raise ValueError("Existing official asset provenance does not match; preserved")
            else:
                data, meta = _fetch_official(asset_url)
                _atomic_bytes(path, data)
                _atomic_bytes(sidecar, (json.dumps(meta, sort_keys=True, indent=2) + "\n").encode())
            meta = dict(meta, path=str(path.relative_to(root)).replace("\\", "/"), filename=filename)
            row_assets.append(meta)
            if filename.endswith(".html"):
                if row["resource_id"] in ("R5", "R6"):
                    sections = _extract_sma_sections(data)
                else:
                    from .source_text import extract_html_sections
                    sections = extract_html_sections(data)
                chunks = []
                for section in sections:
                    for part_no, part in enumerate(section["text"].split("\n\n"), 1):
                        text = part.strip()
                        if not text:
                            continue
                        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
                        chunks.append({"chunk_id": f"{row['resource_id'].lower()}-{len(chunks)+1:03d}-{digest[:16]}",
                                       "resource_id": row["resource_id"], "source_id": row["resource_id"].lower(),
                                       "source_category": row["category"], "title": row["title"],
                                       "url": row["url"], "document_url": asset_url,
                                       "text": text, "sha256": digest,
                                       "source_kind": row["category"], "evidence_tier": CATEGORY_TIERS.get(row["category"], 99),
                                       "locator": section.get("locator") or section.get("section") or f"article block {part_no}",
                                       "conditions": {}, "permission_status": "review_required" if row["category"] == "technology_transfer" else "allowed",
                                       "status": "active", "evidence_role": "source_context",
                                       "source_asset_sha256": meta["sha256"],
                                       "notice": "Official NASA page text; source category limits interpretation. This is not a validated experimental measurement."})
                derived = root / "data/processed/official_resources" / f"{row['resource_id'].lower()}.json"
                _atomic_bytes(derived, (json.dumps({"resource_id": row["resource_id"], "generated_at": datetime.now(timezone.utc).isoformat(), "assets": row_assets, "chunks": chunks}, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"))
                row_assets[-1]["indexed_chunks"] = len(chunks)
            else:
                from pypdf import PdfReader
                if not data.startswith(b"%PDF-"):
                    raise ValueError("The R4 guide asset is not a PDF")
                reader = PdfReader(io.BytesIO(data))
                chunks = []
                for page_num, page in enumerate(reader.pages, 1):
                    text = (page.extract_text() or "").strip()
                    if not text:
                        continue
                    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
                    chunks.append({"chunk_id": f"r4-p{page_num:03d}-{digest[:16]}",
                                   "resource_id": "R4", "source_id": "r4-guide",
                                   "source_category": row["category"], "title": row["title"],
                                   "url": row["url"], "document_url": asset_url,
                                   "text": text, "sha256": digest, "source_kind": row["category"],
                                   "evidence_tier": CATEGORY_TIERS.get(row["category"], 99),
                                   "locator": f"PDF page {page_num}", "conditions": {},
                                   "permission_status": "allowed", "status": "active",
                                   "evidence_role": "source_context", "source_asset_sha256": meta["sha256"],
                                   "notice": "NASA researcher guide text with physical page locator; extraction is not scientific validation."})
                derived = root / "data/processed/official_resources" / "r4-guide.json"
                _atomic_bytes(derived, (json.dumps({"resource_id": "R4", "generated_at": datetime.now(timezone.utc).isoformat(), "assets": row_assets, "chunks": chunks}, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"))
                row_assets[-1]["indexed_chunks"] = len(chunks)
        acquired.append({"resource_id": row["resource_id"], "assets": row_assets})
    return {"acquired": acquired, "acquired_resource_count": len(acquired)}
