"""Synthetic review fixtures test the contract and provenance checks."""
import copy
import unittest

from axiom.model import LocalModel, REVIEW_SCHEMA


def evidence():
    return [
        {"source_id": "fixture-s", "chunk_id": "fixture-c1",
         "text": "The synthetic detector measured 1 mW in this particular setup."},
        {"source_id": "fixture-s", "chunk_id": "fixture-c2",
         "text": "This observation applies only to the tested material in microgravity."},
    ]


def check(index=0, relation="supports"):
    chunk = evidence()[index]
    return {"source_id": chunk["source_id"], "chunk_id": chunk["chunk_id"],
            "quote": chunk["text"], "relation": relation}


def review_response(verdict="supported", checks=None):
    return {"verdict": verdict, "reason": "Synthetic review explanation.",
            "evidence_checks": [check()] if checks is None else checks,
            "uncertainty": "Synthetic scope is restricted to the provided fixture."}


class FixtureModel(LocalModel):
    def __init__(self, response):
        super().__init__("synthetic-model")
        self.response = response
        self.received = None

    def complete(self, system, payload, schema):
        self.received = (system, payload, schema)
        return copy.deepcopy(self.response)


class ModelReviewTests(unittest.TestCase):
    def review(self, response, chunks=None, claim="The synthetic detector measured 1 mW."):
        model = FixtureModel(response)
        result = model.review(claim, evidence() if chunks is None else chunks)
        return result, model

    def test_supported_requires_verified_support_and_preserves_full_context(self):
        response = review_response()
        result, model = self.review(response)
        instruction, payload, schema = model.received
        self.assertEqual(schema, REVIEW_SCHEMA)
        self.assertEqual(payload["evidence"], evidence())
        self.assertEqual(payload["claim"], "The synthetic detector measured 1 mW.")
        self.assertIn("all supplied retrieved context", instruction)
        self.assertEqual(result["verdict"], "supported")
        self.assertEqual(result["asserted_verdict"], "supported")
        self.assertEqual(result["validation"]["quote_provenance"], "verified")
        self.assertEqual(result["validation"]["semantic_grounding"], "model_assessed")
        self.assertEqual(response, review_response())

    def test_counterevidence_can_come_from_another_retrieved_passage(self):
        response = review_response("contradicted", [check(1, "contradicts")])
        result, _ = self.review(response, claim="The observation applies to every material and gravity regime.")
        self.assertEqual(result["verdict"], "contradicted")
        self.assertEqual(result["evidence_checks"][0]["chunk_id"], "fixture-c2")

    def test_supported_with_limiting_or_conflicting_span_downgrades_and_keeps_assertion(self):
        for relation in ("limits", "contradicts"):
            response = review_response(checks=[check(), check(1, relation)])
            with self.subTest(relation=relation):
                result, _ = self.review(response)
                self.assertEqual(result["verdict"], "uncertain")
                self.assertEqual(result["asserted_verdict"], "supported")
                self.assertEqual(result["evidence_checks"], response["evidence_checks"])
                self.assertEqual(result["reason"], response["reason"])
                self.assertIn("support_includes_limiting_or_contradicting_evidence", result["validation"]["issues"])

    def test_forged_counterevidence_reference_or_quote_is_rejected(self):
        for field, value in (("source_id", "forged-source"), ("chunk_id", "forged-chunk"), ("quote", "Invented contradiction")):
            response = review_response("contradicted", [check(1, "contradicts")])
            response["evidence_checks"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.review(response)

    def test_quote_matching_preserves_numeric_units_and_negation(self):
        for quote in ("The synthetic detector measured 1 MW in this particular setup.",
                      "The synthetic detector measured 10 mW in this particular setup.",
                      "The synthetic detector did not measure 1 mW in this particular setup."):
            response = review_response()
            response["evidence_checks"][0]["quote"] = quote
            with self.subTest(quote=quote), self.assertRaisesRegex(ValueError, "quotation"):
                self.review(response)
        response = review_response()
        response["evidence_checks"][0]["quote"] = "The synthetic detector\n measured 1 mW in this particular setup."
        self.assertEqual(self.review(response)[0]["verdict"], "supported")

    def test_quote_verification_explicitly_leaves_relation_semantics_model_assessed(self):
        # A structurally valid support label can still be a model error.
        # The deterministic validator exposes its narrower scope.
        result, _ = self.review(review_response(), claim="The synthetic detector measured 1 MW.")
        self.assertEqual(result["validation"]["semantic_grounding"], "model_assessed")

    def test_supported_and_contradicted_cannot_omit_their_required_relation(self):
        for response in (review_response("supported", []), review_response("contradicted", []),
                         review_response("contradicted", [check()]), review_response("supported", [check(1, "limits")])):
            with self.subTest(response=response), self.assertRaises(ValueError):
                self.review(response)

    def test_uncertain_and_unsupported_can_report_absent_support(self):
        for verdict in ("uncertain", "unsupported"):
            result, _ = self.review(review_response(verdict, []), chunks=[])
            self.assertEqual(result["verdict"], verdict)
            self.assertEqual(result["validation"]["verified_span_count"], 0)
            self.assertEqual(result["validation"]["quote_provenance"], "no_spans_supplied")

    def test_required_fields_and_nonempty_explanations(self):
        valid = review_response()
        malformed = [None, [], {**valid, "extra": True}, {key: value for key, value in valid.items() if key != "uncertainty"}]
        malformed.extend({**valid, key: value} for key, value in (
            ("reason", " "), ("uncertainty", ""), ("verdict", "certified"), ("evidence_checks", "not an array")))
        for response in malformed:
            with self.subTest(response=response), self.assertRaises(ValueError):
                self.review(response)

    def test_evidence_check_shape_limit_and_relations(self):
        malformed = [None, {**check(), "relation": "proves"}, {**check(), "quote": " "}, {**check(), "score": 1}]
        for entry in malformed:
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                self.review(review_response(checks=[entry]))
        with self.assertRaisesRegex(ValueError, "eight"):
            self.review(review_response(checks=[check()] * 9))

    def test_malformed_or_ambiguous_evidence_is_rejected(self):
        for chunks in ([{}], evidence() + [evidence()[0]], ["invalid chunk"]):
            with self.subTest(chunks=chunks), self.assertRaises(ValueError):
                self.review(review_response(), chunks=chunks)

    def test_empty_claim_rejected_before_model_call(self):
        model = FixtureModel(review_response())
        with self.assertRaises(ValueError):
            model.review(" ", evidence())
        self.assertIsNone(model.received)

    def test_draft_retains_optional_claim_type_and_limitations(self):
        draft = {"abstained": False, "reason": "Synthetic draft.", "claims": [{
            "text": "A synthetic finding.", "claim_type": "model_prediction", "limitations": "Fixture scope.",
            "citations": [{"source_id": "fixture-s", "chunk_id": "fixture-c1", "quote": evidence()[0]["text"]}]}]}
        model = FixtureModel(draft)
        self.assertEqual(model.draft("Fixture question?", evidence()), draft)
        self.assertIn("Avoid repeating", model.received[0])


if __name__ == "__main__":
    unittest.main()

class BatchReviewTests(unittest.TestCase):
    def test_batch_maps_reviews_to_requested_order(self):
        from axiom.model import validate_review_batch
        obj={'reviews':[dict(review_response(),claim_id='second'),dict(review_response(),claim_id='first')]}
        claims=[{'claim_id':'first','text':'Fixture first'},{'claim_id':'second','text':'Fixture second'}]
        result=validate_review_batch(obj,claims,evidence())
        self.assertEqual(len(result),2)
        self.assertTrue(all(r['verdict']=='supported' for r in result))

    def test_missing_duplicate_and_forged_batch_reviews_rejected(self):
        from axiom.model import validate_review_batch
        claims=[{'claim_id':'first','text':'Fixture first'},{'claim_id':'second','text':'Fixture second'}]
        for ids in (['first'],['first','first'],['first','forged']):
            obj={'reviews':[dict(review_response(),claim_id=identity) for identity in ids]}
            with self.subTest(ids=ids),self.assertRaises(ValueError):
                validate_review_batch(obj,claims,evidence())


class ShortQuoteTests(unittest.TestCase):
    def test_uninformative_short_support_quote_rejected(self):
        response=review_response()
        response['evidence_checks'][0]['quote']='The'
        with self.assertRaisesRegex(ValueError,'fifteen'):
            FixtureModel(response).review('Fixture claim',evidence())
