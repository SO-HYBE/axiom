import copy
import json
import unittest
from pathlib import Path

from axiom.evaluate import evaluate


def prediction(qid="Q001", system="ignis", citations=True):
    return {"question_id": qid, "system": system, "answer": "Synthetic test answer, not NASA science.",
            "abstained": False, "latency_ms": 10,
            "claims": [{"text": "Synthetic fixture claim.", "verdict": "unreviewed",
                        "citations": [{"source_id": "fixture", "chunk_id": "fixture-1", "quote": "fixture"}] if citations else []}]}


def grade(qid="Q001", system="ignis", supported=True, citation=True, unsafe=False, correct=True):
    return {"question_id": qid, "system": system,
            "claims": [{"supported": supported, "citation_valid": citation, "unsafe_extrapolation": unsafe}],
            "correct_abstention": correct}


class EvaluateTests(unittest.TestCase):
    def test_rates_and_denominators(self):
        predictions = [prediction(), prediction("Q002", citations=False)]
        annotations = [grade(), grade("Q002", supported=False, citation=False, unsafe=True)]
        s = evaluate(predictions, annotations)["systems"]["ignis"]
        self.assertEqual(s["claim_support"]["value"], 0.5)
        self.assertEqual(s["citation_precision"]["value"], 1)
        self.assertEqual(s["citation_precision"]["denominator"], 1)
        self.assertEqual(s["citation_coverage"]["value"], 0.5)
        self.assertEqual(s["unsafe_extrapolation"]["value"], 0.5)

    def test_missing_grades_not_scored(self):
        s = evaluate([prediction()], [])["systems"]["ignis"]
        self.assertEqual(s["ungraded_questions"], 1)
        self.assertIsNone(s["claim_support"]["value"])
        self.assertEqual(s["answer_coverage"]["value"], 1)

    def test_no_claim_abstention_not_perfect_support(self):
        p, g = prediction(), grade()
        p.update(claims=[], abstained=True)
        g.update(claims=[])
        s = evaluate([p], [g])["systems"]["ignis"]
        self.assertIsNone(s["claim_support"]["value"])
        self.assertEqual(s["answer_coverage"]["value"], 0)
        self.assertEqual(s["abstention_accuracy"]["value"], 1)

    def test_duplicate_prediction_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            evaluate([prediction(), prediction()], [])

    def test_duplicate_annotation_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            evaluate([prediction()], [grade(), grade()])

    def test_orphan_annotation_rejected(self):
        with self.assertRaisesRegex(ValueError, "no prediction"):
            evaluate([], [grade()])

    def test_unfinished_annotation_rejected(self):
        g = grade()
        g["claims"][0]["supported"] = None
        with self.assertRaisesRegex(ValueError, "boolean"):
            evaluate([prediction()], [g])

    def test_invalid_system_id_and_numeric_fields_rejected(self):
        for field, value in [("system", "fake"), ("question_id", "../Q001"), ("abstained", 0),
                             ("latency_ms", float("nan")), ("latency_ms", -1)]:
            p = prediction()
            p[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                evaluate([p], [])

    def test_claim_count_mismatch_rejected(self):
        g = grade()
        g["claims"] = []
        with self.assertRaisesRegex(ValueError, "one claim"):
            evaluate([prediction()], [g])

    def test_paired_uses_shared_graded_questions_only(self):
        predictions = [prediction(system="baseline"), prediction(), prediction("Q002")]
        annotations = [grade(system="baseline", supported=False), grade(), grade("Q002")]
        pair = evaluate(predictions, annotations)["paired"]["baseline__ignis"]
        self.assertEqual(pair["question_ids"], ["Q001"])
        self.assertEqual(pair["delta_right_minus_left"]["claim_support"], 1)

    def test_null_abstention_grade_excluded(self):
        s = evaluate([prediction()], [grade(correct=None)])["systems"]["ignis"]
        self.assertEqual(s["abstention_accuracy"]["denominator"], 0)
        self.assertIsNone(s["abstention_accuracy"]["value"])

    def test_empty_inputs_and_no_mutation(self):
        self.assertEqual(evaluate([], [])["systems"], {})
        p, g = [prediction()], [grade()]
        original = copy.deepcopy((p, g))
        evaluate(p, g)
        self.assertEqual((p, g), original)

    def test_benchmark_integrity_and_disjoint_families(self):
        root = Path(__file__).resolve().parents[1] / "benchmarks"
        cases = [json.loads(line) for line in (root / "questions.jsonl").read_text(encoding="utf-8").splitlines()]
        sources = json.loads((root / "sources.json").read_text(encoding="utf-8"))
        self.assertEqual(len(cases), 36)
        self.assertEqual(len({q["question_id"] for q in cases}), 36)
        self.assertEqual(sum(q["split"] == "dev" for q in cases), 12)
        self.assertEqual(sum(q["split"] == "test" for q in cases), 24)
        dev = {q["family_id"] for q in cases if q["split"] == "dev"}
        test = {q["family_id"] for q in cases if q["split"] == "test"}
        self.assertFalse(dev & test)
        for q in cases:
            self.assertEqual(q["annotation_status"], "ai_draft_unreviewed")
            self.assertTrue(set(q["reference_ids"]) <= sources.keys())
            self.assertIs(type(q["expected_abstained"]), bool)


if __name__ == "__main__":
    unittest.main()
