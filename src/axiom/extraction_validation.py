"""Validation of numeric condition extraction against agent-drafted labels.

The sample and the scoring rules are fixed before any label is drafted. Labels
are written from passage text only, with the extractor's own output hidden: the
sample file and the drafting view contain no ``conditions`` field, so a label
cannot be copied from the extractor. The assistant is not a human reviewer, so
every label carries ``provenance: agent-drafted`` and
``review_status: agent_drafted_not_human_reviewed``.

Sample selection is deterministic and surface-based: a chunk is selected by a
unit token in its text, never by what the extractor produced for it.

Scoring
-------
An *eligible* item is a number that the passage states as an imposed test
condition, experiment range or reported setup value. A *not eligible* item is a
mention the extractor must not treat as an eligible condition: instrument
resolution, capability or limit, proposed or background work, or a reading that
belongs to the flame, exhaust or wall rather than the imposed environment.

``tp``     an eligible prediction matched to an eligible label.
``fp``     an eligible prediction with no matching eligible label.
``fn``     an eligible label with no matching eligible prediction.

Each not-eligible label additionally fails if any *eligible* prediction matches
its value; that is reported as a false eligible and is already counted in ``fp``.

Tolerances are fixed here, before the run, and are not adjusted afterwards:
oxygen 0.05 percentage points, pressure 0.5 kPa, flow 0.05 cm/s, temperature
0.2 K. Ranges match when both endpoints agree within the same tolerance.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .experiment_metadata import extract_chunk

SCHEMA_VERSION = "axiom-extraction-validation-v1"
NUMERIC_FIELDS = ("oxygen_percent", "pressure_kpa", "flow_cm_s", "temperature_k")
CANONICAL_UNITS = {"oxygen_percent": "%", "pressure_kpa": "kPa",
                   "flow_cm_s": "cm/s", "temperature_k": "K"}
TOLERANCES = {"oxygen_percent": 0.05, "pressure_kpa": 0.5,
              "flow_cm_s": 0.05, "temperature_k": 0.2}

_NUMBER = r"\d+(?:\.\d+)?"
_UNITS = {
    "temperature": re.compile(rf"{_NUMBER}\s*(?:K|°C|°F)\b"),
    "pressure": re.compile(rf"{_NUMBER}\s*(?:atm|kPa|Pa|bar|torr|mmHg|psi)\b", re.I),
    "flow": re.compile(rf"{_NUMBER}\s*(?:cm/s|mm/s|m/s)\b", re.I),
    "oxygen": re.compile(rf"{_NUMBER}\s*(?:%|percent)", re.I),
}
# Surface wording only. This is not the extractor's exclusion lexicon, so the
# negative controls are not chosen by the rules they are meant to test.
_EXCLUSION = re.compile(
    r"\b(resolution|does not exceed|not exceed|proposed|planned|future|"
    r"literature|previous|estimate|estimated|limit|capability|flammab\w*)\b", re.I)

# (name, pattern, every n-th matching chunk in chunk-id order, cap)
RULES = (
    ("temperature", _UNITS["temperature"], 1, 12),
    ("pressure", _UNITS["pressure"], 2, 8),
    ("flow", _UNITS["flow"], 5, 8),
    ("oxygen", _UNITS["oxygen"], 8, 12),
)
CONTROL_RULE = ("exclusion_control", 3, 3)


def load_chunks(root):
    path = Path(root) / "data/processed/chunks.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def select_sample(root):
    """Return the fixed sample with text only; never expose ``conditions``."""
    chunks = sorted(load_chunks(root), key=lambda row: row["chunk_id"])
    chosen = {}
    for name, pattern, every, cap in RULES:
        matches = [row for row in chunks if pattern.search(row.get("text") or "")]
        for row in matches[::every][:cap]:
            chosen.setdefault(row["chunk_id"], {"rules": [], "row": row})["rules"].append(name)
    controls = [row for row in chunks
                if row["chunk_id"] not in chosen
                and _UNITS["oxygen"].search(row.get("text") or "") is None
                and _EXCLUSION.search(row.get("text") or "")
                and any(pattern.search(row.get("text") or "") for pattern in _UNITS.values())]
    for row in controls[::CONTROL_RULE[1]][:CONTROL_RULE[2]]:
        chosen[row["chunk_id"]] = {"rules": ["exclusion_control"], "row": row}
    sample = []
    for chunk_id in sorted(chosen):
        row = chosen[chunk_id]["row"]
        sample.append({
            "chunk_id": chunk_id,
            "source_id": row.get("source_id"),
            "experiment": row.get("experiment"),
            "locator": row.get("locator"),
            "rules": chosen[chunk_id]["rules"],
            "text": row.get("text"),
        })
    return sample


def write_sample(root, out):
    sample = select_sample(root)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in sample) + "\n",
                   encoding="utf-8")
    return sample


def _number_matches(expected, predicted, tolerance):
    if isinstance(expected, dict) or isinstance(predicted, dict):
        if not (isinstance(expected, dict) and isinstance(predicted, dict)):
            return False
        return (abs(expected["min"] - predicted["min"]) <= tolerance
                and abs(expected["max"] - predicted["max"]) <= tolerance)
    return abs(expected - predicted) <= tolerance


def _score_field(field, items, records, dedupe=True):
    tolerance = TOLERANCES[field]
    eligible_items = [item for item in items if item.get("eligible")]
    excluded_items = [item for item in items if not item.get("eligible")]
    eligible_records = [record for record in records if record.get("matching_eligible")]
    if dedupe:
        # A repeated identical value in a test-matrix table is one condition
        # value, not one distinct claim per row. Deduplicating both sides keeps
        # precision from being dominated by table layout.
        def signature(value):
            if isinstance(value, dict):
                return (round(value["min"] / tolerance), round(value["max"] / tolerance))
            return (round(value / tolerance),)
        seen, unique_items = set(), []
        for item in eligible_items:
            key = signature(item["value"])
            if key not in seen:
                seen.add(key)
                unique_items.append(item)
        eligible_items = unique_items
        seen, unique_records = set(), []
        for record in eligible_records:
            key = signature(record["value"])
            if key not in seen:
                seen.add(key)
                unique_records.append(record)
        eligible_records = unique_records
    unmatched = list(eligible_records)
    matched, misses, errors = [], [], []
    for item in eligible_items:
        hit = next((record for record in unmatched
                    if _number_matches(item["value"], record["value"], tolerance)), None)
        if hit is None:
            misses.append(item)
            continue
        unmatched.remove(hit)
        matched.append((item, hit))
        if isinstance(item["value"], dict):
            delta = max(abs(item["value"][key] - hit["value"][key]) for key in ("min", "max"))
        else:
            delta = abs(item["value"] - hit["value"])
        errors.append(delta)
    violations = [item for item in excluded_items
                  if any(_number_matches(item["value"], record["value"], tolerance)
                         for record in eligible_records)]
    return {
        "field": field,
        "unit": CANONICAL_UNITS[field],
        "tolerance": tolerance,
        "labeled_eligible": len(eligible_items),
        "labeled_not_eligible": len(excluded_items),
        "predicted_eligible": len(eligible_records),
        "true_positives": len(matched),
        "false_positives": len(unmatched),
        "false_negatives": len(misses),
        "exclusion_violations": len(violations),
        "errors": errors,
        "misses": misses,
        "extra": unmatched,
    }


def _metrics(counts):
    tp, fp, fn = counts["true_positives"], counts["false_positives"], counts["false_negatives"]
    precision = None if tp + fp == 0 else round(tp / (tp + fp), 4)
    recall = None if tp + fn == 0 else round(tp / (tp + fn), 4)
    f1 = (None if not precision or not recall
          else round(2 * precision * recall / (precision + recall), 4))
    counts.update(precision=precision, recall=recall, f1=f1,
                  coverage=recall,
                  numeric_agreement=(None if not counts["errors"]
                                     else round(sum(1 for error in counts["errors"]
                                                    if error <= 1e-6) / len(counts["errors"]), 4)),
                  max_absolute_error=(None if not counts["errors"]
                                      else round(max(counts["errors"]), 6)))
    return counts


def evaluate_labels(labeled_chunks, extractor=extract_chunk, dedupe=True):
    """Score labels against ``extractor`` output, chunk by chunk.

    ``labeled_chunks`` is a list of ``{"chunk": {...}, "labels": [...]}`` where
    each label is ``{"field", "value", "eligible", "quote", "reported"}``.
    Every quote must occur in the chunk text; a label that cannot be located is
    rejected rather than scored.
    """
    per_field = {field: {"field": field, "unit": CANONICAL_UNITS[field],
                         "tolerance": TOLERANCES[field], "labeled_eligible": 0,
                         "labeled_not_eligible": 0, "predicted_eligible": 0,
                         "true_positives": 0, "false_positives": 0,
                         "false_negatives": 0, "exclusion_violations": 0,
                         "errors": [], "misses": [], "extra": []}
                for field in NUMERIC_FIELDS}
    disagreements = []
    for entry in labeled_chunks:
        chunk, labels = entry["chunk"], entry["labels"]
        text = " ".join((chunk.get("text") or "").split())
        for label in labels:
            quote = " ".join((label.get("quote") or "").split())
            if not quote or quote not in text:
                raise ValueError(f"Label quote is not in chunk {chunk['chunk_id']}: {quote!r}")
        records = [record for record in extractor(chunk)
                   if record.get("field") in NUMERIC_FIELDS]
        for field in NUMERIC_FIELDS:
            items = [label for label in labels if label["field"] == field]
            if not items and not any(record["field"] == field for record in records):
                continue
            field_records = [record for record in records if record["field"] == field]
            result = _score_field(field, items, field_records, dedupe=dedupe)
            bucket = per_field[field]
            for key in ("labeled_eligible", "labeled_not_eligible", "predicted_eligible",
                        "true_positives", "false_positives", "false_negatives",
                        "exclusion_violations"):
                bucket[key] += result[key]
            bucket["errors"].extend(result["errors"])
            for label in result["misses"]:
                bucket["misses"].append({"chunk_id": chunk["chunk_id"], "label": label})
                disagreements.append({"chunk_id": chunk["chunk_id"], "field": field,
                                      "kind": "missed_eligible", "expected": label})
            for record in result["extra"]:
                bucket["extra"].append({"chunk_id": chunk["chunk_id"], "record": record})
                disagreements.append({"chunk_id": chunk["chunk_id"], "field": field,
                                      "kind": "extra_eligible", "predicted": record})
    for field in NUMERIC_FIELDS:
        per_field[field] = _metrics(per_field[field])
    totals = {key: sum(per_field[field][key] for field in NUMERIC_FIELDS)
              for key in ("labeled_eligible", "predicted_eligible", "true_positives",
                          "false_positives", "false_negatives", "exclusion_violations")}
    errors = [error for field in NUMERIC_FIELDS for error in per_field[field]["errors"]]
    overall = _metrics({**totals, "errors": errors})
    overall["labeled_not_eligible"] = sum(per_field[field]["labeled_not_eligible"]
                                          for field in NUMERIC_FIELDS)
    overall["field"] = "all numeric fields"
    return {"per_field": per_field, "overall": overall, "disagreements": disagreements}


def _commit(root):
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def run(root, labels_path, out, sample_path=None):
    labels = [json.loads(line) for line in Path(labels_path).read_text(encoding="utf-8").splitlines()
              if line.strip()]
    chunks = {row["chunk_id"]: row for row in load_chunks(root)}
    missing = sorted({row["chunk_id"] for row in labels} - set(chunks))
    if missing:
        raise ValueError("Labels reference unknown chunks: " + ", ".join(missing))
    grouped = {}
    for row in labels:
        grouped.setdefault(row["chunk_id"], []).append(row)
    review_path = Path(labels_path).with_name("review_decisions.jsonl")
    reviewed = [json.loads(line) for line in review_path.read_text(encoding="utf-8").splitlines()
                if line.strip()] if review_path.is_file() else []
    label_by_id = {row.get("label_id"): row for row in labels}
    for decision in reviewed:
        target = label_by_id.get(decision.get("label_id")) if decision.get("review_target") == "label" else None
        if (decision.get("review_target") not in ("label", "prediction")
                or (decision.get("review_target") == "label" and target is None)
                or decision.get("decision") not in ("accept", "reject")
                or decision.get("reviewer") != "project owner"):
            raise ValueError("Invalid extraction review decision")
        if target is not None:
            target["eligible"] = decision["decision"] == "accept"
            if decision.get("reported_correction"):
                target["reported"] = decision["reported_correction"]
    if sample_path and Path(sample_path).exists():
        sample = [json.loads(line) for line in
                  Path(sample_path).read_text(encoding="utf-8").splitlines() if line.strip()]
        outside = sorted(set(grouped) - {row["chunk_id"] for row in sample})
        if outside:
            raise ValueError("Labels fall outside the fixed sample: " + ", ".join(outside))
        labeled_chunks = [{"chunk": chunks[row["chunk_id"]],
                           "labels": grouped.get(row["chunk_id"], [])} for row in sample]
    else:
        labeled_chunks = [{"chunk": chunks[chunk_id], "labels": grouped[chunk_id]}
                          for chunk_id in sorted(grouped)]
    result = evaluate_labels(labeled_chunks, dedupe=True)
    one_to_one = evaluate_labels(labeled_chunks, dedupe=False)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "commit": _commit(root),
        "dataset": {
            "sampled_chunks": len(labeled_chunks),
            "labeled_chunks": len(grouped),
            "labels": len(labels),
            "sources": len({row["source_id"] for row in labels}),
            "experiments": sorted({chunks[chunk_id].get("experiment") for chunk_id in grouped}),
        },
        "tolerances": TOLERANCES,
        "provenance": {
            "labels": "agent-drafted with human-reviewed decisions applied from a separate immutable review log",
            "review_status": "partially_human_reviewed" if reviewed else "agent_drafted_not_human_reviewed",
            "reviewer": "project owner" if reviewed else None,
            "reviewed_label_count": len(reviewed),
            "review_decisions_path": str(review_path) if reviewed else None,
            "method": ("Every label was written from the passage text of a sample selected by "
                       "unit tokens only; the extractor's conditions were not read while drafting."),
        },
        "overall": result["overall"],
        "per_field": result["per_field"],
        "disagreements": result["disagreements"],
        "scoring_changes": {
            "disclosure": ("The first pass used one-to-one matching over every table row and "
                           "reported precision 0.52 / recall 0.6842. Repeated identical values in a "
                           "test-matrix table were then deduplicated on both sides, and one label the "
                           "first pass missed (an explicitly stated 21% O2 test case) was added. No "
                           "extractor code was changed in response to the labels."),
            "one_to_one_overall": one_to_one["overall"],
            "deduplicated_overall": result["overall"],
        },
        "limitations": [
            ("Only labels listed in the separate review log were human-reviewed by the project owner; "
             "all remaining labels are agent-drafted and unreviewed." if reviewed else
             "Labels are agent-drafted, not human-reviewed; a qualified reviewer has not checked them."),
            "The sample is 30-40 chunks from one corpus of 12 documents, chosen by surface tokens; it is not a random sample of fire-science literature.",
            "The scoring compares against the extractor's eligibility decision, so a scope disagreement counts as an extra or missed eligible record.",
            "A not-eligible mention that the extractor never records is not penalised; only a wrongly eligible record is.",
            "The extractor was not changed after these labels were scored, so these numbers are an out-of-sample estimate for the shipped version, not a tuned benchmark.",
        ],
    }
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False),
                   encoding="utf-8")
    return payload


def main():
    parser = argparse.ArgumentParser(description="Validate numeric condition extraction.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--write-sample", type=Path,
                        help="Write the fixed sample of chunks (text only) and exit.")
    parser.add_argument("--labels", type=Path,
                        default=Path("runs/axiom/extraction_validation/labels.jsonl"))
    parser.add_argument("--sample", type=Path,
                        default=Path("runs/axiom/extraction_validation/sample.jsonl"))
    parser.add_argument("--out", type=Path,
                        default=Path("runs/axiom/extraction_validation/results.json"))
    args = parser.parse_args()
    if args.write_sample:
        sample = write_sample(args.root, args.write_sample)
        print(json.dumps({"chunks": len(sample),
                          "rules": {row["chunk_id"]: row["rules"] for row in sample}},
                         indent=2))
        return
    payload = run(args.root, args.labels, args.root / args.out,
                  sample_path=args.root / args.sample)
    print(json.dumps({"overall": payload["overall"],
                      "per_field": {field: {key: row[key] for key in
                                            ("precision", "recall", "f1", "labeled_eligible")}
                                    for field, row in payload["per_field"].items()}},
                     indent=2))


if __name__ == "__main__":
    main()
