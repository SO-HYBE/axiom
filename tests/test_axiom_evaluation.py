"""Tests for the offline three-arm evaluation harness.

These tests use a small synthetic recorded run. They check the arithmetic, the
failure exclusion, the null-not-zero rule and the monitor policy guard; the
empirical numbers for the real run live in ``runs/axiom/evaluation/results.json``.
"""
import json
import tempfile
import unittest
from pathlib import Path

from axiom.axiom_evaluation import (_bootstrap_rate, _rate_block, evaluate_arm, load_records, _record,
                                    render_markdown, run)


def _claim(text="a claim", chunk="e1", status=None, applicability=None,
           verdict="model_supported_needs_review", claim_type="source_description"):
    claim = {"text": text, "citations": [{"chunk_id": chunk, "quote": "q", "source_id": "s1"}],
             "claim_type": claim_type}
    if status:
        claim["evidence_status"] = status
    if applicability:
        claim["applicability"] = applicability
    claim["verdict"] = verdict
    return claim


def _run(system, *, abstained=False, claims=(), drafted=None, requested=False):
    return {
        "run_id": f"run-{system}",
        "system": system,
        "question": "q",
        "evidence": [{"chunk_id": "e1", "conditions": {}}],
        "claims": list(claims),
        "draft_checks": list(drafted if drafted is not None else claims),
        "abstained": abstained,
        "answer_status": "insufficient_evidence" if abstained else "model_checked_summary",
        "applicability_requested": requested,
        "target": {},
    }


def _job(path, question_id, system, run_record):
    path.write_text(json.dumps({"question_id": question_id, "system": system,
                                "run": run_record}), encoding="utf-8")


def _fixture(root):
    run_dir = Path(root) / "run"
    (run_dir / "jobs").mkdir(parents=True)
    (run_dir / "manifest.json").write_text(json.dumps({
        "run_id": "run-x", "created_at": "2026-01-01T00:00:00+00:00",
        "status": "completed_with_errors",
        "inputs": {"questions": [
            {"question_id": "Q1", "split": "dev", "category": "answerable",
             "expected_action": "answer", "expected_abstained": False,
             "annotation_status": "ai_draft_unreviewed", "human_reviewer": None},
            {"question_id": "Q2", "split": "test", "category": "insufficient",
             "expected_action": "abstain", "expected_abstained": True,
             "annotation_status": "ai_draft_unreviewed", "human_reviewer": None},
        ]},
    }), encoding="utf-8")
    (run_dir / "failure_hashes.json").write_text(json.dumps({
        "files": [{"file": "Q2--ignis.json", "error": "model call failed"}]
    }), encoding="utf-8")
    _job(run_dir / "jobs/Q1--baseline.json", "Q1", "baseline",
         _run("baseline", claims=[_claim(verdict="unfiltered")]))
    _job(run_dir / "jobs/Q1--rag_only.json", "Q1", "rag_only",
         _run("rag_only", claims=[_claim(verdict="unfiltered")]))
    _job(run_dir / "jobs/Q1--ignis.json", "Q1", "ignis",
         _run("ignis", claims=[_claim(status="supported", applicability="not_assessed")]))
    _job(run_dir / "jobs/Q2--baseline.json", "Q2", "baseline", _run("baseline", abstained=True))
    _job(run_dir / "jobs/Q2--rag_only.json", "Q2", "rag_only", _run("rag_only", abstained=True))
    _job(run_dir / "jobs/Q2--ignis.json", "Q2", "ignis", _run("ignis", abstained=True))
    return run_dir


