"""Offline evaluation of a recorded three-arm AXIOM benchmark run.

The three arms are a plain model (``baseline``), retrieval with a shared saved
draft (``rag_only``) and the same draft with the critic, applicability layer and
runtime monitor (``ignis``). RAG-only and AXIOM share one draft when both arms
are selected, so the comparison isolates verification and withholding rather
than the drafting model.

What this module measures
-------------------------
Everything here is computed from a recorded run and from the deterministic
monitor. No language model decides a number.

``behaviour``      answered/abstained counts against the recorded expected action.
``claims``         drafted versus retained claims, citations and dangling citations.
``monitor``        trace and claim verdicts, published labels, property verdicts.
``applicability``  whether a documented-scope assessment was requested or made.

What it deliberately does not measure
-------------------------------------
Answer correctness, faithfulness or scientific validity. The per-question
rubrics in the manifest are unreviewed agent drafts, and no human reviewer has
scored the answers. A deterministic scorer cannot read a prose rubric, and
inventing a score would be fabrication. Those columns are reported as ``null``
with the reason, never as zero.

Provenance
----------
Question expectations are labelled ``agent-drafted`` (the manifest records
``annotation_status = ai_draft_unreviewed`` with no human reviewer). Monitor
verdicts and all counts are ``automatic``. The assistant is not the reviewer.
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .monitor import MANDATORY, evaluate
from .trace import build_trace

SCHEMA_VERSION = "axiom-evaluation-v1"
SYSTEMS = ("baseline", "rag_only", "ignis")
ARM_LABELS = {
    "baseline": "model without retrieval",
    "rag_only": "retrieval with a shared saved draft, no verification stage",
    "ignis": "same draft plus critic, applicability layer and runtime monitor",
}
CATEGORIES = ("answerable", "insufficient", "extrapolation", "citation_trap", "uncertainty")
DEFAULT_RUN = "runs/benchmarks/3c3cc0f1e4b949a8a33296e94417f13c"


def _rate(numerator, denominator):
    return None if not denominator else round(numerator / denominator, 4)


def _rate_block(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "rate": _rate(numerator, denominator)}


def _bootstrap_rate(values, seed=20261113, replicates=2000):
    """Percentile interval for question-level binary outcomes; null if undefined."""
    values = list(values)
    point = _rate(sum(values), len(values))
    if not values:
        return {"rate": None, "lower_95": None, "upper_95": None,
                "questions": 0, "seed": seed, "replicates": replicates}
    rng = random.Random(seed)
    samples = sorted(_rate(sum(rng.choice(values) for _ in values), len(values))
                     for _ in range(replicates))
    lower = samples[int(0.025 * (replicates - 1))]
    upper = samples[int(0.975 * (replicates - 1))]
    return {"rate": point, "lower_95": lower, "upper_95": upper,
            "questions": len(values), "seed": seed, "replicates": replicates}


def _commit(root):
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _manifest(run_dir):
    return json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))


def load_questions(run_dir):
    """Return the recorded question table keyed by question id."""
    manifest = _manifest(run_dir)
    rows = manifest.get("inputs", {}).get("questions") or []
    questions = {}
    for row in rows:
        questions[row["question_id"]] = {
            "question_id": row["question_id"],
            "split": row.get("split"),
            "category": row.get("category"),
            "expected_action": row.get("expected_action"),
            "expected_abstained": row.get("expected_abstained"),
            "annotation_status": row.get("annotation_status"),
            "human_reviewer": row.get("human_reviewer"),
        }
    if not questions:
        raise ValueError("The recorded run has no question table; nothing to evaluate.")
    return questions


def load_failures(run_dir):
    """Return execution failures keyed by (question_id, system).

    A failed execution is excluded from behavioural and claim denominators. It
    is still listed, because an evaluation that silently drops failures is not
    honest about coverage.
    """
    path = run_dir / "failure_hashes.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    failures = {}
    for row in payload.get("files") or []:
        name = str(row.get("file") or "")
        if "--" not in name:
            continue
        question_id, system = name.split("--", 1)
        failures[(question_id, system.removesuffix(".json"))] = row.get("error") or "unknown"
    return failures


def _citation_chunk_ids(claim):
    return [citation.get("chunk_id") for citation in claim.get("citations") or []
            if citation.get("chunk_id")]


def _record(question_id, system, run, failure):
    """Project one recorded job into the flat record the metrics consume."""
    trace = build_trace(run, question_id=question_id)
    report = evaluate(trace)
    evidence_ids = {row.get("chunk_id") for row in run.get("evidence") or []
                    if row.get("chunk_id")}
    retained = run.get("claims") or []
    drafted = run.get("draft_checks") or []
    citations = [citation for claim in retained for citation in claim.get("citations") or []]
    dangling = [citation.get("chunk_id") for citation in citations
                if citation.get("chunk_id") not in evidence_ids]
    labels = [event.get("label") for event in trace["events"]
              if event["type"] == "CLAIM_PUBLISHED"]
    properties = {row["registry"]["id"]: row["verdict"] for row in report["properties"]}
    claim_verdicts = [row["verdict"] for row in report["claims"].values()]
    return {
        "question_id": question_id,
        "system": system,
        "error": failure,
        "abstained": run.get("abstained"),
        "answer_status": run.get("answer_status"),
        "applicability_requested": bool(run.get("applicability_requested")),
        "drafted_claims": len(drafted),
        "retained_claims": len(retained),
        "drafted_verdicts": [claim.get("verdict") for claim in drafted if claim.get("verdict")],
        "retained_verdicts": [claim.get("verdict") for claim in retained if claim.get("verdict")],
        "cited_claims": sum(1 for claim in retained if _citation_chunk_ids(claim)),
        "citations": len(citations),
        "dangling_citations": len(dangling),
        "claim_types": [claim.get("claim_type") for claim in retained],
        "applicability": [claim.get("applicability") or "not_assessed" for claim in retained],
        "evidence_status": [claim.get("evidence_status") for claim in retained],
        "trace_overall": report["overall"],
        "claim_verdicts": claim_verdicts,
        "published_labels": labels,
        "properties": properties,
        "property_results": report["properties"],
        "trust": report["trust"],
        "trace_events": trace["events"],
        "trace_manifest": trace["manifest"],
        "claims": [
            {"claim_id": f"{question_id}-c{index + 1}",
             "text": claim.get("text"),
             "citations": claim.get("citations") or [],
             "evidence_status": claim.get("evidence_status"),
             "applicability": claim.get("applicability") or "not_assessed",
             "evidence_ids": sorted(set(_citation_chunk_ids(claim))),
             "target_conditions": run.get("target") or {},
             "evidence_conditions": [
                 {"chunk_id": evidence.get("chunk_id"),
                  "conditions": evidence.get("conditions") or {}}
                 for evidence in run.get("evidence") or []
                 if evidence.get("chunk_id") in _citation_chunk_ids(claim)
             ]}
            for index, claim in enumerate(run.get("claims") or [])
        ],
    }


def load_records(run_dir):
    records = []
    failures = load_failures(run_dir)
    for path in sorted((run_dir / "jobs").glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        question_id, system = payload["question_id"], payload["system"]
        failure = failures.get((question_id, system))
        records.append(_record(question_id, system, payload["run"], failure))
    if not records:
        raise ValueError("No recorded jobs found; nothing to measure.")
    return records


def evaluate_arm(records, questions):
    """Aggregate one arm. Records with an ``error`` are excluded from denominators."""
    completed = [row for row in records if not row["error"]]
    failed = [row for row in records if row["error"]]
    answered = [row for row in completed if not row["abstained"]]
    abstained = [row for row in completed if row["abstained"]]
    agreement = [(row, questions[row["question_id"]]) for row in completed
                 if isinstance(questions[row["question_id"]].get("expected_abstained"), bool)]
    agree = sum(1 for row, question in agreement
                if bool(row["abstained"]) == question["expected_abstained"])
    expected_rows = [row for row, question in agreement]
    question_metrics = {
        "answer_coverage": _bootstrap_rate([not row["abstained"] for row in completed]),
        "abstention_rate": _bootstrap_rate([bool(row["abstained"]) for row in completed]),
        "expected_abstention_agreement": _bootstrap_rate([
            bool(row["abstained"]) == questions[row["question_id"]]["expected_abstained"]
            for row in expected_rows]),
    }

    by_category = {}
    for category in CATEGORIES:
        rows = [row for row in completed
                if questions[row["question_id"]].get("category") == category]
        correct = sum(1 for row in rows
                      if isinstance(questions[row["question_id"]].get("expected_abstained"), bool)
                      and bool(row["abstained"])
                      == questions[row["question_id"]]["expected_abstained"])
        eligible = sum(1 for row in rows
                       if isinstance(questions[row["question_id"]].get("expected_abstained"), bool))
        by_category[category] = {
            "completed": len(rows),
            "answered": sum(1 for row in rows if not row["abstained"]),
            "abstained": sum(1 for row in rows if row["abstained"]),
            "expected_abstention_agreement": _rate_block(correct, eligible),
        }

    property_verdicts = {pid: {"PASS": 0, "UNKNOWN": 0, "FAIL": 0} for pid in MANDATORY}
    for row in completed:
        for pid, verdict in row["properties"].items():
            property_verdicts[pid][verdict] += 1

    claim_verdicts = {"PASS": 0, "UNKNOWN": 0, "FAIL": 0}
    for row in completed:
        for verdict in row["claim_verdicts"]:
            claim_verdicts[verdict] += 1

    labels = {"verified": 0, "unverified": 0, "withheld": 0}
    for row in completed:
        for label in row["published_labels"]:
            labels[label] = labels.get(label, 0) + 1

    # A verified publication resting on a claim the monitor did not pass would be
    # an unsafe upgrade. It must be zero; the count is measured rather than assumed.
    unsafe_publications = 0
    passing_without_verified_label = 0
    for row in completed:
        verdicts = row["claim_verdicts"]
        if "FAIL" in verdicts:
            unsafe_publications += row["published_labels"].count("verified")
        if "PASS" in verdicts:
            passing_without_verified_label += sum(
                1 for label in row["published_labels"] if label != "verified")

    trace_verdicts = {"PASS": 0, "UNKNOWN": 0, "FAIL": 0}
    vacuous = 0
    for row in completed:
        trace_verdicts[row["trace_overall"]] += 1
        if not row["claim_verdicts"]:
            vacuous += 1

    applicability = {}
    for row in completed:
        for status in row["applicability"]:
            applicability[status] = applicability.get(status, 0) + 1

    requested = [row for row in completed if row["applicability_requested"]]
    claim_types = {}
    for row in completed:
        for claim_type in row["claim_types"]:
            if claim_type:
                claim_types[claim_type] = claim_types.get(claim_type, 0) + 1
    evidence_status = {}
    for row in completed:
        for status in row["evidence_status"]:
            if status:
                evidence_status[status] = evidence_status.get(status, 0) + 1
    drafted_verdicts = {}
    for row in completed:
        for verdict in row["drafted_verdicts"]:
            drafted_verdicts[verdict] = drafted_verdicts.get(verdict, 0) + 1
    retained_verdicts = {}
    for row in completed:
        for verdict in row["retained_verdicts"]:
            retained_verdicts[verdict] = retained_verdicts.get(verdict, 0) + 1

    return {
        "scheduled": len(records),
        "completed": len(completed),
        "failed": len(failed),
        "failure_details": [{"question_id": row["question_id"], "error": row["error"]}
                            for row in sorted(failed, key=lambda row: row["question_id"])],
        "answered": len(answered),
        "abstained": len(abstained),
        "answer_rate": _rate(len(answered), len(completed)),
        "abstention_rate": _rate(len(abstained), len(completed)),
        "expected_abstention_agreement": {
            **_rate_block(agree, len(agreement)),
            "label_provenance": "agent-drafted",
            "definition": ("answers whose observed abstention matches the recorded "
                           "expected_abstained flag"),
        },
        "question_level_metrics": question_metrics,
        "by_category": by_category,
        "claims": {
            "drafted": sum(row["drafted_claims"] for row in completed),
            "drafted_in_answered_runs": sum(row["drafted_claims"] for row in answered),
            "drafted_in_abstained_runs": sum(row["drafted_claims"] for row in abstained),
            "retained": sum(row["retained_claims"] for row in completed),
            "not_retained": sum(row["drafted_claims"] - row["retained_claims"]
                                for row in completed),
            "retention_rate": _rate(sum(row["retained_claims"] for row in completed),
                                    sum(row["drafted_claims"] for row in completed)),
            "retention_rate_in_answered_runs": _rate(
                sum(row["retained_claims"] for row in answered),
                sum(row["drafted_claims"] for row in answered)),
            "cited": sum(row["cited_claims"] for row in completed),
            "citations": sum(row["citations"] for row in completed),
            "dangling_citations": sum(row["dangling_citations"] for row in completed),
            "claim_types": dict(sorted(claim_types.items())),
            "evidence_status": dict(sorted(evidence_status.items())),
            "drafted_verdicts": dict(sorted(drafted_verdicts.items())),
            "retained_verdicts": dict(sorted(retained_verdicts.items())),
        },
        "monitor": {
            "traces_evaluated": len(completed),
            "vacuous_traces": vacuous,
            "trace_verdicts": trace_verdicts,
            "claim_verdicts": claim_verdicts,
            "published_labels": labels,
            "unsafe_verified_publications": unsafe_publications,
            "passing_without_verified_label": passing_without_verified_label,
            "property_verdicts": property_verdicts,
        },
        "applicability": {
            "runs_requesting_assessment": len(requested),
            "runs_requesting_assessment_answered": sum(1 for row in requested
                                                       if not row["abstained"]),
            "claims_assessed": sum(count for status, count in applicability.items()
                                   if status != "not_assessed"),
            "claims_by_outcome": dict(sorted(applicability.items())),
        },
        "not_measured": {
            "answer_correctness": None,
            "faithfulness": None,
            "scientific_validity": None,
            "claim_evidence_support": None,
            "citation_source_correctness": None,
            "unsupported_quantitative_claims": None,
            "unsupported_generalizations": None,
            "applicability_correctness": None,
            "reason": ("The manifest rubrics are unreviewed agent drafts and no human reviewer "
                       "scored the answers. A deterministic scorer cannot read a prose rubric, "
                       "so no semantic claim-quality or correctness score is produced. Citation "
                       "resolution is counted mechanically, but resolution does not establish "
                       "that a source supports a claim."),
            "denominator": None,
        },
    }


def _pair(records, questions, left, right):
    """Compare two arms on questions both completed. Counts only; no p-values."""
    by_arm = {system: {row["question_id"]: row for row in records
                       if row["system"] == system and not row["error"]}
              for system in (left, right)}
    common = sorted(set(by_arm[left]) & set(by_arm[right]))
    both_answered = [qid for qid in common
                     if not by_arm[left][qid]["abstained"] and not by_arm[right][qid]["abstained"]]
    only_left = [qid for qid in common
                 if not by_arm[left][qid]["abstained"] and by_arm[right][qid]["abstained"]]
    only_right = [qid for qid in common
                  if by_arm[left][qid]["abstained"] and not by_arm[right][qid]["abstained"]]
    both_abstained = [qid for qid in common
                      if by_arm[left][qid]["abstained"] and by_arm[right][qid]["abstained"]]

    def agreement(system):
        eligible = [qid for qid in common
                    if isinstance(questions[qid].get("expected_abstained"), bool)]
        correct = sum(1 for qid in eligible
                      if bool(by_arm[system][qid]["abstained"])
                      == questions[qid]["expected_abstained"])
        return _rate_block(correct, len(eligible))

    return {
        "left": left,
        "right": right,
        "paired_questions": len(common),
        "excluded_from_pairing": {system: sorted(set(questions) - set(by_arm[system]))
                                  for system in (left, right)},
        "outcomes": {
            "both_answered": len(both_answered),
            "both_abstained": len(both_abstained),
            f"only_{left}_answered": len(only_left),
            f"only_{right}_answered": len(only_right),
        },
        "only_left_answered_ids": only_left,
        "only_right_answered_ids": only_right,
        "only_left_answered_details": [
            {"question_id": qid, "category": questions[qid].get("category"),
             "expected_action": questions[qid].get("expected_action")} for qid in only_left],
        "only_right_answered_details": [
            {"question_id": qid, "category": questions[qid].get("category"),
             "expected_action": questions[qid].get("expected_action")} for qid in only_right],
        "answered": {system: sum(1 for qid in common if not by_arm[system][qid]["abstained"])
                     for system in (left, right)},
        "retained_claims": {system: sum(by_arm[system][qid]["retained_claims"]
                                        for qid in common)
                            for system in (left, right)},
        "expected_abstention_agreement": {system: agreement(system)
                                          for system in (left, right)},
        "note": ("Counts over paired questions only. No significance test is reported: "
                 "36 questions are not independent evidence of a population effect."),
    }


def _dataset(run_dir, questions, records):
    manifest = _manifest(run_dir)
    failures = load_failures(run_dir)
    splits = {}
    for question in questions.values():
        splits[question.get("split")] = splits.get(question.get("split"), 0) + 1
    return {
        "run_id": manifest.get("run_id"),
        "recorded_at": manifest.get("created_at"),
        "run_status": manifest.get("status"),
        "source": str(run_dir).replace("\\", "/"),
        "questions": len(questions),
        "systems": sorted({row["system"] for row in records}),
        "scheduled_jobs": len(records),
        "completed_jobs": len(records) - len(failures),
        "execution_failures": len(failures),
        "splits": dict(sorted(splits.items())),
        "categories": {category: sum(1 for question in questions.values()
                                     if question.get("category") == category)
                       for category in CATEGORIES},
    }


def _audit_records(records, questions):
    """One compact row per job, so a reader can check every aggregate by hand."""
    rows = []
    for row in sorted(records, key=lambda row: (row["question_id"], row["system"])):
        question = questions[row["question_id"]]
        rows.append({
            "question_id": row["question_id"],
            "system": row["system"],
            "split": question.get("split"),
            "category": question.get("category"),
            "expected_action": question.get("expected_action"),
            "expected_abstained": question.get("expected_abstained"),
            "error": row["error"],
            "abstained": row["abstained"],
            "drafted_claims": row["drafted_claims"],
            "retained_claims": row["retained_claims"],
            "dangling_citations": row["dangling_citations"],
            "trace_overall": row["trace_overall"],
            "claim_verdicts": row["claim_verdicts"],
            "published_labels": row["published_labels"],
            "claims": row["claims"],
            "trace_events": row["trace_events"],
            "property_results": row["property_results"],
            "trust": row["trust"],
            "trace_manifest": row["trace_manifest"],
        })
    return rows


def run(root, run_dir=None):
    run_dir = Path(run_dir or root / DEFAULT_RUN)
    questions = load_questions(run_dir)
    records = load_records(run_dir)
    arms = {}
    for system in SYSTEMS:
        rows = [row for row in records if row["system"] == system]
        if rows:
            arms[system] = evaluate_arm(rows, questions)
    pairs = {
        "baseline__rag_only": _pair(records, questions, "baseline", "rag_only"),
        "rag_only__ignis": _pair(records, questions, "rag_only", "ignis"),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "commit": _commit(root),
        "dataset": _dataset(run_dir, questions, records),
        "arms": arms,
        "arm_labels": ARM_LABELS,
        "pairs": pairs,
        "records": _audit_records(records, questions),
        "provenance": {
            "question_expectations": "agent-drafted",
            "question_expectation_source": "manifest.inputs.questions (ai_draft_unreviewed)",
            "human_reviewer": None,
            "metrics": "automatic",
            "monitor_verdicts": "automatic",
            "method": ("Built from the recorded jobs. Each job is projected with "
                       "trace.build_trace and evaluated with monitor.evaluate; no language "
                       "model produces or adjusts a metric."),
        },
        "definitions": {
            "answered": "completed execution with abstained = false",
            "expected_abstention_agreement": "observed abstention equals the recorded expected_abstained flag",
            "retained_claim": "claim present in the recorded run's final claim list",
            "not_retained": "drafted claim absent from the final claim list",
            "dangling_citation": "citation chunk id absent from the run's retrieved evidence",
            "vacuous_trace": "trace with no claim in scope, so the run verdict is PASS by default",
            "claim_verdict": "worst property verdict for the claim, including run-level P1 and P7",
            "unsafe_verified_publication": "a verified publication on a trace with a failing claim verdict",
            "passing_without_verified_label": "a claim verdict PASS while its publication label is not verified",
        },
        "limitations": [
            "The run is recorded, not fresh. A fresh three-arm run needs provider API keys that are not present in this environment.",
            "RAG-only and AXIOM share one saved draft; the comparison isolates verification and withholding, not the drafting model.",
            "Answer correctness and faithfulness are not measured: the rubrics are unreviewed agent drafts and no human reviewer scored the answers.",
            "Expected-action agreement uses unreviewed agent-drafted labels, so it is a behavioural check, not ground truth.",
            "Traces are post-hoc projections and do not record model-call failures. A failed execution with no claim is a vacuous PASS, so such runs are excluded from behavioural denominators and counted separately.",
            "No claim carries a verified label on this run: the pipeline made no documented-scope assessment, and the monitor does not upgrade a label on its own.",
            "36 questions from one corpus of 12 documents are not a sample that supports a significance or generalisation claim.",
            "Bootstrap intervals are descriptive question-resampling intervals for answer coverage, abstention and agreement with unreviewed draft labels; they do not establish accuracy or a population effect.",
        ],
    }


def _percent(block):
    if block.get("rate") is None:
        return "null"
    return f"{block['rate']:.4f}"


def render_markdown(payload):
    """Render the measured payload. Every number comes from ``payload``."""
    dataset = payload["dataset"]
    lines = ["# AXIOM three-arm evaluation", "",
             f"Results commit: `{payload['commit']}`  ",
             f"Run at: {payload['generated_at']}  ",
             f"Recorded benchmark run: `{dataset['run_id']}` ({dataset['recorded_at']})  ",
             f"Dataset: {dataset['questions']} questions, {dataset['scheduled_jobs']} jobs, "
             f"{dataset['completed_jobs']} completed, {dataset['execution_failures']} execution failures.",
             ""]
    lines += ["**Provenance.** Question expectations are agent-drafted and unreviewed "
              "(`ai_draft_unreviewed`, no human reviewer). Monitor verdicts and metrics are "
              "automatic. Answer correctness is **not measured**.", ""]
    lines += ["## Arms", "",
              "| Arm | Completed | Answered | Abstained | Expected-abstention agreement | "
              "Drafted claims | Retained claims | Dangling citations |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for system, arm in payload["arms"].items():
        lines.append(f"| {system} | {arm['completed']} | {arm['answered']} | {arm['abstained']} | "
                     f"{_percent(arm['expected_abstention_agreement'])} | "
                     f"{arm['claims']['drafted']} | {arm['claims']['retained']} | "
                     f"{arm['claims']['dangling_citations']} |")
    lines += ["", "## Claim retention", "",
              "| Arm | Drafted in answered runs | Drafted in abstained runs | Retained | "
              "Retention in answered runs | Drafted but not retained |",
              "| --- | --- | --- | --- | --- | --- |"]
    for system, arm in payload["arms"].items():
        claims = arm["claims"]
        lines.append(f"| {system} | {claims['drafted_in_answered_runs']} | "
                     f"{claims['drafted_in_abstained_runs']} | {claims['retained']} | "
                     f"{_percent({'rate': claims['retention_rate_in_answered_runs']})} | "
                     f"{claims['not_retained']} |")
    lines += ["", "A drafted claim is not retained when the run abstains or when the critic does "
              "not clear it. Retention is a run-level decision, so a supported draft can be lost "
              "with an abstained answer.", ""]
    lines += ["## Question-level metrics", "",
              "Intervals are 95% percentile intervals from 2,000 seeded question bootstrap resamples. "
              "Agreement is against unreviewed agent-drafted expectations.", "",
              "| Arm | Answer coverage (95% CI) | Abstention rate (95% CI) | Draft-label agreement (95% CI) |",
              "| --- | --- | --- | --- |"]
    for system, arm in payload["arms"].items():
        metrics = arm["question_level_metrics"]
        def interval(value):
            if value["rate"] is None:
                return "null"
            return f"{value['rate']:.4f} ({value['lower_95']:.4f}–{value['upper_95']:.4f}; n={value['questions']})"
        lines.append(f"| {system} | {interval(metrics['answer_coverage'])} | "
                     f"{interval(metrics['abstention_rate'])} | "
                     f"{interval(metrics['expected_abstention_agreement'])} |")
    lines += ["", "Semantic evidence support, source correctness, unsupported quantitative claims, "
              "unsupported generalizations and applicability correctness are not measured because "
              "no independent claim-level annotations exist. Mechanical dangling-citation counts "
              "only check that citation IDs occur in retrieved evidence.", ""]
    lines += ["## Monitor outcomes", "",
              "| Arm | Vacuous traces | Trace PASS/UNKNOWN/FAIL | Claim PASS/UNKNOWN/FAIL | "
              "Published verified/unverified | Unsafe verified publications |",
              "| --- | --- | --- | --- | --- | --- |"]
    for system, arm in payload["arms"].items():
        monitor = arm["monitor"]
        trace = monitor["trace_verdicts"]
        claim = monitor["claim_verdicts"]
        labels = monitor["published_labels"]
        lines.append(
            f"| {system} | {monitor['vacuous_traces']} | "
            f"{trace['PASS']}/{trace['UNKNOWN']}/{trace['FAIL']} | "
            f"{claim['PASS']}/{claim['UNKNOWN']}/{claim['FAIL']} | "
            f"{labels.get('verified', 0)}/{labels.get('unverified', 0)} | "
            f"{monitor['unsafe_verified_publications']} |")
    lines += ["", "A vacuous trace has no claim in scope, so its PASS is not evidence that "
              "anything was verified. The two failed AXIOM executions are excluded from the "
              "completed denominators and are listed in the results JSON. A run-level property "
              "failure (P1, P7) applies to every claim in that run, which is why one dangling "
              "citation can fail more than one claim.", ""]
    ignis = payload["arms"].get("ignis")
    if ignis:
        monitor = ignis["monitor"]
        lines += [
            f"- AXIOM: {monitor['claim_verdicts']['PASS']} claims pass every process property, "
            f"{monitor['published_labels'].get('verified', 0)} carry a verified label and "
            f"{monitor['passing_without_verified_label']} passing claims stay explicitly unverified. "
            "A verified label additionally requires a `WITHIN_DOCUMENTED_SCOPE` assessment, which "
            "this run never made, so the monitor does not upgrade the label on its own.",
            f"- AXIOM requested an applicability assessment on "
            f"{ignis['applicability']['runs_requesting_assessment']} completed runs and answered "
            f"{ignis['applicability']['runs_requesting_assessment_answered']} of them.",
        ]
    rag = payload["arms"].get("rag_only")
    if rag:
        lines.append(f"- RAG-only: {rag['monitor']['claim_verdicts']['UNKNOWN']} claims are UNKNOWN "
                     "because there is no verification stage; the monitor cannot certify them, so "
                     "they stay unverified rather than being called correct.")
    baseline = payload["arms"].get("baseline")
    if baseline:
        lines.append(f"- Baseline: {baseline['monitor']['claim_verdicts']['FAIL']} claim verdicts "
                     f"FAIL and {baseline['claims']['dangling_citations']} citation(s) are dangling.")
    lines += [""]
    lines += ["## Paired comparison", "",
              "| Pair | Paired questions | Both answered | Both abstained | Only left answered | "
              "Only right answered |",
              "| --- | --- | --- | --- | --- | --- |"]
    for name, pair in payload["pairs"].items():
        outcomes = pair["outcomes"]
        left, right = pair["left"], pair["right"]
        lines.append(f"| {name} | {pair['paired_questions']} | {outcomes['both_answered']} | "
                     f"{outcomes['both_abstained']} | {outcomes[f'only_{left}_answered']} | "
                     f"{outcomes[f'only_{right}_answered']} |")
    lines += ["", "Counts only. No significance test is reported.", ""]
    for name, pair in payload["pairs"].items():
        left, right = pair["left"], pair["right"]
        if pair["only_right_answered_details"]:
            detail = ", ".join(f"{row['question_id']} ({row['category']})"
                               for row in pair["only_right_answered_details"])
            lines.append(f"- `{right}` answered and `{left}` abstained: {detail}.")
        if pair["only_left_answered_details"]:
            detail = ", ".join(f"{row['question_id']} ({row['category']})"
                               for row in pair["only_left_answered_details"])
            lines.append(f"- `{left}` answered and `{right}` abstained: {detail}.")
    lines += [""]
    lines += ["## What the monitor did not verify", ""]
    lines += [f"- {item}" for item in payload["limitations"]]
    lines += ["", "## Provenance", "",
              f"- Question expectations: {payload['provenance']['question_expectations']} "
              f"({payload['provenance']['question_expectation_source']})",
              f"- Human reviewer: {payload['provenance']['human_reviewer']}",
              f"- Metrics and monitor verdicts: {payload['provenance']['metrics']}", ""]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Evaluate an AXIOM three-arm benchmark run.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--run", type=Path, default=None)
    parser.add_argument("--out", type=Path,
                        default=Path("runs/axiom/evaluation/results.json"))
    parser.add_argument("--report", type=Path,
                        default=Path("runs/axiom/evaluation/REPORT.md"))
    args = parser.parse_args()
    payload = run(args.root, args.run)
    destination = args.root / args.out
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False),
                           encoding="utf-8")
    report = args.root / args.report
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_markdown(payload), encoding="utf-8")
    summary = {
        system: {
            "completed": arm["completed"],
            "answered": arm["answered"],
            "abstained": arm["abstained"],
            "expected_abstention_agreement": arm["expected_abstention_agreement"]["rate"],
            "retained_claims": arm["claims"]["retained"],
            "trace_verdicts": arm["monitor"]["trace_verdicts"],
            "claim_verdicts": arm["monitor"]["claim_verdicts"],
            "published_labels": arm["monitor"]["published_labels"],
        }
        for system, arm in payload["arms"].items()
    }
    print(json.dumps(summary, indent=2))
    print(json.dumps({"written": str(destination), "report": str(report)}, indent=2))


if __name__ == "__main__":
    main()
