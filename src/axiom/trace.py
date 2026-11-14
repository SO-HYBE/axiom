"""Versioned execution traces and the deterministic observation-integrity layer.

A trace is an ordered, append-only sequence of typed events plus a run-end
manifest. Each event carries a content hash over its canonical fields. The hash
detects accidental corruption of the recorded channel. It is not a signature and
does not resist an adversary that recomputes hashes; that attack is out of scope
and documented in ``docs/TRACE_MUTATIONS.md``.

The integrity layer never repairs an event. It classifies what it can trust and
what must stay unknown, and the monitor in ``monitor.py`` consumes that decision.
"""
from __future__ import annotations

import hashlib
import json

SCHEMA_VERSION = "axiom-trace-v1"

EVENT_TYPES = (
    "QUERY_RECEIVED",
    "EVIDENCE_RETRIEVED",
    "METADATA_EXTRACTED",
    "METADATA_VALIDATED",
    "CLAIM_GENERATED",
    "CLAIM_LINKED_TO_EVIDENCE",
    "APPLICABILITY_CHECKED",
    "CLAIM_VERIFIED",
    "CLAIM_WITHHELD",
    "CLAIM_PUBLISHED",
)

# Fields that participate in the content hash. ``content_hash`` itself is
# excluded so a hash can be computed and verified without circularity.
_HASH_EXCLUDED = frozenset({"content_hash"})


def canonical(event):
    """Return the canonical JSON text that the content hash covers."""
    body = {key: value for key, value in event.items() if key not in _HASH_EXCLUDED}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(event):
    return hashlib.sha256(canonical(event).encode("utf-8")).hexdigest()


def make_event(event_type, run_id, seq, **fields):
    """Build one event with a computed content hash.

    Sequence numbers are authoritative. Timestamps are optional and are carried
    as data only; no ordering property depends on them.
    """
    if event_type not in EVENT_TYPES:
        raise ValueError("Unknown event type: " + str(event_type))
    if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1:
        raise ValueError("seq must be a positive integer")
    event = dict(fields)
    event.update({
        "event_id": event.pop("event_id", f"{run_id}-{seq:04d}-{event_type.lower()}"),
        "type": event_type,
        "run_id": run_id,
        "seq": seq,
        "timestamp": event.pop("timestamp", None),
        "schema_version": SCHEMA_VERSION,
    })
    event["content_hash"] = content_hash(event)
    return event


def make_trace(run_id, events, scenario_version=None, metadata_version=None,
               manifest=None):
    """Wrap events and a manifest. Stored order is preserved, not sorted.

    Preserving the recorded order is what lets the integrity layer notice that a
    channel delivered events out of sequence.
    """
    events = list(events)
    if manifest is None:
        manifest = {
            "event_count": len(events),
            "last_seq": max((event.get("seq") for event in events
                             if isinstance(event.get("seq"), int)), default=0),
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "events": events,
        "manifest": manifest,
        "versions": {"scenario_version": scenario_version,
                     "metadata_version": metadata_version},
    }


def _content_equal(left, right):
    body = lambda event: {key: value for key, value in event.items()
                          if key not in _HASH_EXCLUDED}
    return body(left) == body(right)