class RateTests(unittest.TestCase):
    def test_a_zero_denominator_is_null_not_zero(self):
        block = _rate_block(0, 0)
        self.assertIsNone(block["rate"])
        self.assertEqual(block["numerator"], 0)
        self.assertEqual(block["denominator"], 0)

    def test_question_bootstrap_is_seeded_and_reports_denominator(self):
        first = _bootstrap_rate([True, False, True], seed=4, replicates=100)
        second = _bootstrap_rate([True, False, True], seed=4, replicates=100)
        self.assertEqual(first, second)
        self.assertEqual(first["questions"], 3)
        self.assertEqual(first["rate"], 0.6667)
        self.assertLessEqual(first["lower_95"], first["rate"])
        self.assertGreaterEqual(first["upper_95"], first["rate"])


class SyntheticRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.run_dir = _fixture(self.root)
        self.payload = run(self.root, self.run_dir)

    def tearDown(self):
        self.tmp.cleanup()

    def test_execution_failures_are_excluded_and_reported(self):
        ignis = self.payload["arms"]["ignis"]
        self.assertEqual(ignis["scheduled"], 2)
        self.assertEqual(ignis["completed"], 1)
        self.assertEqual(ignis["failed"], 1)
        self.assertEqual(ignis["failure_details"][0]["question_id"], "Q2")
        self.assertEqual(self.payload["dataset"]["completed_jobs"], 5)
        self.assertEqual(self.payload["dataset"]["execution_failures"], 1)

    def test_behaviour_counts_and_expected_action_agreement(self):
        baseline = self.payload["arms"]["baseline"]
        self.assertEqual((baseline["answered"], baseline["abstained"]), (1, 1))
        self.assertEqual(baseline["expected_abstention_agreement"]["rate"], 1.0)
        ignis = self.payload["arms"]["ignis"]
        self.assertEqual((ignis["answered"], ignis["abstained"]), (1, 0))
        self.assertEqual(ignis["expected_abstention_agreement"]["rate"], 1.0)

    def test_claim_retention_is_counted_per_arm(self):
        claims = self.payload["arms"]["ignis"]["claims"]
        self.assertEqual((claims["drafted"], claims["retained"], claims["not_retained"]),
                         (1, 1, 0))
        self.assertEqual(claims["drafted_in_answered_runs"], 1)
        self.assertEqual(claims["retained_verdicts"], {"model_supported_needs_review": 1})

    def test_monitor_separates_verified_from_unverified(self):
        baseline = self.payload["arms"]["baseline"]["monitor"]
        rag = self.payload["arms"]["rag_only"]["monitor"]
        ignis = self.payload["arms"]["ignis"]["monitor"]
        self.assertEqual(baseline["claim_verdicts"], {"PASS": 0, "UNKNOWN": 1, "FAIL": 0})
        self.assertEqual(rag["claim_verdicts"], {"PASS": 0, "UNKNOWN": 1, "FAIL": 0})
        self.assertEqual(ignis["claim_verdicts"], {"PASS": 1, "UNKNOWN": 0, "FAIL": 0})
        self.assertEqual(ignis["published_labels"], {"verified": 0, "unverified": 1,
                                                     "withheld": 0})
        self.assertEqual(ignis["passing_without_verified_label"], 1)
        self.assertEqual(ignis["unsafe_verified_publications"], 0)

    def test_vacuous_passes_are_counted_separately(self):
        baseline = self.payload["arms"]["baseline"]["monitor"]
        self.assertEqual(baseline["vacuous_traces"], 1)
        # The answered baseline run has an unverified claim, so only the
        # abstained run passes, and it passes with no claim in scope.
        self.assertEqual(baseline["trace_verdicts"], {"PASS": 1, "UNKNOWN": 1, "FAIL": 0})

    def test_pairing_uses_only_common_questions(self):
        pair = self.payload["pairs"]["rag_only__ignis"]
        self.assertEqual(pair["paired_questions"], 1)
        self.assertEqual(pair["excluded_from_pairing"]["ignis"], ["Q2"])
        self.assertEqual(pair["outcomes"]["both_answered"], 1)

    def test_correctness_is_null_with_a_reason(self):
        not_measured = self.payload["arms"]["ignis"]["not_measured"]
        for key in ("answer_correctness", "faithfulness", "scientific_validity"):
            self.assertIsNone(not_measured[key])
        self.assertTrue(not_measured["reason"])
        for key in ("claim_evidence_support", "citation_source_correctness",
                    "unsupported_quantitative_claims", "unsupported_generalizations",
                    "applicability_correctness"):
            self.assertIsNone(not_measured[key])

    def test_question_level_intervals_are_present(self):
        interval = self.payload["arms"]["baseline"]["question_level_metrics"]["answer_coverage"]
        self.assertEqual(interval["questions"], 2)
        self.assertEqual(interval["rate"], 0.5)
        self.assertEqual(interval["replicates"], 2000)

    def test_audit_rows_cover_every_scheduled_job(self):
        self.assertEqual(len(self.payload["records"]), 6)
        row = next(row for row in self.payload["records"]
                   if row["question_id"] == "Q2" and row["system"] == "ignis")
        self.assertEqual(row["error"], "model call failed")

    def test_audit_rows_carry_the_observations_needed_by_the_inspector(self):
        row = next(row for row in self.payload["records"]
                   if row["question_id"] == "Q1" and row["system"] == "ignis")
        self.assertTrue(row["claims"])
        self.assertTrue(row["trace_events"])
        self.assertEqual(len(row["property_results"]), 8)
        self.assertIn("flags", row["trust"])
        self.assertEqual(row["trace_manifest"]["event_count"], len(row["trace_events"]))
        self.assertIn("event_ids", row["property_results"][0]["results"][0])

    def test_report_renders_measured_values_and_provenance(self):
        text = render_markdown(self.payload)
        self.assertIn("Results commit:", text)
        self.assertIn("Answer correctness is **not measured**", text)
        self.assertIn("agent-drafted", text)
        self.assertIn("| ignis | 1 | 1 | 0 |", text)


