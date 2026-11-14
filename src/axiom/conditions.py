"""Validate scoped condition records without inferring scientific applicability.

Valid means schema and quotation provenance passed. It does not mean the quoted
text entails the extracted value, a proposed condition was tested, or a human
reviewer's identity was verified. No values, units or review statuses are coerced.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

TEXT_FIELDS = frozenset({"gravity", "fuel", "geometry", "apparatus"})
NUMERIC_UNITS = {"oxygen_percent": "%", "pressure_kpa": "kPa", "flow_cm_s": "cm/s",
                 "temperature_k": "K"}
FIELDS = TEXT_FIELDS | NUMERIC_UNITS.keys()
SCOPES = frozenset({"experiment_range", "setup", "individual_test"})
EVIDENCE_STATUSES = frozenset({"proposed", "reported", "background"})
REVIEW_STATUSES = frozenset({"ai_draft", "human_reviewed"})
REQUIRED = frozenset({"record_id", "source_id", "chunk_id", "quote", "field", "value", "unit",
                      "scope", "evidence_status", "review_status", "reviewer"})
ALLOWED = REQUIRED | {"notes"}


def normalize_quote(text: str) -> str:
    """Ignore layout whitespace only: mW and MW must remain different."""
    return " ".join(text.split())


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _finite_number(value: object) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _numeric_error(value: object, field: str) -> str | None:
    if not _finite_number(value):
        return "Numeric values must be finite JSON numbers, not booleans or numeric strings"
    if value < 0 or field == "oxygen_percent" and value > 100 or field == "pressure_kpa" and value == 0:
        return "Numeric value is outside the field's physical bounds"
    if field == "temperature_k" and value == 0:
        return "Numeric value is outside the field's physical bounds"
    return None


def validate_records(records: list[dict], chunks: list[dict] | dict[str, dict]) -> dict:
    """Return errors per record; never mutate input or promote draft extractions.

    Null is an explicit unknown value. Numeric ranges have exactly min/max keys
    and the canonical unit on the record. Proposed/background records may validate
    structurally but remain distinct from reported observations in the output.
    """
    if not isinstance(records, list):
        raise ValueError("records must be a list")
    if not isinstance(chunks, (list, dict)):
        raise ValueError("chunks must be a list or chunk_id mapping")
    errors, corpus_errors, chunk_index = [], [], {}
    iterable = list(chunks.values()) if isinstance(chunks, dict) else chunks
    for index, chunk in enumerate(iterable):
        if not isinstance(chunk, dict) or any(not _nonempty(chunk.get(k)) for k in ("chunk_id", "source_id", "text")):
            corpus_errors.append({"index": index, "code": "malformed_chunk", "message": "Chunks require nonempty chunk_id, source_id and text"})
            continue
        cid = chunk["chunk_id"]
        if isinstance(chunks, dict) and chunks.get(cid) is not chunk:
            corpus_errors.append({"index": index, "code": "chunk_key_mismatch", "message": "Mapping key must match the chunk_id"})
        if cid in chunk_index:
            corpus_errors.append({"index": index, "code": "duplicate_chunk_id", "message": f"Ambiguous chunk_id: {cid}"})
        chunk_index[cid] = chunk

    identifiers = {}
    for i, record in enumerate(records):
        if isinstance(record, dict) and _nonempty(record.get("record_id")):
            identifiers.setdefault(record["record_id"], []).append(i)
    valid = []
    for index, record in enumerate(records):
        local = []
        rid = record.get("record_id") if isinstance(record, dict) else None

        def error(code, message):
            local.append({"index": index, "record_id": rid if isinstance(rid, str) else None,
                          "code": code, "message": message})

        if not isinstance(record, dict):
            error("record_type", "Condition record must be an object")
            errors.extend(local)
            continue
        missing, extra = REQUIRED - record.keys(), record.keys() - ALLOWED
        if missing:
            error("missing_fields", "Missing fields: " + ", ".join(sorted(missing)))
        if extra:
            error("unknown_fields", "Unknown fields: " + ", ".join(sorted(extra)))
        for field in ("record_id", "source_id", "chunk_id", "quote"):
            if not _nonempty(record.get(field)):
                error("invalid_" + field, field + " must be a nonempty string")
        if _nonempty(rid) and len(identifiers[rid]) > 1:
            error("duplicate_record_id", "All records sharing this record_id are invalid")
        for key, choices in (("field", FIELDS), ("scope", SCOPES), ("evidence_status", EVIDENCE_STATUSES),
                             ("review_status", REVIEW_STATUSES)):
            value = record.get(key)
            if not isinstance(value, str) or value not in choices:
                error("invalid_" + key, f"{key} must be one of: " + ", ".join(sorted(choices)))
        if "notes" in record and not isinstance(record["notes"], str):
            error("invalid_notes", "notes must be a string")
        if record.get("review_status") == "ai_draft" and record.get("reviewer") is not None:
            error("draft_reviewer", "An AI draft must have reviewer=null")
        if record.get("review_status") == "human_reviewed" and not _nonempty(record.get("reviewer")):
            error("missing_reviewer", "human_reviewed requires a nonempty reviewer identifier")

        field, value, unit = record.get("field"), record.get("value"), record.get("unit")
        if isinstance(field, str) and field in TEXT_FIELDS:
            if value is not None and not _nonempty(value):
                error("invalid_value", "Categorical values must be nonempty strings or null for unknown")
            if unit is not None:
                error("invalid_unit", "Categorical fields require unit=null")
        elif isinstance(field, str) and field in NUMERIC_UNITS:
            if unit != NUMERIC_UNITS[field]:
                error("invalid_unit", f"{field} requires unit={NUMERIC_UNITS[field]!r}; no conversion is inferred")
            if value is not None:
                if isinstance(value, dict):
                    if set(value) != {"min", "max"}:
                        error("invalid_range", "A numeric range must contain exactly min and max")
                    else:
                        for endpoint in ("min", "max"):
                            problem = _numeric_error(value[endpoint], field)
                            if problem:
                                error("invalid_range", endpoint + ": " + problem)
                        if all(_finite_number(value[k]) for k in ("min", "max")) and value["min"] > value["max"]:
                            error("reversed_range", "Range min cannot exceed max")
                else:
                    problem = _numeric_error(value, field)
                    if problem:
                        error("invalid_value", problem)

        cid, sid, quote = record.get("chunk_id"), record.get("source_id"), record.get("quote")
        chunk = chunk_index.get(cid) if isinstance(cid, str) else None
        if chunk is None:
            error("unknown_chunk", "Referenced chunk_id is absent from the supplied corpus")
        else:
            if sid != chunk["source_id"]:
                error("source_mismatch", "source_id does not match the referenced chunk")
            if _nonempty(quote) and normalize_quote(quote) not in normalize_quote(chunk["text"]):
                error("quote_mismatch", "Quote is not a case-preserving, whitespace-normalized substring of the chunk")
        if corpus_errors:
            error("invalid_corpus", "Corpus has malformed, duplicate or miskeyed chunks; validation fails closed")
        errors.extend(local)
        if not local:
            valid.append(record)

    return {"schema_version": "1.0", "total_records": len(records), "valid_count": len(valid),
            "invalid_count": len(records) - len(valid), "errors": errors, "corpus_errors": corpus_errors,
            "valid_record_ids": [r["record_id"] for r in valid],
            "valid_by_review_status": {s: sum(r["review_status"] == s for r in valid) for s in sorted(REVIEW_STATUSES)},
            "valid_by_evidence_status": {s: sum(r["evidence_status"] == s for r in valid) for s in sorted(EVIDENCE_STATUSES)},
            "unknown_value_count": sum(r["value"] is None for r in valid),
            "validation_scope": "structure_and_quote_provenance_only", "automatic_approval": False,
            "notice": "Quotation presence does not verify extraction meaning, human review identity, or applicability. Proposed/background conditions are not test results. Unknown values remain null."}


def _read_jsonl(path: Path) -> list[dict]:
    records = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if line.strip():
            try:
                records.append(json.loads(line, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(f"Invalid JSON number: {x}"))))
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"{path.name}:{line_number}: {exc}") from exc
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        report = validate_records(_read_jsonl(args.root / "data/conditions.jsonl"),
                                  _read_jsonl(args.root / "data/processed/chunks.jsonl"))
    except (OSError, ValueError) as exc:
        parser.exit(2, f"AXIOM condition validation: {exc}\n")
    print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False))
    if report["invalid_count"] or report["corpus_errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