def integrity(trace):
    """Classify trust in one trace before any property is evaluated.

    Returns the trusted events in sequence order, discarded idempotent
    duplicates, untrusted events, and trust flags. No event is ever fabricated
    and no missing event is imputed.
    """
    events = trace.get("events") or []
    manifest = trace.get("manifest") or {}
    duplicates_identical, duplicates_conflicting = [], []
    hash_mismatch, malformed = [], []
    seen_ids, seen_seq = {}, {}
    trusted = []

    for index, event in enumerate(events):
        if not isinstance(event, dict) or event.get("type") not in EVENT_TYPES:
            malformed.append({"index": index, "event_id": None,
                              "reason": "Unknown or missing event type"})
            continue
        event_id = event.get("event_id")
        seq = event.get("seq")
        stored = event.get("content_hash")
        if not isinstance(event_id, str) or not event_id:
            malformed.append({"index": index, "event_id": None,
                              "reason": "Missing event_id"})
            continue
        if stored is not None and stored != content_hash(event):
            hash_mismatch.append({"index": index, "event_id": event_id, "type": event["type"],
                                  "seq": seq, "reason": "Content hash does not match"})
            continue
        if stored is None:
            malformed.append({"index": index, "event_id": event_id, "type": event["type"],
                              "reason": "Missing content_hash"})
            continue

        if event_id in seen_ids:
            first = seen_ids[event_id]
            if _content_equal(first, event):
                duplicates_identical.append({"event_id": event_id, "seq": seq,
                                             "type": event["type"]})
            else:
                duplicates_conflicting.append({"event_id": event_id, "seq": seq,
                                               "type": event["type"]})
            continue
        if isinstance(seq, int) and not isinstance(seq, bool) and seq in seen_seq:
            duplicates_conflicting.append({"event_id": event_id, "seq": seq,
                                           "type": event["type"]})
            continue
        seen_ids[event_id] = event
        if isinstance(seq, int) and not isinstance(seq, bool):
            seen_seq[seq] = event
        trusted.append(event)

    seqs = [event.get("seq") for event in trusted]
    observed_seqs = [event.get("seq") for event in events
                     if isinstance(event, dict) and isinstance(event.get("seq"), int)
                     and not isinstance(event.get("seq"), bool)]
    seq_usable = all(isinstance(seq, int) and not isinstance(seq, bool) for seq in seqs)
    unique_seq = (len(set(observed_seqs)) == len(observed_seqs)
                  and len(observed_seqs) == len(events))
    stored_order = [event.get("seq") for event in events if isinstance(event.get("seq"), int)]
    delivery_order_reliable = stored_order == sorted(stored_order)

    ordered = sorted(trusted, key=lambda event: event.get("seq", 0))
    observed = len(events)
    expected = manifest.get("event_count")
    last_seq = manifest.get("last_seq")
    gap_detected = False
    if seq_usable and seqs:
        present = set(seqs)
        gap_detected = any(seq not in present for seq in range(1, max(seqs) + 1))
    run_incomplete = (
        expected is None or not isinstance(expected, int) or observed != expected
        or last_seq is None or (seq_usable and seqs and max(seqs) != last_seq)
        or gap_detected
    )
    ordering_unreliable = not delivery_order_reliable or not seq_usable or not unique_seq

    return {
        "schema_version": "axiom-integrity-v1",
        "events_observed": observed,
        "events_trusted": len(trusted),
        "trusted": ordered,
        "discarded_duplicates": duplicates_identical,
        "flags": {
            "gap_detected": gap_detected,
            "duplicate_identical": duplicates_identical,
            "duplicate_conflicting": duplicates_conflicting,
            "hash_mismatch": hash_mismatch,
            "malformed": malformed,
            "delivery_order_reliable": delivery_order_reliable,
            "seq_usable": seq_usable,
            "seq_unique": unique_seq,
            "ordering_unreliable": ordering_unreliable,
            "ordering_recoverable": seq_usable and unique_seq,
            "run_incomplete": run_incomplete,
        },
        "manifest": {"event_count": expected, "last_seq": last_seq},
        "notices": [
            "The content hash detects accidental corruption only; it is not a signature.",
            "A discarded exact duplicate is idempotent. A conflicting duplicate makes the event untrusted.",
            "No missing event is reconstructed; absence is treated as missing observation.",
        ],
    }


def _citation_rows(claim):
    rows = []
    for citation in claim.get("citations") or []:
        chunk_id = citation.get("chunk_id") or citation.get("source_id")
        if chunk_id:
            rows.append({"chunk_id": chunk_id,
                         "quote": citation.get("quote"),
                         "source_id": citation.get("source_id")})
    return rows


