"""Tests for the extraction-validation harness and its fixed sample rules."""
import json
import re
import unittest
from pathlib import Path

from axiom.extraction_validation import (NUMERIC_FIELDS, TOLERANCES, evaluate_labels,
                                         select_sample)

ROOT = Path(__file__).resolve().parents[1]


def label(field, value, eligible=True, quote="chamber pressure was 1 atm"):
    return {"field": field, "value": value, "eligible": eligible, "quote": quote,
            "reported": str(value)}


def record(field, value, eligible=True):
    return {"field": field, "value": value, "matching_eligible": eligible}


def entry(text, labels, chunk_id="c1"):
    return {"chunk": {"chunk_id": chunk_id, "source_id": "s1", "experiment": "T",
                      "locator": "p.1", "text": text}, "labels": labels}


class QuoteIntegrityTests(unittest.TestCase):
    def test_a_label_whose_quote_is_absent_is_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_labels([entry("chamber pressure was 1 atm",
                                   [label("pressure_kpa", 101.325, quote="not in the text")])])

    def test_a_label_whose_quote_is_present_is_accepted(self):
        result = evaluate_labels([entry("chamber pressure was 1 atm",
                                        [label("pressure_kpa", 101.325)])])
        self.assertEqual(result["overall"]["labeled_eligible"], 1)


class ScoringTests(unittest.TestCase):
    def test_matching_and_mismatch_are_counted_per_field(self):
        labels = [label("pressure_kpa", 101.325),
                  label("oxygen_percent", 21.0),
                  label("flow_cm_s", 10.0),
                  label("flow_cm_s", 2.0, eligible=False)]
        text = "chamber pressure was 1 atm"
        def extractor(chunk):
            return [record("pressure_kpa", 101.325), record("oxygen_percent", 21.0),
                    record("flow_cm_s", 2.0), record("flow_cm_s", 99.0)]
        result = evaluate_labels([entry(text, labels)], extractor=extractor)
        per_field = result["per_field"]
        self.assertEqual(per_field["pressure_kpa"]["true_positives"], 1)
        self.assertEqual(per_field["pressure_kpa"]["false_negatives"], 0)
        self.assertEqual(per_field["oxygen_percent"]["true_positives"], 1)
        self.assertEqual(per_field["flow_cm_s"]["true_positives"], 0)
        self.assertEqual(per_field["flow_cm_s"]["false_positives"], 2)
        self.assertEqual(per_field["flow_cm_s"]["false_negatives"], 1)
        self.assertEqual(per_field["flow_cm_s"]["exclusion_violations"], 1)
        self.assertEqual(per_field["temperature_k"]["labeled_eligible"], 0)
        self.assertIsNone(per_field["temperature_k"]["precision"])

    def test_overall_precision_recall_and_f1_are_derived(self):
        labels = [label("pressure_kpa", 101.325)]
        result = evaluate_labels([entry("chamber pressure was 1 atm", labels)],
                                 extractor=lambda chunk: [record("pressure_kpa", 101.325),
                                                          record("pressure_kpa", 50.0)])
        overall = result["overall"]
        self.assertEqual((overall["true_positives"], overall["false_positives"],
                          overall["false_negatives"]), (1, 1, 0))
        self.assertEqual(overall["precision"], 0.5)
        self.assertEqual(overall["recall"], 1.0)
        self.assertEqual(overall["f1"], round(2 * 0.5 * 1.0 / 1.5, 4))

    def test_tolerance_is_fixed_before_the_run(self):
        self.assertEqual(TOLERANCES["pressure_kpa"], 0.5)
        label_row = label("pressure_kpa", 101.325)
        inside = evaluate_labels([entry("chamber pressure was 1 atm", [label_row])],
                                 extractor=lambda chunk: [record("pressure_kpa", 101.8)])
        outside = evaluate_labels([entry("chamber pressure was 1 atm", [label_row])],
                                  extractor=lambda chunk: [record("pressure_kpa", 101.9)])
        self.assertEqual(inside["overall"]["true_positives"], 1)
        self.assertEqual(outside["overall"]["true_positives"], 0)

    def test_identical_values_are_deduplicated_on_both_sides(self):
        labels = [label("pressure_kpa", 101.325)]
        def extractor(chunk):
            return [record("pressure_kpa", 101.325), record("pressure_kpa", 101.325)]
        deduped = evaluate_labels([entry("chamber pressure was 1 atm", labels)],
                                  extractor=extractor)
        raw = evaluate_labels([entry("chamber pressure was 1 atm", labels)],
                              extractor=extractor, dedupe=False)
        self.assertEqual(deduped["overall"]["false_positives"], 0)
        self.assertEqual(deduped["overall"]["true_positives"], 1)
        self.assertGreater(raw["overall"]["false_positives"], 0)

    def test_an_empty_scope_reports_null_rates_not_zero(self):
        result = evaluate_labels([entry("nothing numeric here", [])])
        overall = result["overall"]
        self.assertEqual(overall["true_positives"] + overall["false_positives"]
                         + overall["false_negatives"], 0)
        self.assertIsNone(overall["precision"])
        self.assertIsNone(overall["recall"])
        self.assertIsNone(overall["f1"])

    def test_excluded_records_are_not_counted_as_correct_conditions(self):
        labels = [label("temperature_k", 297.25, eligible=True)]
        def extractor(chunk):
            return [record("temperature_k", 297.25, eligible=False)]
        result = evaluate_labels([entry("chamber pressure was 1 atm", labels)],
                                 extractor=extractor)
        self.assertEqual(result["overall"]["true_positives"], 0)
        self.assertEqual(result["overall"]["false_negatives"], 1)


class SampleRuleTests(unittest.TestCase):
    def test_selection_is_deterministic_and_carries_no_extracted_conditions(self):
        first = select_sample(ROOT)
        second = select_sample(ROOT)
        self.assertEqual(first, second)
        self.assertTrue(first)
        for row in first:
            self.assertNotIn("conditions", row)
            self.assertTrue(row["text"])
            self.assertTrue(row["locator"])

    def test_every_selected_chunk_matches_the_rule_that_selected_it(self):
        patterns = {
            "temperature": re.compile(r"\d+(?:\.\d+)?\s*(?:K|°C|°F)\b"),
            "pressure": re.compile(r"\d+(?:\.\d+)?\s*(?:atm|kPa|Pa|bar|torr|mmHg|psi)\b", re.I),
            "flow": re.compile(r"\d+(?:\.\d+)?\s*(?:cm/s|mm/s|m/s)\b", re.I),
            "oxygen": re.compile(r"\d+(?:\.\d+)?\s*(?:%|percent)", re.I),
        }
        for row in select_sample(ROOT):
            for rule in row["rules"]:
                if rule == "exclusion_control":
                    continue
                self.assertRegex(row["text"], patterns[rule])

    def test_sample_is_bounded_and_covers_every_rule(self):
        sample = select_sample(ROOT)
        self.assertLessEqual(len(sample), 40)
        rules = {rule for row in sample for rule in row["rules"]}
        for rule in ("temperature", "pressure", "flow", "oxygen"):
            self.assertIn(rule, rules)


if __name__ == "__main__":
    unittest.main()