class DanglingCitationTests(unittest.TestCase):
    def test_a_citation_outside_the_retrieved_set_fails_the_claim(self):
        record = _record("Q1", "baseline",
                         _run("baseline", claims=[_claim(chunk="ghost", verdict="unfiltered")]),
                         None)
        self.assertEqual(record["citations"], 1)
        self.assertEqual(record["dangling_citations"], 1)
        self.assertEqual(record["claim_verdicts"], ["FAIL"])

    def test_a_valid_citation_does_not_fail_the_claim(self):
        record = _record("Q1", "baseline",
                         _run("baseline", claims=[_claim(verdict="unfiltered")]), None)
        self.assertEqual(record["dangling_citations"], 0)
        self.assertEqual(record["claim_verdicts"], ["UNKNOWN"])


class FailureHandlingTests(unittest.TestCase):
    def test_a_failure_row_is_not_a_zero_denominator(self):
        questions = {"Q1": {"question_id": "Q1", "category": "answerable",
                            "expected_abstained": False}}
        records = [{"question_id": "Q1", "system": "ignis", "error": "boom",
                    "abstained": True, "applicability_requested": False,
                    "drafted_claims": 0, "retained_claims": 0, "drafted_verdicts": [],
                    "retained_verdicts": [], "cited_claims": 0, "citations": 0,
                    "dangling_citations": 0, "claim_types": [], "applicability": [],
                    "evidence_status": [], "trace_overall": "PASS", "claim_verdicts": [],
                    "published_labels": [], "properties": {}}]
        arm = evaluate_arm(records, questions)
        self.assertEqual(arm["completed"], 0)
        self.assertIsNone(arm["answer_rate"])
        self.assertIsNone(arm["expected_abstention_agreement"]["rate"])
        self.assertIsNone(arm["claims"]["retention_rate"])

    def test_load_records_accepts_the_synthetic_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = _fixture(root)
            records = load_records(run_dir)
            self.assertEqual(len(records), 6)
            self.assertEqual(sum(1 for row in records if row["error"]), 1)


if __name__ == "__main__":
    unittest.main()
