"""Deterministic applicability engine for AXIOM.

The engine turns the existing per-investigation comparison into a field-level and
overall applicability report. It is a pure function over already-extracted,
quoted condition records. No model participates.

Meaning of the overall outcome
------------------------------
``CONFLICTING_EVIDENCE``
    At least one specified field is documented with a matching value by one
    direct investigation and a contradicting value by another, so the corpus
    does not resolve which documented regime applies to the scenario.
``WITHIN_DOCUMENTED_SCOPE``
    No specified field is conflicting, and at least one *direct* investigation
    documents an exact or range-containing value for **every** specified field.
    This is a necessary evidence check. It is not proof of physical
    transferability, safety or behaviour.
``CONDITION_MISMATCH``
    No direct investigation covers the full combination, at least one specified
    field is documented only at contradicting values, and no direct investigation
    matches that field.
``INSUFFICIENT_INFORMATION``
    Anything else: a required field is undocumented or only unqualified, or the
    fields are individually documented but no single direct investigation covers
    the combination.

Precedence is evaluated in the order listed above. The order is fixed and is
reported with every assessment.

Scope of the field registry
---------------------------
The source documents do not separate "fuel" from "material", or "geometry" from
"configuration", and they use one term for each pair. AXIOM therefore exposes the
brief's nine logical fields while reusing the documented record for the shared
physical attribute:

* oxygen -> ``oxygen_percent``
* pressure -> ``pressure_kpa``
* airflow -> ``flow_cm_s``
* gravity -> ``gravity``
* fuel -> ``fuel``
* material -> ``fuel`` (same documented attribute; no second value invented)
* geometry -> ``geometry``
* configuration -> ``apparatus`` (test configuration/apparatus)
* temperature -> ``temperature_k``

No value is inferred for a field that the corpus does not document.
"""
from __future__ import annotations

from .transferability import FIELDS, FIELD_LABELS, NUMERIC_FIELDS

OVERALL_ORDER = (
    "CONFLICTING_EVIDENCE",
    "WITHIN_DOCUMENTED_SCOPE",
    "CONDITION_MISMATCH",
    "INSUFFICIENT_INFORMATION",
)
FIELD_OUTCOMES = ("MATCH", "MISMATCH", "CONFLICTING", "UNKNOWN")

# The nine logical fields required by the AXIOM brief, mapped to the documented
# attribute that actually carries the evidence.
LOGICAL_FIELDS = (
    ("oxygen", "oxygen concentration", "oxygen_percent"),
    ("pressure", "pressure", "pressure_kpa"),
    ("airflow", "airflow / ventilation", "flow_cm_s"),
    ("gravity", "gravity regime", "gravity"),
    ("fuel", "fuel", "fuel"),
    ("material", "material", "fuel"),
    ("geometry", "geometry", "geometry"),
    ("configuration", "test configuration", "apparatus"),
    ("temperature", "temperature", "temperature_k"),
)

PRECEDENCE_NOTE = (
    "CONFLICTING_EVIDENCE is checked first because contradictory documentation invalidates a "
    "scope claim, then WITHIN_DOCUMENTED_SCOPE, then CONDITION_MISMATCH, then "
    "INSUFFICIENT_INFORMATION. WITHIN requires one direct investigation to document every "
    "specified field and no specified field to be conflicting; it is a necessary evidence "
    "check, never proof of physical transferability or safety."
)


def _direct(investigation):
    return investigation.get("relevance", {}).get("evidence_type") in ("direct", "unclassified")


def _matches(field, target, value):
    if field in NUMERIC_FIELDS:
        if isinstance(value, dict):
            return value["min"] <= target <= value["max"]
        return abs(float(value) - float(target)) <= 1e-9
    return value == target


def _evaluations(target, investigations):
    """Return per-source-field records and classifications from investigations."""
    rows = []
    for investigation in investigations:
        for parameter in investigation.get("parameters", []):
            if parameter["field"] not in target:
                continue
            rows.append((investigation, parameter))
    return rows


