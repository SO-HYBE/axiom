"""Synthetic records exercise review-hint boundaries without scientific labels."""
import copy
import unittest

from axiom.evidence_conflicts import conflict_hints


def record(identifier, value, **changes):
    item = {
        "record_id": identifier, "source_id": "fixture-source", "chunk_id": "chunk-" + identifier,
        "quote": "Synthetic quotation for " + identifier + ".", "field": "flow_cm_s", "value": value,
        "unit": "cm/s", "scope": "experiment_range", "evidence_status": "reported",
        "review_status": "ai_draft", "reviewer": None, "notes": "Synthetic fixture.",
    }
    item.update(changes)
    return item


def chunks_for(records):
    return [{"chunk_id": r["chunk_id"], "source_id": r["source_id"], "text": r["quote"]} for r in records]


class EvidenceConflictTests(unittest.TestCase):
    def test_value_difference_preserves_scope_and_stages_as_draft_hint(self):
        records = [record("initial", 5, notes="Initial flow."), record("final", 2, notes="Final flow.")]
        hints = conflict_hints(records, chunks_for(records))
        self.assertEqual(len(hints), 1)
        hint = hints[0]
        self.assertEqual(hint["kind"], "reported_value_difference")
        self.assertEqual(hint["record_ids"], ["final", "initial"])
        self.assertEqual(hint["values"], [2, 5])
        self.assertEqual(hint["notes"], ["Final flow.", "Initial flow."])
        self.assertEqual(hint["scopes"], ["experiment_range", "experiment_range"])
        self.assertTrue(hint["requires_scope_review"])
        self.assertEqual(hint["review_status"], "ai_draft")
        self.assertIn("stages", hint["explanation"])

    def test_source_scope_field_and_evidence_status_boundaries(self):
        for changes in ({"source_id": "other-source"}, {"scope": "setup"},
                        {"evidence_status": "proposed"}, {"field": "pressure_kpa", "unit": "kPa"}):
            with self.subTest(changes=changes):
                records = [record("a", 5), record("b", 10, **changes)]
                self.assertEqual(conflict_hints(records, chunks_for(records)), [])

    def test_planned_range_differences_retain_proposed_status(self):
        records = [record("research", {"min": 10, "max": 50}, field="oxygen_percent", unit="%",
                          evidence_status="proposed", notes="Research description."),
                   record("operations", {"min": 10, "max": 40}, field="oxygen_percent", unit="%",
                          evidence_status="proposed", notes="Operations description.")]
        hint = conflict_hints(records, chunks_for(records))[0]
        self.assertEqual(hint["evidence_status"], "proposed")
        self.assertIn("proposed", hint["explanation"])
        self.assertEqual(set(hint["quotes"]), {r["quote"] for r in records})

    def test_equivalent_values_unknowns_and_other_fields_do_not_create_hints(self):
        examples = [(5, 5.0), (5, {"min": 5, "max": 5}),
                    ({"min": 0, "max": 5}, {"max": 5, "min": 0}), (None, 5)]
        for first, second in examples:
            with self.subTest(values=(first, second)):
                records = [record("a", first), record("b", second)]
                self.assertEqual(conflict_hints(records, chunks_for(records)), [])
        records = [record("a", "fuel one", field="fuel", unit=None),
                   record("b", "fuel two", field="fuel", unit=None)]
        self.assertEqual(conflict_hints(records, chunks_for(records)), [])

    def test_geometry_differences_are_review_hints(self):
        records = [record("a", "thin sheet", field="geometry", unit=None),
                   record("b", "rod", field="geometry", unit=None)]
        hint = conflict_hints(records, chunks_for(records))[0]
        self.assertEqual(hint["field"], "geometry")
        self.assertEqual(hint["values"], ["thin sheet", "rod"])

    def test_invalid_quote_or_duplicate_id_is_ignored(self):
        records = [record("a", 1), record("b", 2)]
        chunks = chunks_for(records)
        records[1]["quote"] = "An invented quotation absent from the source."
        self.assertEqual(conflict_hints(records, chunks), [])
        records = [record("a", 1), record("a", 2)]
        self.assertEqual(conflict_hints(records, chunks_for(records)), [])

    def test_generated_hint_keeps_original_review_states_without_promotion(self):
        records = [record("a", 1, review_status="human_reviewed", reviewer="fixture-reviewer"),
                   record("b", 2, review_status="human_reviewed", reviewer="fixture-reviewer")]
        hint = conflict_hints(records, chunks_for(records))[0]
        self.assertEqual(hint["record_review_statuses"], ["human_reviewed", "human_reviewed"])
        self.assertEqual(hint["review_status"], "ai_draft")

    def test_bounded_deterministic_output_preserves_input_and_values(self):
        records = [record(f"r{i:02}", {"min": 0, "max": i + 1}) for i in range(8)]
        chunks = chunks_for(records)
        original = copy.deepcopy((records, chunks))
        hints = conflict_hints(records, chunks)
        self.assertEqual(len(hints), 12)
        self.assertEqual(hints, conflict_hints(list(reversed(records)), list(reversed(chunks))))
        self.assertEqual((records, chunks), original)
        hints[0]["values"][0]["max"] = 999
        self.assertEqual((records, chunks), original)


if __name__ == "__main__":
    unittest.main()
