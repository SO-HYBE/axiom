"""Synthetic ranking fixtures test accounting. They are not scientific results."""
import copy
import unittest

from axiom.retrieval_eval import cases_digest, evaluate_retrieval


def passages(count=6):
    return [{"source_id": "fixture", "chunk_id": f"p{i}", "text": f"Synthetic sample {i} at 1 mW."}
            for i in range(1, count + 1)]


def query(qid, wanted=()):
    return {"query_id": qid, "query": qid + " synthetic question", "expected_match": bool(wanted),
            "reference_spans": [{"source_id": c["source_id"], "chunk_id": c["chunk_id"], "quote": c["text"]}
                                for c in wanted], "annotation_status": "ai_draft", "span_labels_exhaustive": False}


class RetrievalEvaluationTests(unittest.TestCase):
    def test_hit_recall_and_negative_accuracy_have_separate_denominators(self):
        corpus = passages()
        cases = [query("a", corpus[:2]), query("b", [corpus[5]]), query("c"), query("d")]
        responses = {"a": [corpus[0]], "b": corpus, "c": [], "d": [corpus[3]]}
        calls = []

        def retrieve(text, chunks, limit):
            calls.append((text, limit))
            self.assertIs(chunks, corpus)
            return responses[text.split()[0]]

        report = evaluate_retrieval(cases, corpus, retrieve)
        self.assertEqual(calls, [(case["query"], 5) for case in cases])
        self.assertEqual(report["hit_at_5"], {"numerator": 1, "denominator": 2, "value": 0.5})
        self.assertEqual(report["known_span_recall_at_5"], {"numerator": 1, "denominator": 3, "value": 1 / 3})
        self.assertEqual(report["negative_abstention_accuracy"], {"numerator": 1, "denominator": 2, "value": 0.5})
        self.assertEqual(len(report["queries"][1]["rankings"]), 5)
        self.assertIsNone(report["queries"][2]["hit_at_5"])
        self.assertTrue(report["queries"][2]["negative_abstention_correct"])

    def test_actual_rank_and_reference_are_inspectable(self):
        corpus = passages(2)
        case = query("rank", [corpus[1]])
        report = evaluate_retrieval([case], corpus, lambda text, chunks, limit: [{**c, "score": score}
                                                                                 for c, score in zip(chunks, (3, 2))])
        detail = report["queries"][0]
        self.assertEqual(detail["rankings"][1], {"rank": 2, "source_id": "fixture", "chunk_id": "p2", "score": 2})
        self.assertEqual(detail["reference_spans"][0]["rank"], 2)
        self.assertEqual(detail["known_span_recall_at_5"]["value"], 1)
        self.assertIsNone(report["negative_abstention_accuracy"]["value"])

    def test_no_positive_queries_never_scores_full_recall(self):
        report = evaluate_retrieval([query("missing")], [], lambda *unused: [])
        self.assertEqual(report["hit_at_5"]["denominator"], 0)
        self.assertIsNone(report["hit_at_5"]["value"])
        self.assertIsNone(report["known_span_recall_at_5"]["value"])
        self.assertEqual(report["negative_abstention_accuracy"]["value"], 1)

    def test_invalid_gold_rejected_before_search(self):
        corpus = passages(1)
        original = query("a", corpus)
        for field, value in (("quote", "Synthetic sample 1 at 1 MW."), ("chunk_id", "missing"), ("source_id", "other")):
            case = copy.deepcopy(original)
            case["reference_spans"][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "does not resolve"):
                evaluate_retrieval([case], corpus, lambda *args: self.fail("search must not see bad labels"))

    def test_duplicate_queries_spans_and_unlabeled_positive_rejected(self):
        corpus = passages(1)
        case = query("a", corpus)
        for cases in ([case, case], [{**case, "reference_spans": case["reference_spans"] * 2}],
                      [{**case, "expected_match": False}], [{**case, "reference_spans": []}]):
            with self.subTest(cases=cases), self.assertRaises(ValueError):
                evaluate_retrieval(cases, corpus, lambda *args: [])

    def test_rankings_require_real_unique_corpus_ids(self):
        corpus = passages(1)
        for result in ([corpus[0], corpus[0]], [{**corpus[0], "source_id": "wrong"}],
                       [{**corpus[0], "chunk_id": "unknown"}]):
            with self.subTest(result=result), self.assertRaisesRegex(ValueError, "retrieved unknown"):
                evaluate_retrieval([query("a", corpus)], corpus, lambda *args: result)

    def test_canonical_digest_preserves_case_order_and_contents(self):
        a, b = query("a"), query("b")
        self.assertEqual(cases_digest([a, b]), cases_digest([dict(reversed(list(a.items()))), b]))
        self.assertNotEqual(cases_digest([a, b]), cases_digest([b, a]))
        self.assertNotEqual(cases_digest([a, b]), cases_digest([{**a, "query": "different question"}, b]))


if __name__ == "__main__":
    unittest.main()
