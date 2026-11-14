"""Offline scoring of independently graded saved answers; never an LLM judge."""
from __future__ import annotations

import argparse
import itertools
import json
import math
import re
from pathlib import Path

SYSTEMS = frozenset({"baseline", "rag_only", "ignis"})
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z")


def _key(row: dict) -> tuple[str, str]:
    if not isinstance(row, dict):
        raise ValueError("Each row must be an object")
    qid, system = row.get("question_id"), row.get("system")
    if not isinstance(qid, str) or not _ID.fullmatch(qid):
        raise ValueError("Invalid question_id")
    if not isinstance(system, str) or system not in SYSTEMS:
        raise ValueError(f"system must be one of {sorted(SYSTEMS)}")
    return qid, system


def _bool(value: object, field: str) -> None:
    if type(value) is not bool:
        raise ValueError(f"{field} must be boolean")


def _indexed(rows: list[dict], kind: str) -> dict:
    result = {}
    for row in rows:
        key = _key(row)
        if key in result:
            raise ValueError(f"Duplicate {kind} row {key}")
        result[key] = row
    return result


def _validate_prediction(row: dict) -> None:
    if not isinstance(row.get("answer"), str):
        raise ValueError("answer must be a string")
    _bool(row.get("abstained"), "abstained")
    claims = row.get("claims")
    if not isinstance(claims, list):
        raise ValueError("claims must be a list")
    for claim in claims:
        if not isinstance(claim, dict) or not isinstance(claim.get("text"), str) or not claim["text"].strip():
            raise ValueError("Each claim requires nonempty text")
        if not isinstance(claim.get("verdict"), str):
            raise ValueError("Each claim requires a verdict string; use unreviewed for baseline")
        citations = claim.get("citations")
        if not isinstance(citations, list):
            raise ValueError("citations must be a list")
        for cite in citations:
            if not isinstance(cite, dict) or any(not isinstance(cite.get(f), str) or not cite[f].strip()
                                               for f in ("source_id", "chunk_id", "quote")):
                raise ValueError("Each citation requires source_id, chunk_id and quote")
    for field in ("latency_ms", "cost_usd", "input_tokens", "output_tokens"):
        if field in row:
            value = row[field]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{field} must be finite and nonnegative")


def _validate_grade(grade: dict, prediction: dict) -> None:
    claims = grade.get("claims")
    if not isinstance(claims, list) or len(claims) != len(prediction["claims"]):
        raise ValueError("Grading must contain one claim entry per prediction claim in order")
    for claim in claims:
        if not isinstance(claim, dict):
            raise ValueError("Claim grade must be an object")
        for field in ("supported", "citation_valid", "unsafe_extrapolation"):
            _bool(claim.get(field), field)
    if "correct_abstention" not in grade or grade["correct_abstention"] is not None and type(grade["correct_abstention"]) is not bool:
        raise ValueError("correct_abstention must be boolean or null")


def _rate(numerator: int, denominator: int, unit: str) -> dict:
    return {"value": numerator / denominator if denominator else None,
            "numerator": numerator, "denominator": denominator, "unit": unit}


def _summarize(predictions: list[dict], grades: dict) -> dict:
    graded = [p for p in predictions if _key(p) in grades]
    total_claims = supported = unsafe = cited = valid_cited = 0
    correct = eligible = 0
    for p in graded:
        g = grades[_key(p)]
        for claim, label in zip(p["claims"], g["claims"]):
            total_claims += 1
            supported += label["supported"]
            unsafe += label["unsafe_extrapolation"]
            if claim["citations"]:
                cited += 1
                valid_cited += label["citation_valid"]
        if g["correct_abstention"] is not None:
            eligible += 1
            correct += g["correct_abstention"]
    latency = [p["latency_ms"] for p in predictions if "latency_ms" in p]
    return {
        "predictions": len(predictions), "graded_questions": len(graded),
        "ungraded_questions": len(predictions) - len(graded),
        "graded_zero_claim_questions": sum(not p["claims"] for p in graded),
        "claim_support": _rate(supported, total_claims, "claims"),
        "citation_precision": _rate(valid_cited, cited, "cited_claims"),
        "citation_coverage": _rate(cited, total_claims, "claims"),
        "unsafe_extrapolation": _rate(unsafe, total_claims, "claims"),
        "abstention_accuracy": _rate(correct, eligible, "questions_with_abstention_grade"),
        "answer_coverage": _rate(sum(not p["abstained"] for p in predictions), len(predictions), "predictions"),
        "mean_latency_ms": sum(latency) / len(latency) if latency else None,
        "latency_observations": len(latency),
    }


def evaluate(predictions: list[dict], annotations: list[dict]) -> dict:
    """Reject malformed/duplicate/orphan records; exclude missing labels from quality scores.

    Annotation claims align by position with an independently audited atomic-claim
    list. This function cannot verify the truth, completeness, or independence of
    those labels. A zero denominator is null, never a perfect score.
    """
    pmap = _indexed(predictions, "prediction")
    amap = _indexed(annotations, "annotation")
    for p in predictions:
        _validate_prediction(p)
    for key, a in amap.items():
        if key not in pmap:
            raise ValueError(f"Annotation has no prediction: {key}")
        _validate_grade(a, pmap[key])
    systems = {s: _summarize([p for p in predictions if p["system"] == s], amap)
               for s in sorted({p["system"] for p in predictions})}
    paired = {}
    for left, right in itertools.combinations(systems, 2):
        common = sorted({q for q, s in amap if s == left} & {q for q, s in amap if s == right})
        summaries = {s: _summarize([pmap[q, s] for q in common], amap) for s in (left, right)}
        delta = {}
        for metric in ("claim_support", "citation_precision", "unsafe_extrapolation", "abstention_accuracy", "answer_coverage"):
            a, b = (summaries[s][metric]["value"] for s in (left, right))
            delta[metric] = b - a if a is not None and b is not None else None
        paired[f"{left}__{right}"] = {"question_ids": common, "paired_questions": len(common),
                                          "systems": summaries, "delta_right_minus_left": delta}
    return {"schema_version": "1.0", "evaluation_kind": "independent_annotation_scoring",
            "is_scientific_validation": False, "systems": systems, "paired": paired,
            "limitations": ["Labels are supplied, not independently verified by this evaluator.",
                            "Citation precision is per cited claim, not per citation.",
                            "Paired deltas pool claims; report counts and inspect question-level failures.",
                            "No significance or safety certification follows from these scores."]}


def load_jsonl(path: str | Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("predictions", type=Path)
    parser.add_argument("annotations", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = json.dumps(evaluate(load_jsonl(args.predictions), load_jsonl(args.annotations)), indent=2, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result + "\n", encoding="utf-8")
    else:
        print(result)


if __name__ == "__main__":
    main()