def _evidence(parameter):
    items = []
    for record in parameter.get("records", []):
        items.append({
            "source_id": record["source_id"],
            "chunk_id": record["chunk_id"],
            "locator": record.get("locator"),
            "quote": record["quote"],
            "value": record.get("value"),
            "unit": record.get("unit"),
            "evidence_status": record.get("evidence_status"),
            "scope": record.get("scope"),
            "extraction": "deterministic_pattern_v1",
            "validation_status": "automatic",
        })
    return items


def _field_outcome(field, target, investigations):
    target_value = target[field]
    direct_rows = [(i, p) for i, p in _evaluations({field: target_value}, investigations) if _direct(i)]
    match_rows = [i for i, p in direct_rows if p["classification"] in ("exact_match", "partial_match")]
    mismatch_rows = [i for i, p in direct_rows if p["classification"] == "mismatch"]
    unknown_rows = [(i, p) for i, p in direct_rows if p["classification"] == "unknown"]
    all_records = [r for _, p in direct_rows for r in p.get("records", [])]
    unqualified = [r for _, p in direct_rows for r in p.get("unqualified_records", [])]

    if match_rows and mismatch_rows:
        outcome = "CONFLICTING"
        reason = ("Different direct investigations document a matching value and a contradicting "
                  "value for this field. The corpus does not resolve which applies.")
    elif match_rows:
        outcome = "MATCH"
        reason = "At least one direct investigation documents an equal value or a range containing it."
    elif mismatch_rows:
        outcome = "MISMATCH"
        reason = "Direct investigations document this field, but no documented value matches."
    else:
        outcome = "UNKNOWN"
        if unqualified:
            reason = ("A mention exists but is not a qualified reported test condition, so it cannot "
                      "support a match.")
        else:
            reason = ("No direct investigation documents a qualified value. This is not evidence that "
                      "the condition was never tested.")
    if not all_records and not unqualified:
        missing_status = "missing"
    elif not all_records and unqualified:
        missing_status = "ambiguous_present_but_unqualified"
    else:
        missing_status = "documented"
    return {
        "field": field,
        "label": FIELD_LABELS[field],
        "scenario_value": target_value,
        "unit": NUMERIC_FIELDS.get(field),
        "outcome": outcome,
        "reason": reason,
        "basis": "reported_test_condition" if all_records else (
            "unqualified_mention_only" if unqualified else "not_documented_in_available_corpus"),
        "missing_status": missing_status,
        "validation_status": "automatic",
        "extraction": "deterministic_pattern_v1",
        "matched_investigations": [i["investigation_id"] for i in match_rows],
        "mismatched_investigations": [i["investigation_id"] for i in mismatch_rows],
        "unknown_investigations": [i["investigation_id"] for i, _ in unknown_rows],
        "evidence": [item for _, p in direct_rows for item in _evidence(p)],
    }


def _full_coverage(investigation, fields):
    by_field = {p["field"]: p for p in investigation.get("parameters", [])}
    if not _direct(investigation):
        return False
    for field in fields:
        parameter = by_field.get(field)
        if not parameter or parameter["classification"] not in ("exact_match", "partial_match"):
            return False
    return True


