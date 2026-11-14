"""Surface bounded, source-local value differences for scope review.

Quote provenance validation does not establish that an extracted value is correct
or that two records describe the same test. Every automated hint remains a draft.
"""
from collections import defaultdict
from copy import deepcopy
from itertools import combinations

from .conditions import normalize_quote, validate_records


COMPARISON_FIELDS = frozenset({"pressure_kpa", "oxygen_percent", "flow_cm_s", "geometry"})
MAX_HINTS = 12


def _value_key(record):
    value = record["value"]
    if record["field"] == "geometry":
        return normalize_quote(value)
    if isinstance(value, dict):
        return value["min"], value["max"]
    return value, value


def conflict_hints(records, chunks):
    """Compare compatible recorded scopes without merging conditions or studies.

    The scope/status labels are necessary grouping boundaries. Their shared value
    does not establish identical experimental context. Quotes and notes remain
    attached so distinct subsets, stages and extraction errors can be reviewed.
    """
    report = validate_records(records, chunks)
    valid_ids = set(report["valid_record_ids"])
    groups = defaultdict(list)
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("record_id"), str):
            continue
        if record["record_id"] not in valid_ids:
            continue
        if record["field"] not in COMPARISON_FIELDS or record["value"] is None:
            continue
        key = (record["source_id"], record["field"], record["scope"],
               record["evidence_status"], record["unit"] or "")
        groups[key].append(record)

    hints = []
    for key in sorted(groups):
        group = sorted(groups[key], key=lambda record: record["record_id"])
        for left, right in combinations(group, 2):
            if _value_key(left) == _value_key(right):
                continue
            pair = (left, right)
            hints.append({
                "kind": "reported_value_difference",
                "field": left["field"],
                "source_id": left["source_id"],
                "record_ids": [record["record_id"] for record in pair],
                "chunk_ids": [record["chunk_id"] for record in pair],
                "values": [deepcopy(record["value"]) for record in pair],
                "unit": left["unit"],
                "scopes": [record["scope"] for record in pair],
                "evidence_status": left["evidence_status"],
                "quotes": [record["quote"] for record in pair],
                "notes": [record.get("notes", "") for record in pair],
                "record_review_statuses": [record["review_status"] for record in pair],
                "review_status": "ai_draft",
                "requires_scope_review": True,
                "explanation": (
                    f"These {left['evidence_status']} entries carry different {left['field']} values "
                    "under the same recorded scope. Compare their quotations and notes to determine "
                    "whether they describe separate test subsets, stages, or an extraction error. "
                    "Quotation provenance has been checked; scientific compatibility requires scope review."
                ),
            })
            if len(hints) == MAX_HINTS:
                return hints
    return hints
