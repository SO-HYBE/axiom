"""Synthetic report fixtures only; these tests establish no scientific results."""
import copy
import unittest
from unittest.mock import patch

from axiom.benchmark_report import summarize_benchmark


def job(q="fixture-1", system="ignis", split="dev"):
    return {"question_id": q, "system": system, "split": split}


def prediction(q="fixture-1", system="ignis", **extras):
    return {"question_id": q, "system": system, "answer": "Synthetic fixture answer.",
            "abstained": False, "claims": [{"text": "Synthetic fixture claim.",
            "citations": [{"source_id": "fixture", "chunk_id": "fixture-1", "quote": "fixture"}],
            "verdict": "supported"}], **extras}


def grade(q="fixture-1", system="ignis", supported=True):
    return {"question_id": q, "system": system, "claims": [{"supported": supported,
            "citation_valid": True, "unsafe_extrapolation": False}], "correct_abstention": True}


class BenchmarkReportTests(unittest.TestCase):
    def test_critic_verdict_and_ai_labels_are_never_grades(self):
        manifest = {"jobs": [job()], "expected_abstained": False}
        report = summarize_benchmark(manifest, [prediction(expected_abstained=False)])
        metrics = report["quality"]["systems"]["ignis"]
        for field in ("claim_support", "citation_precision", "unsafe_extrapolation", "abstention_accuracy"):
            self.assertIsNone(metrics[field]["value"])
        self.assertEqual(report["progress"]["overall"]["ungraded"], 1)
        self.assertFalse(report["is_scientific_validation"])

    def test_failures_pending_and_success_have_distinct_denominators(self):
        manifest = {"jobs": [job("fixture-1"), job("fixture-2"), job("fixture-3"), job("fixture-4")]}
        rows = [prediction(), prediction("fixture-2", abstained=True, claims=[], answer=""),
                {"question_id": "fixture-3", "system": "ignis", "execution_error": "Synthetic timeout"}]
        report = summarize_benchmark(manifest, rows)
        p = report["progress"]["overall"]
        self.assertEqual({k: p[k] for k in ("scheduled", "completed", "failed", "pending", "attempted")},
                         {"scheduled": 4, "completed": 2, "failed": 1, "pending": 1, "attempted": 3})
        self.assertEqual(p["answer_coverage"], {"value": .5, "numerator": 1, "denominator": 2})
        self.assertEqual(p["scheduled_answer_coverage"]["value"], .25)
        self.assertEqual(p["failed_jobs"], [{"question_id": "fixture-3", "system": "ignis"}])
        self.assertEqual(report["quality"]["systems"]["ignis"]["predictions"], 2)

    def test_failed_annotations_excluded_and_independent_grades_used(self):
        rows = [prediction(), prediction("fixture-2", error="Synthetic failure")]
        report = summarize_benchmark({"jobs": [job(), job("fixture-2")]}, rows,
                                     [grade(supported=False), grade("fixture-2")])
        self.assertEqual(report["excluded_failure_annotations"], 1)
        self.assertEqual(report["quality"]["systems"]["ignis"]["claim_support"]["value"], 0)
        self.assertEqual(report["progress"]["overall"]["graded"], 1)

    def test_split_and_system_groups_do_not_mix_labels(self):
        jobs = [job(), job(system="baseline"), job("fixture-2", split="test")]
        rows = [prediction(), prediction(system="baseline"), prediction("fixture-2")]
        report = summarize_benchmark({"jobs": jobs}, rows, [grade(), grade(system="baseline"), grade("fixture-2", supported=False)])
        self.assertEqual(report["progress"]["by_system_split"]["baseline"]["test"]["scheduled"], 0)
        self.assertEqual(report["quality_by_split"]["dev"]["systems"]["ignis"]["claim_support"]["value"], 1)
        self.assertEqual(report["quality_by_split"]["test"]["systems"]["ignis"]["claim_support"]["value"], 0)
        self.assertEqual(report["quality"]["paired"]["baseline__ignis"]["question_ids"], ["fixture-1"])

    def test_unknown_usage_stays_null_and_latency_includes_failure(self):
        rows = [prediction(latency_ms=10, input_tokens=4, output_tokens=None),
                prediction("fixture-2", error="Synthetic failure", latency_ms=30)]
        report = summarize_benchmark({"jobs": [job(), job("fixture-2")]}, rows)
        p = report["performance"]["overall"]
        self.assertEqual(p["mean_latency_ms"], 20)
        self.assertIsNone(p["input_tokens"]["total"])
        self.assertEqual(p["input_tokens"]["known_subtotal"], 4)
        self.assertEqual(p["input_tokens"]["unknown_predictions"], 1)
        self.assertIsNone(p["output_tokens"]["known_subtotal"])
        self.assertIsNone(p["cost_usd"]["total"])
        self.assertEqual(p["cache_status_unknown_predictions"], 2)

    def test_cache_usage_counts_only_new_tokens_and_partial_unknown(self):
        calls = [{"cache_hit": True, "usage": {"prompt_tokens": 0, "completion_tokens": 0},
                  "cached_usage": {"prompt_tokens": 900, "completion_tokens": 900}},
                 {"cache_hit": False, "usage": {"prompt_tokens": 5, "completion_tokens": 2}},
                 {"usage": {"prompt_tokens": 1, "completion_tokens": 1}}]
        report = summarize_benchmark({"jobs": [job()]}, [prediction(model_calls=calls)])
        p = report["performance"]["overall"]
        self.assertEqual(p["cache_hit_calls"], 1)
        self.assertEqual(p["cache_status_known_calls"], 2)
        self.assertEqual(p["cache_status_unknown_calls"], 1)
        self.assertEqual(p["input_tokens"]["total"], 6)
        self.assertEqual(p["output_tokens"]["total"], 3)
        self.assertIn("cache", p["latency_policy"])

    def test_zero_usage_is_known_but_missing_call_usage_is_unknown(self):
        rows = [prediction(model_calls=[{"cache_hit": True, "usage": {"prompt_tokens": 0, "completion_tokens": 0}}])]
        self.assertEqual(summarize_benchmark({"jobs": [job()]}, rows)["performance"]["overall"]["input_tokens"]["total"], 0)
        rows[0]["model_calls"].append({"cache_hit": False, "usage": {}})
        self.assertIsNone(summarize_benchmark({"jobs": [job()]}, rows)["performance"]["overall"]["input_tokens"]["total"])

    def test_all_failed_and_empty_schedules_never_look_graded(self):
        report = summarize_benchmark({"jobs": [job()]}, [prediction(error="Synthetic failure")])
        self.assertEqual(report["quality"]["systems"], {})
        self.assertIsNone(report["progress"]["overall"]["answer_coverage"]["value"])
        empty = summarize_benchmark({"jobs": []}, [])
        self.assertEqual(empty["progress"]["overall"]["scheduled"], 0)
        self.assertIsNone(empty["performance"]["overall"]["mean_latency_ms"])

    def test_metadata_and_inputs_preserved_without_inferred_validation(self):
        manifest = {"jobs": [job()], "evaluation_kind": "exploratory_generation", "annotation_status": "unreviewed",
                    "status": "interrupted", "source_readiness": {"warnings": ["Synthetic extraction warning"]}}
        rows = [prediction(input_tokens=None, latency_ms=None)]
        before = copy.deepcopy((manifest, rows))
        report = summarize_benchmark(manifest, rows)
        self.assertEqual((manifest, rows), before)
        self.assertEqual(report["manifest_status"], "interrupted")
        self.assertEqual(report["source_readiness"], manifest["source_readiness"])
        report["source_readiness"]["warnings"].clear()
        self.assertTrue(manifest["source_readiness"]["warnings"])

    def test_malformed_duplicate_or_orphan_records_rejected(self):
        cases = [({}, [], None), ({"jobs": [job(), job()]}, [], None),
                 ({"jobs": [job(split="train")]}, [], None),
                 ({"jobs": [job()]}, [prediction(), prediction()], None),
                 ({"jobs": [job()]}, [prediction("outside")], None),
                 ({"jobs": [job()]}, [], [grade()]),
                 ({"jobs": [job()]}, [prediction()], [grade(), grade()]),
                 ({"jobs": [job()]}, [prediction(abstained=1)], None),
                 ({"jobs": [job()]}, [prediction(error=True)], None),
                 ({"jobs": [job()]}, [prediction(latency_ms=-1)], None),
                 ({"jobs": [job()]}, [prediction(model_calls=[{"cache_hit": "yes"}])], None)]
        for manifest, rows, grades in cases:
            with self.subTest(manifest=manifest, rows=rows), self.assertRaises(ValueError):
                summarize_benchmark(manifest, rows, grades)

    def test_existing_evaluator_receives_no_failed_predictions(self):
        from axiom.evaluate import evaluate
        with patch("axiom.benchmark_report.evaluate", wraps=evaluate) as scorer:
            summarize_benchmark({"jobs": [job(), job("fixture-2")]},
                                [prediction(), prediction("fixture-2", error="Synthetic failure")])
        self.assertEqual(len(scorer.call_args_list[0].args[0]), 1)
        self.assertEqual(scorer.call_args_list[0].args[1], [])

    def test_unavailable_named_scope_remains_pending_without_quality(self):
        blocked = {**job("fixture-2", split="test"), "block_reason": "named_scope_unavailable"}
        report = summarize_benchmark({"jobs": [job(), blocked]}, [prediction()])
        progress = report["progress"]["overall"]
        self.assertEqual(progress["pending"], 1)
        self.assertEqual(progress["blocked_scope"], 1)
        self.assertEqual(progress["failed"], 0)
        self.assertEqual(progress["pending_blocked"][0]["block_reason"], "named_scope_unavailable")
        self.assertEqual(report["quality_by_split"]["test"]["systems"], {})


if __name__ == "__main__":
    unittest.main()
