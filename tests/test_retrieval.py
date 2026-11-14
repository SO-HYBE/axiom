"""Retrieval-contract tests using synthetic passages and test conditions."""

import unittest

from axiom.retrieval import search


def passage(source_id, chunk_id, text, **overrides):
    record = {
        "source_id": source_id,
        "chunk_id": chunk_id,
        "title": "Fixture publication",
        "locator": "PDF page 1, text part 1",
        "text": text,
        "source_kind": "conference_paper",
        "experiment": "BASS-II",
        "evidence_tier": 1,
        "conditions": {},
    }
    record.update(overrides)
    return record


class EvidenceRetrievalTests(unittest.TestCase):
    def test_metadata_catalogs_and_rights_holds_never_enter_the_evidence_pool(self):
        records = [
            passage("legacy", "legacy-page", "A passage about oxygen."),
            passage("catalog", "catalog-entry", "An oxygen collection.", source_kind="dataset_catalog"),
            passage("metadata", "index-entry", "An oxygen index entry.", source_kind="metadata"),
            passage("held", "held-page", "An oxygen finding.", permission_status="review_required"),
            passage("blocked", "blocked-page", "A blocked oxygen record.", permission_status="blocked"),
        ]
        for opt_in in (False, True):
            with self.subTest(include_overviews=opt_in):
                hits = search("oxygen", records, include_overviews=opt_in)
                self.assertEqual([hit["source_id"] for hit in hits], ["legacy"])

    def test_overviews_require_explicit_opt_in(self):
        overview = passage("plan", "objectives", "The planned test concerns extinction.",
                           source_kind="experiment_overview", evidence_tier=3)
        self.assertEqual(search("extinction", [overview]), [])
        hits = search("extinction", [overview], include_overviews=True)
        self.assertEqual([hit["chunk_id"] for hit in hits], ["objectives"])

    def test_experiment_and_source_filters_intersect(self):
        records = [
            passage("selected", "s", "Oxygen observation.", experiment="FLEX"),
            passage("excluded-source", "u", "Oxygen measurement.", experiment="FLEX"),
            passage("excluded-experiment", "v", "Oxygen summary.", experiment="SAFFIRE"),
        ]
        hits = search("oxygen", records, experiments=["FLEX"], source_ids=["selected", "excluded-experiment"])
        self.assertEqual([hit["source_id"] for hit in hits], ["selected"])

    def test_identical_passages_share_a_result_and_keep_eligible_source_attribution(self):
        text = "The sample extinction passage is identical across two publications."
        records = [
            passage("original", "p1", text, study_family="BASS-II"),
            passage("copy", "p2", text, study_family="BASS-II"),
            passage("held-copy", "p3", text, study_family="BASS-II", permission_status="review_required"),
        ]
        hits = search("extinction", records)
        self.assertEqual(len(hits), 1)
        chosen = hits[0]
        attributions = set(chosen["ranking"]["duplicate_source_ids"]) | {chosen["source_id"]}
        self.assertEqual(attributions, {"original", "copy"})
        self.assertEqual(chosen["text"], text)

    def test_distinct_passages_from_one_publication_both_remain_available(self):
        records = [
            passage("paper", "page-one", "Oxygen was recorded.", locator="PDF page 1, text part 1"),
            passage("paper", "page-two", "Oxygen was varied.", locator="PDF page 2, text part 1"),
        ]
        hits = search("oxygen", records)
        self.assertEqual({hit["chunk_id"] for hit in hits}, {"page-one", "page-two"})

    def test_rank_explanation_identifies_actual_query_terms_and_document_tier(self):
        record = passage("paper", "chunk", "Oxygen was measured.", evidence_tier=2)
        hit = search("oxygen pressure", [record])[0]
        rank = hit["ranking"]
        self.assertGreater(rank["lexical_score"], 0)
        self.assertEqual(set(rank["matched_terms"]), {"oxygen"})
        self.assertEqual(rank["evidence_tier"], 2)
        self.assertEqual(rank["applicability"]["status"], "not_requested")
        self.assertNotIn("ranking", record)

    def test_source_category_is_exposed_and_only_breaks_equal_relevance_ties(self):
        background = passage("background", "background", "Oxygen measured.",
                             source_category="scientific_background", source_kind="technical_report")
        primary = passage("primary", "primary", "Oxygen measured.",
                          source_category="primary_experimental_data", source_kind="experimental_dataset")
        hits = search("oxygen", [background, primary])
        self.assertEqual([hit['chunk_id'] for hit in hits], ['primary', 'background'])
        self.assertEqual(hits[0]['ranking']['resource_id'], None)
        self.assertEqual(hits[0]['ranking']['source_category'], 'primary_experimental_data')
        # More lexical overlap still outranks category when relevance differs.
        detailed = passage("background-detailed", "detailed", "Oxygen measured and documented.",
                           source_category="scientific_background")
        hits = search("oxygen documented", [primary, detailed])
        self.assertEqual(hits[0]['chunk_id'], 'detailed')

    def test_missing_condition_retains_evidence_and_identifies_the_unknown_field(self):
        record = passage("paper", "chunk", "A flow observation.",
                         conditions={"gravity": "microgravity", "flow_cm_s": None})
        hits = search("flow", [record], target={"gravity": "microgravity", "flow_cm_s": 0})
        self.assertEqual(len(hits), 1)
        applicability = hits[0]["ranking"]["applicability"]
        self.assertEqual(applicability["status"], "unknown")
        self.assertIn("flow_cm_s", applicability["unknown_fields"])

    def test_known_zero_flow_is_distinct_from_missing_or_nonzero_flow(self):
        record = passage("paper", "chunk", "A flow observation.", conditions={"flow_cm_s": 0})
        matching = search("flow", [record], target={"flow_cm_s": 0})[0]
        different = search("flow", [record], target={"flow_cm_s": 5})[0]
        self.assertEqual(matching["ranking"]["applicability"]["status"], "matching_fields")
        applicability = different["ranking"]["applicability"]
        self.assertEqual(applicability["status"], "mismatch")
        self.assertIn("flow_cm_s", applicability["mismatched_fields"])

    def test_flow_does_not_generate_a_match_on_airflow_alone(self):
        record = passage("paper", "chunk", "Airflow was recorded.")
        self.assertEqual(search("flow", [record]), [])


    def test_sparse_shared_vocabulary_can_return_no_results(self):
        record = passage("paper", "chunk", "A pressure observation.")
        query = "planetary magnetic terrain temperature pressure spectroscopy"
        self.assertEqual(search(query, [record]), [])
        self.assertEqual(len(search(query, [record], min_query_coverage=0)), 1)

    def test_invalid_coverage_threshold_is_rejected(self):
        for value in (-1, 2, float('nan'), True):
            with self.assertRaises(ValueError):
                search("oxygen", [], min_query_coverage=value)

if __name__ == "__main__":
    unittest.main()
