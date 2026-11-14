"""Deterministic trace mutations for the AXIOM trace lab.

Channel mutations model an unreliable observation channel. They never recompute
a content hash: damaged content must be *detected* by the integrity layer, not
silently re-signed. The original trace is never modified; every operator returns
a new list of event dictionaries.

Two adversarial helpers (``duplicate_conflicting`` and ``*_rehash``) deliberately
recompute hashes so the lab can show what happens when the documented threat
model is violated. They are reported separately and never mixed into the
channel-damage metrics.

Operators
---------
``loss``                  remove one event
``reorder``               swap the stored position of two adjacent events
``duplicate_identical``   copy one event exactly
``duplicate_conflicting`` same event id, different payload, rehashed (adversarial)
``corrupt_payload``       change a payload value, keep the old hash
``corrupt_evidence_ref``  change an evidence identifier, keep the old hash
``corrupt_seq``           change a sequence number, keep the old hash
``corrupt_timestamp``     change a timestamp, keep the old hash
``delay``                 move an event later in delivery order and shift its timestamp
``corrupt_evidence_ref_rehash`` adversarial variant of the evidence corruption
``corrupt_seq_rehash``    adversarial variant of the sequence corruption
"""
from __future__ import annotations

import copy
import random

from .trace import content_hash

CHANNEL_OPERATORS = (
    "loss", "reorder", "duplicate_identical", "corrupt_payload",
    "corrupt_evidence_ref", "corrupt_seq", "corrupt_timestamp", "delay",
)
ADVERSARIAL_OPERATORS = (
    "duplicate_conflicting", "corrupt_evidence_ref_rehash", "corrupt_seq_rehash",
)
OPERATORS = CHANNEL_OPERATORS + ADVERSARIAL_OPERATORS

# Event types that carry the fields a corruption operator can target.
_EVIDENCE_BEARING = ("CLAIM_LINKED_TO_EVIDENCE", "CLAIM_VERIFIED", "CLAIM_PUBLISHED",
                     "EVIDENCE_RETRIEVED")


def _copy(trace):
    return {**trace, "events": copy.deepcopy(trace["events"])}


def _rng(seed, operator):
    return random.Random(f"axiom:{seed}:{operator}")


def _pick(rows, rng, predicate):
    eligible = [index for index, row in enumerate(rows) if predicate(row)]
    return rng.choice(eligible) if eligible else None


def _rehash(event):
    event["content_hash"] = content_hash(event)
    return event


def apply(trace, operator, seed=0):
    """Return ``(mutated_trace, record)`` or ``(None, None)`` if not applicable."""
    if operator not in OPERATORS:
        raise ValueError("Unknown mutation operator: " + operator)
    mutated = _copy(trace)
    rows = mutated["events"]
    rng = _rng(seed, operator)
    record = {"operator": operator, "seed": seed, "adversarial": operator in ADVERSARIAL_OPERATORS}

    if operator == "loss":
        index = _pick(rows, rng, lambda row: True)
        record.update(index=index, event=rows[index])
        del rows[index]
    elif operator == "reorder":
        index = _pick(rows, rng, lambda row: True)
        other = (index + 1) % len(rows)
        if other == index:
            return None, None
        rows[index], rows[other] = rows[other], rows[index]
        record.update(index=index, other=other, event=rows[other])
    elif operator == "duplicate_identical":
        index = _pick(rows, rng, lambda row: True)
        rows.insert(index, copy.deepcopy(rows[index]))
        record.update(index=index, event=rows[index])
    elif operator == "duplicate_conflicting":
        index = _pick(rows, rng, lambda row: True)
        twin = copy.deepcopy(rows[index])
        twin["claim_id"] = "conflict-" + str(twin.get("claim_id"))
        _rehash(twin)
        rows.insert(index, twin)
        record.update(index=index, event=twin)
    elif operator in ("corrupt_payload", "corrupt_evidence_ref", "corrupt_evidence_ref_rehash"):
        if operator.startswith("corrupt_evidence_ref"):
            index = _pick(rows, rng, lambda row: bool(row.get("evidence_ids")))
            if index is None:
                return None, None
            rows[index]["evidence_ids"] = list(rows[index]["evidence_ids"]) + ["ghost-evidence"]
            record["field"] = "evidence_ids"
        else:
            index = _pick(rows, rng, lambda row: "claim_id" in row or "question" in row)
            if index is None:
                return None, None
            for key in ("question", "claim_id", "outcome", "label", "verdict"):
                if key in rows[index]:
                    rows[index][key] = str(rows[index][key]) + "-corrupt"
                    record["field"] = key
                    break
        record.update(index=index, event=rows[index])
        if operator.endswith("_rehash"):
            _rehash(rows[index])
    elif operator in ("corrupt_seq", "corrupt_seq_rehash"):
        index = _pick(rows, rng, lambda row: isinstance(row.get("seq"), int))
        if index is None:
            return None, None
        rows[index]["seq"] = rows[index]["seq"] + 1000
        record.update(index=index, event=rows[index], field="seq")
        if operator.endswith("_rehash"):
            _rehash(rows[index])
    elif operator == "corrupt_timestamp":
        index = _pick(rows, rng, lambda row: row.get("timestamp") is not None)
        if index is None:
            return None, None
        rows[index]["timestamp"] = rows[index]["timestamp"] + 10_000_000
        record.update(index=index, event=rows[index], field="timestamp")
    elif operator == "delay":
        index = _pick(rows, rng, lambda row: row.get("timestamp") is not None)
        if index is None:
            return None, None
        row = rows.pop(index)
        row["timestamp"] = (row.get("timestamp") or 0) + 60_000
        rows.append(row)
        record.update(index=index, event=row, field="timestamp")
    else:  # pragma: no cover - guarded above
        raise ValueError(operator)

    record["event_type"] = record["event"]["type"]
    record["event_id"] = record["event"]["event_id"]
    return mutated, record


def describe(operator):
    """Plain-English description used by the Trace Lab UI."""
    return {
        "loss": "Remove one event from the recorded channel.",
        "reorder": "Swap the delivery position of two adjacent events; sequence numbers are untouched.",
        "duplicate_identical": "Deliver one event twice, byte for byte.",
        "duplicate_conflicting": "Deliver the same event id with a different payload and a recomputed hash (adversarial).",
        "corrupt_payload": "Change one payload field and keep the old content hash.",
        "corrupt_evidence_ref": "Add a fabricated evidence identifier and keep the old content hash.",
        "corrupt_evidence_ref_rehash": "Add a fabricated evidence identifier and recompute the hash (adversarial).",
        "corrupt_seq": "Change one sequence number and keep the old content hash.",
        "corrupt_seq_rehash": "Change one sequence number and recompute the hash (adversarial).",
        "corrupt_timestamp": "Change one timestamp and keep the old content hash.",
        "delay": "Deliver one event later and shift its timestamp; sequence numbers are untouched.",
    }[operator]
