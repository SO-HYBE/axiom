"""AXIOM trace-mutation lab.

Runs the monitor on unmutated traces first, then measures what happens under
channel damage and under seeded pipeline faults. Every number in the output is
computed from a real evaluation; an undefined denominator is ``null``, never zero.

Definitions
-----------
``reference verdict``      Monitor verdict on the unmutated trace.
``correct conclusive``     A mutated verdict that is conclusive and equals the
                          reference verdict. Channel damage introduces no new
                          process violation, so a conclusive verdict must not move.
``false conclusive``       A mutated verdict that is conclusive and differs from
                          the reference verdict.
``inconclusive``           UNKNOWN on the mutated trace.
``coverage``               conclusive / cases.
``trustworthy conclusive rate`` correct conclusive / conclusive (null if none).
``false conclusive rate``  false conclusive / cases.
``inconclusive rate``      inconclusive / cases.

Seeded faults are measured separately: the label is fixed by construction, so
``detected`` means the expected property returned FAIL.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .faults import FAULTS, inject
from .monitor import MANDATORY, evaluate
from .mutations import CHANNEL_OPERATORS, describe, apply
from .trace import build_trace

SCHEMA_VERSION = "axiom-trace-lab-v1"


def _rate(numerator, denominator):
    return None if not denominator else round(numerator / denominator, 4)


def _commit(root):
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _jobs(root):
    directory = Path(root) / "runs/benchmarks/3c3cc0f1e4b949a8a33296e94417f13c/jobs"
    return sorted(directory.glob("*.json"))


def load_cases(root):
    """Return one record per recorded job with its trace and reference verdict."""
    cases = []
    for path in _jobs(root):
        record = json.loads(path.read_text(encoding="utf-8"))
        trace = build_trace(record["run"], question_id=record["question_id"])
        cases.append({
            "question_id": record["question_id"],
            "system": record["run"].get("system"),
            "trace": trace,
            "reference": evaluate(trace),
        })
    return cases


def _verdict_map(report):
    return {row["registry"]["id"]: row["verdict"] for row in report["properties"]}


def _empty_counts():
    return {"cases": 0, "correct": 0, "false": 0, "unknown": 0}


def _add_case(bucket, reference, mutated):
    if reference == "UNKNOWN":
        bucket["reference_inconclusive"] = bucket.get("reference_inconclusive", 0) + 1
        return
    bucket["cases"] += 1
    if mutated == "UNKNOWN":
        bucket["unknown"] += 1
    elif mutated == reference:
        bucket["correct"] += 1
    else:
        bucket["false"] += 1


def _finalise(bucket):
    conclusive = bucket["correct"] + bucket["false"]
    cases = bucket["cases"]
    bucket["conclusive"] = conclusive
    bucket["coverage"] = _rate(conclusive, cases)
    bucket["trustworthy_conclusive_rate"] = _rate(bucket["correct"], conclusive)
    bucket["false_conclusive_rate"] = _rate(bucket["false"], cases)
    bucket["inconclusive_rate"] = _rate(bucket["unknown"], cases)
    return bucket


def run_channel_lab(cases, seeds=(0, 1)):
    matrix = {mode: {operator: {pid: _empty_counts() for pid in MANDATORY}
                     for operator in CHANNEL_OPERATORS} for mode in ("on", "off")}
    overall = {mode: _empty_counts() for mode in ("on", "off")}
    records = []
    for case in cases:
        reference = _verdict_map(case["reference"])
        for operator in CHANNEL_OPERATORS:
            for seed in seeds:
                mutated, record = apply(case["trace"], operator, seed)
                if mutated is None:
                    continue
                on = _verdict_map(evaluate(mutated))
                off = _verdict_map(evaluate(mutated, integrity_layer=False))
                for pid in MANDATORY:
                    _add_case(matrix["on"][operator][pid], reference[pid], on[pid])
                    _add_case(matrix["off"][operator][pid], reference[pid], off[pid])
                    _add_case(overall["on"], reference[pid], on[pid])
                    _add_case(overall["off"], reference[pid], off[pid])
                records.append({
                    "case": f"{case['question_id']}-{case['system']}",
                    "operator": operator, "seed": seed,
                    "event_type": record["event_type"],
                    "on": on, "off": off, "reference": reference,
                })
    for mode in matrix.values():
        for operator in mode.values():
            for pid in operator:
                _finalise(operator[pid])
    for bucket in overall.values():
        _finalise(bucket)
    return {"matrix": matrix, "overall": overall, "records": records}


def run_fault_lab(cases):
    summary = {}
    records = []
    for fault, property_id, description in FAULTS:
        bucket = {"expected_property": property_id, "description": description,
                  "attempts": 0, "applicable": 0, "detected": 0, "missed": 0,
                  "expected_unknown": 0, "collateral_failures": 0}
        for case in cases:
            bucket["attempts"] += 1
            faulty, label = inject(case["trace"], fault)
            if faulty is None:
                continue
            bucket["applicable"] += 1
            report = evaluate(faulty)
            verdicts = _verdict_map(report)
            if verdicts[property_id] == "FAIL":
                bucket["detected"] += 1
            elif verdicts[property_id] == "UNKNOWN":
                bucket["expected_unknown"] += 1
            else:
                bucket["missed"] += 1
            others = [pid for pid, verdict in verdicts.items()
                      if verdict == "FAIL" and pid != property_id]
            if others:
                bucket["collateral_failures"] += 1
            records.append({"case": f"{case['question_id']}-{case['system']}", "fault": fault,
                            "expected_property": property_id, "verdicts": verdicts,
                            "aggregate": report["overall"]})
        bucket["detection_rate"] = _rate(bucket["detected"], bucket["applicable"])
        summary[fault] = bucket
    return {"summary": summary, "records": records}


def run(root, seeds=(0, 1)):
    cases = load_cases(root)
    if not cases:
        raise ValueError("No recorded benchmark jobs found; nothing to measure.")
    reference_counts = {}
    for case in cases:
        key = case["reference"]["overall"]
        reference_counts[key] = reference_counts.get(key, 0) + 1
    channel = run_channel_lab(cases, seeds=seeds)
    faults = run_fault_lab(cases)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "commit": _commit(root),
        "dataset": {
            "traces": len(cases),
            "questions": len({case["question_id"] for case in cases}),
            "systems": sorted({case["system"] for case in cases}),
            "reference_overall": reference_counts,
            "source": "runs/benchmarks/3c3cc0f1e4b949a8a33296e94417f13c/jobs",
        },
        "operators": {operator: describe(operator) for operator in CHANNEL_OPERATORS},
        "seeds": list(seeds),
        "channel": channel,
        "faults": faults,
        "definitions": {
            "correct_conclusive": "conclusive mutated verdict equal to the reference verdict",
            "false_conclusive": "conclusive mutated verdict that differs from the reference verdict",
            "inconclusive": "UNKNOWN on the mutated trace",
            "coverage": "conclusive / cases",
            "trustworthy_conclusive_rate": "correct / conclusive (null when no conclusive case)",
            "false_conclusive_rate": "false / cases",
            "inconclusive_rate": "unknown / cases",
            "fault_detection_rate": "detected / applicable seeded faults",
        },
        "limitations": [
            "Channel damage introduces no new process violation; the reference verdict is the ground truth.",
            "Seeded fault labels are fixed by construction and do not come from the monitor.",
            "The content hash detects accidental corruption only. Adversarial rehashing is reported separately.",
            "Timestamps are data only; no property depends on them, so timestamp corruption is expected to stay inconclusive or unchanged.",
            "These numbers describe this corpus of recorded runs and these operators; they are not a claim of immunity to arbitrary mutations.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="Run the AXIOM trace-mutation lab.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--out", type=Path,
                        default=Path("runs/axiom/trace_lab/results.json"))
    parser.add_argument("--seeds", type=int, default=2)
    args = parser.parse_args()
    result = run(args.root, seeds=tuple(range(args.seeds)))
    destination = args.root / args.out
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False),
                           encoding="utf-8")
    summary = {
        "traces": result["dataset"]["traces"],
        "channel_on": {key: result["channel"]["overall"]["on"][key]
                       for key in ("cases", "correct", "false", "unknown",
                                   "trustworthy_conclusive_rate", "false_conclusive_rate")},
        "channel_off": {key: result["channel"]["overall"]["off"][key]
                        for key in ("cases", "correct", "false", "unknown",
                                    "trustworthy_conclusive_rate", "false_conclusive_rate")},
        "faults": {name: row["detection_rate"] for name, row in result["faults"]["summary"].items()},
        "written": str(destination),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