def summarize(assessment):
    """Return the AXIOM applicability block for one scenario assessment."""
    target = assessment.get("target") or {}
    investigations = assessment.get("investigations") or []
    specified = [field for field in FIELDS if field in target]
    if not specified:
        return {
            "schema_version": "axiom-applicability-v1",
            "overall": "INSUFFICIENT_INFORMATION",
            "overall_reason": "No scenario parameter was specified, so no evidence check is possible.",
            "precedence": list(OVERALL_ORDER),
            "precedence_note": PRECEDENCE_NOTE,
            "logical_fields": [],
            "field_outcomes": [],
            "full_coverage_investigations": [],
            "necessary_not_sufficient": True,
            "limitations": [
                "No scenario parameter was specified, so the engine cannot check documented scope.",
                "WITHIN_DOCUMENTED_SCOPE is a necessary evidence check, not proof of physical transferability or safety.",
                "A missing field means the available corpus does not document it; it is not proof that NASA never tested it.",
            ],
        }

    fields = [_field_outcome(field, target, investigations) for field in specified]
    outcomes = {row["field"]: row["outcome"] for row in fields}
    conflict_fields = [row["field"] for row in fields if row["outcome"] == "CONFLICTING"]
    mismatch_fields = [row["field"] for row in fields if row["outcome"] == "MISMATCH"]
    unknown_fields = [row["field"] for row in fields if row["outcome"] == "UNKNOWN"]
    full = ([] if conflict_fields
            else [i["investigation_id"] for i in investigations if _full_coverage(i, specified)])

    if conflict_fields:
        overall = "CONFLICTING_EVIDENCE"
        reason = ("The corpus documents both matching and contradicting values for: " + ", ".join(
                      FIELD_LABELS[f] for f in conflict_fields) + ". A scope claim cannot be made "
                  "until the applicable documented regime is resolved.")
    elif full:
        overall = "WITHIN_DOCUMENTED_SCOPE"
        reason = ("At least one direct investigation documents an exact or range-containing value for "
                  "every specified field: " + ", ".join(full) + ".")
    elif mismatch_fields and not any(o == "MATCH" for o in outcomes.values()):
        overall = "CONDITION_MISMATCH"
        reason = ("No direct investigation covers the full combination, and the documented values "
                  "contradict the scenario for: " + ", ".join(
                      FIELD_LABELS[f] for f in mismatch_fields) + ".")
    else:
        overall = "INSUFFICIENT_INFORMATION"
        if unknown_fields:
            reason = ("No direct investigation covers the full combination, and some specified fields "
                      "are not documented with a qualified value: " + ", ".join(
                          FIELD_LABELS[f] for f in unknown_fields) + ".")
        elif mismatch_fields:
            reason = ("No direct investigation covers the full combination, and some investigations "
                      "document contradicting values while others match.")
        else:
            reason = ("Each specified field is documented somewhere, but no single direct investigation "
                      "documents the full combination.")

    logical = []
    for key, label, source_field in LOGICAL_FIELDS:
        if source_field not in target:
            continue
        source = next(row for row in fields if row["field"] == source_field)
        logical.append({
            "key": key,
            "label": label,
            "source_field": source_field,
            "outcome": source["outcome"],
            "missing_status": source["missing_status"],
            "scenario_value": source["scenario_value"],
            "unit": source["unit"],
            "note": None if key not in ("material", "configuration") else (
                "Shares the documented %s attribute because the source documents do not separate them." %
                FIELD_LABELS[source_field]),
        })

    return {
        "schema_version": "axiom-applicability-v1",
        "overall": overall,
        "overall_reason": reason,
        "precedence": list(OVERALL_ORDER),
        "precedence_note": PRECEDENCE_NOTE,
        "specified_fields": specified,
        "field_outcomes": fields,
        "logical_fields": logical,
        "full_coverage_investigations": full,
        "conflict_fields": conflict_fields,
        "mismatch_fields": mismatch_fields,
        "unknown_fields": unknown_fields,
        "necessary_not_sufficient": True,
        "limitations": [
            "WITHIN_DOCUMENTED_SCOPE is a necessary evidence check, not proof of physical transferability or safety.",
            "A mismatch means the corpus documents a different condition, not that the scenario is physically unsafe.",
            "Missing means the available corpus does not document the condition; it is not proof that NASA never tested it.",
            "Condition comparison cannot establish apparatus, scale, ignition or measurement-definition equivalence.",
            "All condition records are machine-extracted and not human-reviewed.",
        ],
    }
