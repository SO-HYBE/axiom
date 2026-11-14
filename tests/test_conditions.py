"""Synthetic condition fixtures test accounting and validation, not NASA science."""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from axiom.conditions import normalize_quote, validate_records


def chunk():
    return {"source_id": "synthetic-source", "chunk_id": "synthetic-1",
            "text": "Synthetic fixture only. Proposed flow is 0 to 5 cm/s. Signal is 1 mW. Fuel is fixture plastic."}


def record(**changes):
    item = {"record_id": "fixture-condition-1", "source_id": "synthetic-source", "chunk_id": "synthetic-1",
            "quote": "Proposed flow is 0 to 5 cm/s.", "field": "flow_cm_s", "value": {"min": 0, "max": 5},
            "unit": "cm/s", "scope": "experiment_range", "evidence_status": "proposed",
            "review_status": "ai_draft", "reviewer": None, "notes": "Synthetic fixture; not a scientific finding."}
    item.update(changes)
    return item


class ConditionTests(unittest.TestCase):
    def assert_invalid(self, item, code):
        report = validate_records([item], [chunk()])
        self.assertEqual(report["invalid_count"], 1)
        self.assertIn(code, {e["code"] for e in report["errors"]})

    def test_valid_draft_preserves_status_scope_and_input(self):
        records = [record()]
        original = copy.deepcopy(records)
        report = validate_records(records, [chunk()])
        self.assertEqual(report["valid_count"], 1)
        self.assertEqual(report["valid_by_review_status"]["ai_draft"], 1)
        self.assertEqual(report["valid_by_evidence_status"]["proposed"], 1)
        self.assertFalse(report["automatic_approval"])
        self.assertEqual(records, original)

    def test_whitespace_normalized_but_unit_case_preserved(self):
        self.assertEqual(normalize_quote(" a\n b "), "a b")
        self.assertEqual(validate_records([record(quote="Proposed flow\n is 0 to 5 cm/s.")], [chunk()])["valid_count"], 1)
        self.assert_invalid(record(quote="Signal is 1 MW."), "quote_mismatch")

    def test_wrong_source_or_missing_chunk_rejected(self):
        self.assert_invalid(record(source_id="wrong-source"), "source_mismatch")
        self.assert_invalid(record(chunk_id="missing"), "unknown_chunk")

    def test_unknown_stays_null_not_zero(self):
        item = record(value=None)
        report = validate_records([item], [chunk()])
        self.assertEqual(report["valid_count"], 1)
        self.assertEqual(report["unknown_value_count"], 1)
        self.assertIsNone(item["value"])
        self.assertEqual(validate_records([record(value=0)], [chunk()])["unknown_value_count"], 0)

    def test_numeric_strings_bool_nonfinite_and_bounds_rejected(self):
        for value in ("5", True, float("nan"), float("inf"), -1):
            with self.subTest(value=value):
                self.assert_invalid(record(value=value), "invalid_value")
        self.assert_invalid(record(field="oxygen_percent", unit="%", value=101), "invalid_value")
        self.assert_invalid(record(field="pressure_kpa", unit="kPa", value=0), "invalid_value")

    def test_range_order_and_shape_rejected(self):
        self.assert_invalid(record(value={"min": 5, "max": 0}), "reversed_range")
        self.assert_invalid(record(value={"min": 0}), "invalid_range")
        self.assert_invalid(record(value={"min": 0, "max": "5"}), "invalid_range")
        self.assert_invalid(record(value={"min": 0, "max": 5, "unit": "cm/s"}), "invalid_range")

    def test_unit_conversion_not_assumed(self):
        self.assert_invalid(record(unit="m/s"), "invalid_unit")
        self.assert_invalid(record(field="pressure_kpa", value=1, unit="atm"), "invalid_unit")

    def test_text_fields_and_units(self):
        item = record(field="fuel", value="fixture plastic", unit=None, quote="Fuel is fixture plastic.")
        self.assertEqual(validate_records([item], [chunk()])["valid_count"], 1)
        self.assert_invalid(record(field="fuel", value=0, unit=None), "invalid_value")
        self.assert_invalid(record(field="fuel", value="fixture plastic", unit="%"), "invalid_unit")

    def test_review_status_requires_reviewer_entry_without_authenticating_it(self):
        self.assert_invalid(record(review_status="human_reviewed"), "missing_reviewer")
        self.assert_invalid(record(reviewer="An AI draft cannot have reviewer"), "draft_reviewer")
        item = record(review_status="human_reviewed", reviewer="synthetic-reviewer")
        report = validate_records([item], [chunk()])
        self.assertEqual(report["valid_by_review_status"]["human_reviewed"], 1)
        self.assertFalse(report["automatic_approval"])

    def test_scope_status_and_required_fields(self):
        self.assert_invalid(record(scope="universal"), "invalid_scope")
        self.assert_invalid(record(evidence_status="proven"), "invalid_evidence_status")
        self.assert_invalid(record(review_status="approved"), "invalid_review_status")
        item = record()
        del item["value"]
        self.assert_invalid(item, "missing_fields")
        self.assert_invalid(record(extra_flag=True), "unknown_fields")

    def test_all_duplicate_records_rejected(self):
        report = validate_records([record(), record()], [chunk()])
        self.assertEqual(report["invalid_count"], 2)
        self.assertEqual(report["valid_count"], 0)

    def test_malformed_corpus_fails_closed(self):
        report = validate_records([record()], [chunk(), chunk()])
        self.assertEqual(report["valid_count"], 0)
        self.assertEqual(report["corpus_errors"][0]["code"], "duplicate_chunk_id")
        self.assertEqual(validate_records([record()], {"synthetic-1": chunk()})["valid_count"], 1)
        self.assertEqual(validate_records([record()], {"wrong-key": chunk()})["valid_count"], 0)

    def test_malformed_records_produce_report_not_crash(self):
        for item in (None, [], {}, record(field=[]), record(chunk_id=[]), record(record_id=[])):
            with self.subTest(item=item):
                self.assertEqual(validate_records([item], [chunk()])["invalid_count"], 1)

    def test_exact_quote_does_not_approve_extraction_meaning(self):
        # A wrong interpretation can pass structural validation. This disclosed
        # limitation must not be hidden behind claims of scientific validation.
        item = record(value=4)
        report = validate_records([item], [chunk()])
        self.assertEqual(report["valid_count"], 1)
        self.assertEqual(report["validation_scope"], "structure_and_quote_provenance_only")
        self.assertEqual(item["review_status"], "ai_draft")

    def test_cli_success_and_failure_exit_codes(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("AXIOM_TEST_TMPDIR")) as directory:
            root = Path(directory)
            (root / "data/processed").mkdir(parents=True)
            (root / "data/processed/chunks.jsonl").write_text(json.dumps(chunk()) + "\n", encoding="utf-8")
            path = root / "data/conditions.jsonl"
            path.write_text(json.dumps(record()) + "\n", encoding="utf-8")
            command = [sys.executable, "-m", "axiom.conditions", "--root", str(root)]
            success = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(success.returncode, 0, success.stderr)
            self.assertEqual(json.loads(success.stdout)["valid_count"], 1)
            path.write_text(json.dumps(record(quote="invented quote")), encoding="utf-8")
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 1)
            path.write_text("{broken json}", encoding="utf-8")
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 2)


if __name__ == "__main__":
    unittest.main()
