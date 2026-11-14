import unittest
from axiom.critic import check_claim, validate_conditions
from axiom.model import validate_draft, LocalModel


class CriticTests(unittest.TestCase):
    def setUp(self):
        self.text = "Flames can persist under the experimental conditions described here."
        self.chunk = {"source_id": "nasa-1", "text": self.text, "url": "https://ntrs.nasa.gov/citations/1", "locator": "PDF page 2", "conditions": {}}
        self.claim = {"text": self.text, "citations": [{"source_id": "nasa-1", "chunk_id": "c1", "quote": self.text}]}

    def check(self, claim=None, **kwargs):
        return check_claim(claim or self.claim, {"c1": self.chunk}, **kwargs)

    def test_exact_excerpt_is_not_safety_validation(self):
        result = self.check()
        self.assertEqual(result["verdict"], "quoted_evidence")
        self.assertEqual(result["applicability"], "not_assessed")

    def test_forged_citation_rejected(self):
        self.claim["citations"][0]["source_id"] = "fake"
        self.assertEqual(self.check()["verdict"], "blocked")

    def test_wrong_quote_rejected(self):
        self.claim["citations"][0]["quote"] = "All flames are safe in every condition."
        self.assertEqual(self.check()["verdict"], "blocked")

    def test_scientific_unit_case_is_preserved(self):
        self.chunk["text"] = "The measured power was 1 mW under these conditions."
        self.claim["text"] = "The measured power was 1 MW under these conditions."
        self.claim["citations"][0]["quote"] = self.claim["text"]
        self.assertEqual(self.check()["verdict"], "blocked")

    def test_true_quote_does_not_support_inverted_claim(self):
        self.claim["text"] = "Flames never persist under the experimental conditions described here."
        self.assertEqual(self.check()["verdict"], "needs_review")
        self.assertEqual(self.check(semantic={"verdict": "unsupported", "reason": "Negation inversion"})["verdict"], "blocked")

    def test_model_support_remains_provisional(self):
        self.claim["text"] = "The experiment sustained flames."
        self.assertEqual(self.check(semantic={"verdict": "supported", "reason": "Paraphrase"})["verdict"], "model_supported_needs_review")

    def reviewed(self, quote, claim, kind="conference_paper", extra=""):
        self.chunk.update(text=quote + extra, source_kind=kind)
        self.claim["text"] = claim
        self.claim["citations"][0]["quote"] = quote
        return self.check(semantic={"verdict": "supported", "reason": "fixture semantic judgment"})

    def test_swapped_composition_blocked_even_when_both_numbers_are_cited(self):
        result = self.reviewed("The specimen contained 75% cotton, 25% fiberglass.",
                               "The specimen was 25% cotton and 75% fiberglass.")
        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("numeric_association_mismatch", result["issues"])

    def test_correct_pairs_survive_reordering_but_remain_provisional(self):
        result = self.reviewed("The specimen contained 75% cotton, 25% fiberglass.",
                               "The blend included 25% fiberglass and 75% cotton.")
        self.assertEqual(result["verdict"], "model_supported_needs_review")
        self.assertEqual(result["issues"], [])

    def test_unparsed_percent_association_needs_review(self):
        result = self.reviewed("The specimen contained 75% cotton, 25% fiberglass.",
                               "Fiberglass accounted for 75% of the specimen.")
        self.assertEqual(result["verdict"], "needs_review")
        self.assertIn("numeric_association_unresolved", result["issues"])

    def test_uncited_measurement_elsewhere_on_page_cannot_support_a_paraphrase(self):
        result = self.reviewed("The first test recorded 1 mW of power.",
                               "The first test produced 1 MW.", extra=" A different test recorded 1 MW.")
        self.assertEqual(result["verdict"], "needs_review")
        self.assertIn("numeric_literal_not_cited", result["issues"])

    def test_unknown_unit_with_identical_number_needs_review(self):
        result = self.reviewed("The fixture measured 5 widgets of signal.",
                               "A value of 5 widgets was recorded.")
        self.assertEqual(result["verdict"], "needs_review")
        self.assertIn("numeric_unit_unresolved", result["issues"])

    def test_multi_percentage_prose_without_a_parseable_list_needs_review(self):
        result = self.reviewed("Cotton accounted for 75% whereas fiberglass accounted for 25%.",
                               "The sample contained 75% fiberglass and 25% cotton.")
        self.assertEqual(result["verdict"], "needs_review")
        self.assertIn("numeric_association_unresolved", result["issues"])

    def test_extreme_numeric_literal_does_not_abort_claim_review(self):
        result = self.reviewed("The fixture recorded a pressure measurement.",
                               "The reported pressure was 1e999999999999999999999999999 Pa.")
        self.assertEqual(result["verdict"], "needs_review")
        self.assertIn("numeric_literal_unresolved", result["issues"])

    def test_overview_plan_cannot_support_completed_finding(self):
        result = self.reviewed("The experiment will examine the extinction of droplets.",
                               "The experiment demonstrated droplet extinction.", kind="experiment_overview")
        self.assertEqual(result["verdict"], "needs_review")
        self.assertIn("overview_scope_unresolved", result["issues"])

    def test_overview_objective_can_remain_an_objective(self):
        result = self.reviewed("The experiment will examine the extinction of droplets.",
                               "The study aims to examine droplet extinction.", kind="experiment_overview")
        self.assertEqual(result["verdict"], "model_supported_needs_review")

    def test_categorical_summary_with_experiment_identifier_is_unaffected(self):
        result = self.reviewed("FLEX-2 investigated droplet behavior under the reported conditions.",
                               "The FLEX-2 investigation studied droplet behavior.")
        self.assertEqual(result["verdict"], "model_supported_needs_review")

    def test_unknown_conditions_prevent_transfer(self):
        result = self.check(target={"oxygen_percent": 30}, applicability=True)
        self.assertEqual(result["verdict"], "needs_review")
        self.assertIn("condition_unknown:oxygen_percent", result["issues"])

    def test_zero_flow_is_not_missing(self):
        self.chunk["conditions"] = {"flow_cm_s": 0}
        result = self.check(target={"flow_cm_s": 0}, applicability=True)
        self.assertNotIn("condition_unknown:flow_cm_s", result["issues"])
        self.assertNotIn("condition_mismatch:flow_cm_s", result["issues"])

    def test_condition_mismatch_reported(self):
        self.chunk["conditions"] = {"gravity": "microgravity"}
        self.assertIn("condition_mismatch:gravity", self.check(target={"gravity": "lunar"}, applicability=True)["issues"])

    def test_invalid_conditions_rejected(self):
        for bad in ({"oxygen_percent": 101}, {"flow_cm_s": float("nan")}, {"pressure_kpa": 0}, {"fuel": 2}, {"unknown": 1}, {"flow_cm_s": True}):
            with self.assertRaises(ValueError):
                validate_conditions(bad)

    def test_malformed_model_claims_rejected(self):
        for bad in ({}, {"abstained": "false", "reason": "", "claims": []}, {"abstained": False, "reason": "", "claims": [{"text": "x", "citations": [None]}]}):
            with self.assertRaises(ValueError):
                validate_draft(bad)

    def test_model_endpoint_is_local_only(self):
        with self.assertRaises(ValueError):
            LocalModel("model", "https://example.com")

class Phase4CriticTests(unittest.TestCase):
    def claim(self,text):
        quote='The investigated sample showed limited flame spread in this particular setup.'
        chunk={'source_id':'s','text':quote,'url':'https://ntrs.nasa.gov/citations/1','locator':'PDF page 1','conditions':{}}
        claim={'text':text,'citations':[{'source_id':'s','chunk_id':'c','quote':quote}]}
        return claim,{'c':chunk}

    def test_universal_safety_claim_cannot_be_released_on_supported_model_label(self):
        claim,chunks=self.claim('All spacecraft materials are fireproof.')
        result=check_claim(claim,chunks,semantic={'verdict':'supported','reason':'Fixture error'})
        self.assertIn('universal_safety_claim_unresolved',result['issues'])
        self.assertEqual(result['verdict'],'needs_review')

    def test_qualified_negation_avoids_universal_assertion_flag(self):
        claim,chunks=self.claim('This does not establish that all spacecraft materials are fireproof.')
        result=check_claim(claim,chunks,semantic={'verdict':'supported','reason':'Fixture interpretation'})
        self.assertNotIn('universal_safety_claim_unresolved',result['issues'])
