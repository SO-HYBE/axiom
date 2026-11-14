"""Seeded pipeline faults with labels fixed by construction.

The generator injects a known process bug into a valid trace. Unlike the channel
mutations in ``mutations.py``, these traces are internally consistent: they carry
valid content hashes because a genuinely buggy pipeline would have emitted them.
Each fault declares the property it violates before the monitor runs, so the
label does not depend on monitor code.
"""
from __future__ import annotations

import copy

from .trace import make_event, make_trace

FAULTS = (
    ("publish_before_verify", "P8", "Publication is emitted before its verification."),
    ("stale_verification", "P3", "Publication presents a scenario version that the verification did not cover."),
    ("dangling_citation", "P1", "Publication cites an evidence record that was never retrieved."),
    ("scope_expansion", "P4", "A claim is verified within scope while a check reports a condition mismatch."),
    ("missing_check", "P2", "A supported verification requires an applicability check but none was emitted."),
    ("missing_metadata_validation", "P2", "A supported verification has no metadata validation in a complete run."),
    ("withheld_published", "P5", "A withheld claim is also published."),
    ("uncertain_as_verified", "P5", "An unverified claim is published with a verified label."),
    ("missing_verification", "P5", "A verified publication has no verification event."),
    ("conflicting_duplicate", "P7", "One event id carries two different payloads."),
)


def _rebuild(events, run_id):
    """Renumber contiguously and recompute hashes as a pipeline would."""
    rebuilt = []
    for index, event in enumerate(events, 1):
        body = {key: value for key, value in event.items()
                if key not in ("type", "seq", "content_hash", "run_id", "schema_version")}
        rebuilt.append(make_event(event["type"], run_id, index, **body))
    return rebuilt


def _trace(original, events):
    return make_trace(original["run_id"], events,
                      scenario_version=(original.get("versions") or {}).get("scenario_version"),
                      metadata_version=(original.get("versions") or {}).get("metadata_version"))


def _first(events, event_type, claim_id=None):
    for index, event in enumerate(events):
        if event.get("type") == event_type and (claim_id is None or event.get("claim_id") == claim_id):
            return index, event
    return None, None


def _published_with_verification(events):
    """Return ``(publish_index, publish, verify_index, verify)`` for a claim with both."""
    for publish_index, publish in enumerate(events):
        if publish.get("type") != "CLAIM_PUBLISHED":
            continue
        verify_index, verify = _first(events, "CLAIM_VERIFIED", publish.get("claim_id"))
        if verify is not None:
            return publish_index, publish, verify_index, verify
    return None, None, None, None


