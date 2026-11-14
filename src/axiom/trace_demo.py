"""Build deterministic, non-persistent Trace Lab demonstrations from a saved run."""
from __future__ import annotations

import json
from pathlib import Path

from .monitor import evaluate
from .mutations import apply
from .trace import build_trace

PRESETS = {
    "remove_validation": "Remove validation event",
    "publish_before_verify": "Reorder publish before verify",
    "corrupt_evidence_id": "Corrupt evidence ID",
}


def _example_run(root):
    jobs = root / "runs/benchmarks/3c3cc0f1e4b949a8a33296e94417f13c/jobs"
    if not jobs.is_dir():
        raise FileNotFoundError("Recorded AXIOM example run is unavailable")
    for path in sorted(jobs.glob("*--ignis.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        run = record.get("run") or {}
        if run.get("claims") and not run.get("abstained"):
            return record["question_id"], run
    raise ValueError("No published claim is available for the trace demonstration")


def build_demo(root: Path, preset: str):
    """Return an original and a single deterministic mutation, without writing files."""
    if preset not in PRESETS:
        raise ValueError("Unknown Trace Lab preset")
    question_id, run = _example_run(Path(root))
    original = build_trace(run, question_id=question_id)
    mutated = {**original, "events": [dict(event) for event in original["events"]]}
    if preset == "remove_validation":
        index = next((i for i, event in enumerate(mutated["events"])
                      if event["type"] == "METADATA_VALIDATED"), None)
        if index is None:
            raise ValueError("Example trace has no metadata validation event")
        event = mutated["events"].pop(index)
        mutation = {"operator": "loss", "event_id": event["event_id"],
                    "event_type": event["type"], "adversarial": False}
        explanation = ("The run-end manifest still includes the removed validation event. "
                       "The incomplete observation makes dependent verification properties UNKNOWN.")
    elif preset == "publish_before_verify":
        events = mutated["events"]
        verify_index = next((i for i, event in enumerate(events)
                             if event["type"] == "CLAIM_VERIFIED"), None)
        if verify_index is None:
            raise ValueError("Example trace has no verification event")
        claim_id = events[verify_index].get("claim_id")
        publish_index = next((i for i, event in enumerate(events)
                              if event["type"] == "CLAIM_PUBLISHED"
                              and event.get("claim_id") == claim_id), None)
        if publish_index is None:
            raise ValueError("Example verification has no matching publication")
        events[verify_index], events[publish_index] = events[publish_index], events[verify_index]
        mutation = {"operator": "reorder", "event_id": events[verify_index]["event_id"],
                    "event_type": "CLAIM_PUBLISHED", "adversarial": False}
        explanation = ("The delivery order places publication before verification while sequence "
                       "numbers remain unchanged. Ordering is unreliable, so P8 and dependent "
                       "claims cannot be trusted as if the run were correctly ordered.")
    else:
        mutated, mutation = apply(original, "corrupt_evidence_ref", seed=0)
        if mutated is None:
            raise ValueError("Example trace has no evidence reference to corrupt")
        explanation = ("An evidence identifier was altered while its original hash was retained. "
                       "The integrity layer detects the hash mismatch and does not treat the "
                       "altered observation as trusted.")

    return {
        "preset": preset,
        "label": PRESETS[preset],
        "question_id": question_id,
        "source_kind": "post-hoc projection of a recorded benchmark run",
        "original": original,
        "mutated": mutated,
        "reference": evaluate(original),
        "mutated_verdict": evaluate(mutated),
        "mutation": mutation,
        "explanation": explanation,
    }