def build_trace(run, metadata_version="chunk-conditions-v1", question_id=None):
    """Project a recorded pipeline run into a versioned trace.

    This is a post-hoc, deterministic projection: it does not change pipeline
    behaviour and it invents no event that the run did not produce. The baseline
    and RAG-only arms have no verification stage, so their claims carry no
    CLAIM_VERIFIED event and are published with an explicit ``unverified`` label.
    """
    run_id = run.get("run_id") or "run"
    system = run.get("system")
    claim_prefix = question_id or run_id
    events, seq = [], 0

    def add(event_type, **fields):
        nonlocal seq
        seq += 1
        events.append(make_event(event_type, run_id, seq, timestamp=seq * 1000, **fields))

    add("QUERY_RECEIVED", question=run.get("question"), system=system)
    evidence = run.get("evidence") or []
    evidence_ids = [row.get("chunk_id") for row in evidence if row.get("chunk_id")]
    add("EVIDENCE_RETRIEVED", evidence_ids=evidence_ids)
    fields = {}
    for row in evidence:
        for key, value in (row.get("conditions") or {}).items():
            if value is not None and key not in fields:
                fields[key] = value
    add("METADATA_EXTRACTED", metadata_version=metadata_version, fields=fields)
    add("METADATA_VALIDATED", metadata_version=metadata_version,
        validation_status="automatic", valid=bool(evidence_ids))

    target = run.get("target") or {}
    scenario_version = "scenario-" + hashlib.sha256(
        json.dumps(target, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    claims = run.get("claims") or []
    published = []
    for index, claim in enumerate(claims):
        claim_id = f"{claim_prefix}-c{index + 1}"
        citations = _citation_rows(claim)
        linked_ids = sorted({row["chunk_id"] for row in citations})
        add("CLAIM_GENERATED", claim_id=claim_id, text=claim.get("text"))
        add("CLAIM_LINKED_TO_EVIDENCE", claim_id=claim_id,
            evidence_ids=linked_ids, citations=citations)
        applicability = claim.get("applicability") or "not_assessed"
        outcome = {"documented_alignment": "WITHIN_DOCUMENTED_SCOPE",
                   "partially_documented": "WITHIN_DOCUMENTED_SCOPE",
                   "outside_documented_conditions": "CONDITION_MISMATCH",
                   "no_documented_conditions": "INSUFFICIENT_INFORMATION",
                   "not_assessed": "NOT_ASSESSED"}.get(applicability, "NOT_ASSESSED")
        add("APPLICABILITY_CHECKED", claim_id=claim_id,
            scenario_id=target.get("scenario_id"), scenario_version=scenario_version,
            outcome=outcome, source="recorded_claim_applicability")
        status = claim.get("evidence_status")
        if system == "ignis" and status in ("supported", "unverified", "withheld"):
            verdict = {"supported": "supported", "unverified": "unverified",
                       "withheld": "withheld"}[status]
            required = ["METADATA_VALIDATED"]
            if run.get("applicability_requested") or applicability != "not_assessed":
                required.append("APPLICABILITY_CHECKED")
            add("CLAIM_VERIFIED", claim_id=claim_id, verdict=verdict,
                evidence_ids=linked_ids, scenario_version=scenario_version,
                metadata_version=metadata_version, applicability_outcome=outcome,
                required_checks=required)
            if verdict == "withheld":
                add("CLAIM_WITHHELD", claim_id=claim_id, reason="recorded critic verdict")
            elif not run.get("abstained"):
                published.append((claim_id, "verified" if outcome == "WITHIN_DOCUMENTED_SCOPE"
                                  else "unverified", linked_ids))
        elif not run.get("abstained") and claim.get("verdict") != "blocked":
            published.append((claim_id, "unverified", linked_ids))

    for claim_id, label, linked_ids in published:
        add("CLAIM_PUBLISHED", claim_id=claim_id, label=label,
            evidence_ids=linked_ids, scenario_version=scenario_version,
            metadata_version=metadata_version)
    return make_trace(run_id, events, scenario_version=scenario_version,
                      metadata_version=metadata_version)