def inject(trace, fault):
    """Return ``(faulty_trace, label)`` or ``(None, None)`` if the fault does not apply."""
    if fault not in {name for name, _, _ in FAULTS}:
        raise ValueError("Unknown fault: " + fault)
    rows = copy.deepcopy(trace["events"])
    run_id = trace["run_id"]
    label = {"fault": fault, "expected_property": dict((name, prop) for name, prop, _ in FAULTS)[fault],
             "expected_verdict": "FAIL",
             "description": dict((name, text) for name, text, _ in FAULTS)[fault]}

    if fault == "publish_before_verify":
        publish_index, publish, verify_index, verify = _published_with_verification(rows)
        if publish is None:
            return None, None
        rows[publish_index] = make_event("CLAIM_PUBLISHED", run_id, verify["seq"],
                                         **{key: value for key, value in publish.items()
                                            if key not in ("type", "run_id", "seq", "content_hash", "schema_version")})
        rows[verify_index] = make_event("CLAIM_VERIFIED", run_id, publish["seq"],
                                        **{key: value for key, value in verify.items()
                                           if key not in ("type", "run_id", "seq", "content_hash", "schema_version")})
        rows = sorted(rows, key=lambda row: row["seq"])

    elif fault == "stale_verification":
        index, publish, _, _ = _published_with_verification(rows)
        if publish is None:
            return None, None
        body = {key: value for key, value in publish.items()
                if key not in ("type", "run_id", "seq", "content_hash", "schema_version")}
        body["scenario_version"] = str(body.get("scenario_version")) + "-stale"
        rows[index] = make_event("CLAIM_PUBLISHED", run_id, publish["seq"], **body)

    elif fault == "dangling_citation":
        index, publish = _first(rows, "CLAIM_PUBLISHED")
        linked_index, linked = _first(rows, "CLAIM_LINKED_TO_EVIDENCE",
                                      publish.get("claim_id") if publish else None)
        if publish is None or linked is None:
            return None, None
        for target_index, event in ((index, publish), (linked_index, linked)):
            body = {key: value for key, value in event.items()
                    if key not in ("type", "run_id", "seq", "content_hash", "schema_version")}
            body["evidence_ids"] = list(body.get("evidence_ids") or []) + ["ghost-evidence"]
            rows[target_index] = make_event(event["type"], run_id, event["seq"], **body)

    elif fault == "scope_expansion":
        index, publish = _first(rows, "CLAIM_PUBLISHED")
        claim_id = publish.get("claim_id") if publish else None
        check_index, check = _first(rows, "APPLICABILITY_CHECKED", claim_id)
        verify_index, verify = _first(rows, "CLAIM_VERIFIED", claim_id)
        if verify is None:
            return None, None
        body = {key: value for key, value in verify.items()
                if key not in ("type", "run_id", "seq", "content_hash", "schema_version")}
        body["applicability_outcome"] = "WITHIN_DOCUMENTED_SCOPE"
        rows[verify_index] = make_event("CLAIM_VERIFIED", run_id, verify["seq"], **body)
        if check is None:
            rows.append(make_event("APPLICABILITY_CHECKED", run_id, verify["seq"] + 1,
                                   claim_id=claim_id,
                                   scenario_version=verify.get("scenario_version"),
                                   outcome="CONDITION_MISMATCH"))
        else:
            body = {key: value for key, value in check.items()
                    if key not in ("type", "run_id", "seq", "content_hash", "schema_version")}
            body["outcome"] = "CONDITION_MISMATCH"
            rows[check_index] = make_event("APPLICABILITY_CHECKED", run_id, check["seq"], **body)

    elif fault == "missing_check":
        _, publish, _, verify = _published_with_verification(rows)
        if verify is None or verify.get("verdict") != "supported":
            return None, None
        claim_id = verify.get("claim_id")
        rows = [row for row in rows if not (row.get("type") == "APPLICABILITY_CHECKED"
                                            and row.get("claim_id") == claim_id)]
        index = next(index for index, row in enumerate(rows) if row["event_id"] == verify["event_id"])
        body = {key: value for key, value in verify.items()
                if key not in ("type", "run_id", "seq", "content_hash", "schema_version")}
        body["required_checks"] = ["METADATA_VALIDATED", "APPLICABILITY_CHECKED"]
        body["applicability_outcome"] = "WITHIN_DOCUMENTED_SCOPE"
        rows[index] = make_event("CLAIM_VERIFIED", run_id, verify["seq"], **body)
        rows = _rebuild(rows, run_id)

    elif fault == "missing_metadata_validation":
        if not any(row.get("type") == "METADATA_VALIDATED" for row in rows):
            return None, None
        if not any(row.get("type") == "CLAIM_VERIFIED"
                   and row.get("verdict") == "supported" for row in rows):
            return None, None
        rows = [row for row in rows if row.get("type") != "METADATA_VALIDATED"]
        rows = _rebuild(rows, run_id)

    elif fault == "withheld_published":
        index, publish, _, _ = _published_with_verification(rows)
        if publish is None:
            index, publish = _first(rows, "CLAIM_PUBLISHED")
        if publish is None:
            return None, None
        rows.append(make_event("CLAIM_WITHHELD", run_id, len(rows) + 1,
                               claim_id=publish.get("claim_id"), reason="seeded fault"))

    elif fault == "uncertain_as_verified":
        publish_index, publish, index, verify = _published_with_verification(rows)
        if verify is None:
            return None, None
        body = {key: value for key, value in verify.items()
                if key not in ("type", "run_id", "seq", "content_hash", "schema_version")}
        body["verdict"] = "unverified"
        rows[index] = make_event("CLAIM_VERIFIED", run_id, verify["seq"], **body)
        body = {key: value for key, value in publish.items()
                if key not in ("type", "run_id", "seq", "content_hash", "schema_version")}
        body["label"] = "verified"
        rows[publish_index] = make_event("CLAIM_PUBLISHED", run_id, publish["seq"], **body)

    elif fault == "missing_verification":
        publish_index, publish, index, verify = _published_with_verification(rows)
        if verify is None:
            return None, None
        rows = [row for row in rows if row["event_id"] != verify["event_id"]]
        for position, row in enumerate(rows):
            if row.get("event_id") == publish["event_id"]:
                body = {key: value for key, value in row.items()
                        if key not in ("type", "run_id", "seq", "content_hash", "schema_version")}
                body["label"] = "verified"
                rows[position] = make_event("CLAIM_PUBLISHED", run_id, row["seq"], **body)
        rows = _rebuild(rows, run_id)

    elif fault == "conflicting_duplicate":
        index, event = _first(rows, "EVIDENCE_RETRIEVED")
        if event is None:
            index, event = _first(rows, "CLAIM_GENERATED")
        if event is None:
            return None, None
        twin = {key: value for key, value in event.items()
                if key not in ("type", "run_id", "seq", "content_hash", "schema_version")}
        if "evidence_ids" in twin:
            twin["evidence_ids"] = list(twin["evidence_ids"]) + ["ghost-evidence"]
        else:
            twin["text"] = "conflicting duplicate"
        rows.append(make_event(event["type"], run_id, event["seq"], **twin))

    label["applicable"] = True
    return _trace(trace, rows), label
