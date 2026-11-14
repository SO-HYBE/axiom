"""Tests for the deterministic AXIOM applicability engine and temperature field."""
import unittest
from pathlib import Path

from axiom.applicability import OVERALL_ORDER, summarize
from axiom.experiment_metadata import extract_chunk, investigations
from axiom.research import load_chunks
from axiom.scenario import assess, catalog
from axiom.transferability import normalize_scenario

ROOT = Path(__file__).resolve().parents[1]

UNITS = {"oxygen_percent": "%", "pressure_kpa": "kPa", "flow_cm_s": "cm/s", "temperature_k": "K"}


def parameter(field, classification, values=(), unqualified=()):
    def record(value):
        return {"source_id": "s", "chunk_id": "c", "locator": "p.1", "quote": "q",
                "value": value, "unit": UNITS.get(field), "evidence_status": "reported",
                "scope": "individual_test"}

    return {"field": field, "label": field, "scenario_value": None, "unit": UNITS.get(field),
            "classification": classification, "reason": "", "basis": "reported_test_condition",
            "records": [record(value) for value in values],
            "unqualified_records": [record(value) for value in unqualified]}


def investigation(identifier, parameters, evidence_type="direct"):
    return {"investigation_id": identifier, "relevance": {"evidence_type": evidence_type},
            "parameters": parameters}


def engine(target, *groups):
    return summarize({"target": target, "investigations": list(groups)})


class OverallOutcomeTests(unittest.TestCase):
    def test_one_direct_investigation_covering_every_field_is_within_scope(self):
        result = engine(
            {"gravity": "microgravity", "oxygen_percent": 21.0},
            investigation("A", [parameter("gravity", "exact_match", ["microgravity"]),
                                parameter("oxygen_percent", "partial_match", [{"min": 18, "max": 30}])]))
        self.assertEqual(result["overall"], "WITHIN_DOCUMENTED_SCOPE")
        self.assertEqual(result["full_coverage_investigations"], ["A"])
        self.assertTrue(result["necessary_not_sufficient"])

    def test_missing_field_is_insufficient_information_not_a_match(self):
        result = engine({"gravity": "microgravity", "oxygen_percent": 21.0},
                        investigation("A", [parameter("gravity", "exact_match", ["microgravity"])]))
        self.assertEqual(result["overall"], "INSUFFICIENT_INFORMATION")
        row = next(row for row in result["field_outcomes"] if row["field"] == "oxygen_percent")
        self.assertEqual(row["outcome"], "UNKNOWN")
        self.assertEqual(row["missing_status"], "missing")

    def test_unqualified_mention_is_ambiguous_and_never_a_match(self):
        result = engine({"pressure_kpa": 50.0},
                        investigation("A", [parameter("pressure_kpa", "unknown", unqualified=[50.0])]))
        self.assertEqual(result["overall"], "INSUFFICIENT_INFORMATION")
        row = result["field_outcomes"][0]
        self.assertEqual(row["missing_status"], "ambiguous_present_but_unqualified")
        self.assertIn("not a qualified", row["reason"])

    def test_mismatch_without_a_matching_investigation_is_condition_mismatch(self):
        result = engine({"oxygen_percent": 15.0},
                        investigation("A", [parameter("oxygen_percent", "mismatch", [30.0])]))
        self.assertEqual(result["overall"], "CONDITION_MISMATCH")
        self.assertEqual(result["mismatch_fields"], ["oxygen_percent"])

    def test_match_and_mismatch_across_direct_investigations_is_conflicting(self):
        result = engine({"oxygen_percent": 21.0},
                        investigation("A", [parameter("oxygen_percent", "exact_match", [21.0])]),
                        investigation("B", [parameter("oxygen_percent", "mismatch", [30.0])]))
        self.assertEqual(result["overall"], "CONFLICTING_EVIDENCE")
        self.assertEqual(result["conflict_fields"], ["oxygen_percent"])

    def test_conflicting_evidence_precedes_a_scope_claim(self):
        result = engine(
            {"gravity": "microgravity", "oxygen_percent": 21.0},
            investigation("A", [parameter("gravity", "exact_match", ["microgravity"]),
                                parameter("oxygen_percent", "exact_match", [21.0])]),
            investigation("B", [parameter("gravity", "mismatch", ["terrestrial"]),
                                parameter("oxygen_percent", "mismatch", [30.0])]))
        self.assertEqual(result["overall"], "CONFLICTING_EVIDENCE")
        self.assertEqual(result["full_coverage_investigations"], [])
        self.assertEqual(result["precedence"], list(OVERALL_ORDER))

    def test_conflicting_evidence_precedes_condition_mismatch(self):
        result = engine(
            {"gravity": "microgravity", "oxygen_percent": 21.0},
            investigation("A", [parameter("gravity", "exact_match", ["microgravity"]),
                                parameter("oxygen_percent", "mismatch", [30.0])]),
            investigation("B", [parameter("oxygen_percent", "exact_match", [21.0])]))
        self.assertEqual(result["overall"], "CONFLICTING_EVIDENCE")

    def test_individually_matching_fields_without_one_full_investigation_are_insufficient(self):
        result = engine({"gravity": "microgravity", "oxygen_percent": 21.0},
                        investigation("A", [parameter("gravity", "exact_match", ["microgravity"])]),
                        investigation("B", [parameter("oxygen_percent", "exact_match", [21.0])]))
        self.assertEqual(result["overall"], "INSUFFICIENT_INFORMATION")
        self.assertEqual(result["full_coverage_investigations"], [])

    def test_contextual_evidence_cannot_establish_scope(self):
        result = engine({"gravity": "terrestrial"},
                        investigation("A", [parameter("gravity", "exact_match", ["terrestrial"])],
                                      evidence_type="contextual"))
        self.assertEqual(result["overall"], "INSUFFICIENT_INFORMATION")
        self.assertEqual(result["full_coverage_investigations"], [])

    def test_range_endpoints_are_inclusive_boundaries(self):
        low = engine({"oxygen_percent": 18.0},
                     investigation("A", [parameter("oxygen_percent", "partial_match",
                                                   [{"min": 18, "max": 30}])]))
        high = engine({"oxygen_percent": 30.0},
                      investigation("A", [parameter("oxygen_percent", "partial_match",
                                                    [{"min": 18, "max": 30}])]))
        outside = engine({"oxygen_percent": 30.001},
                         investigation("A", [parameter("oxygen_percent", "mismatch",
                                                       [{"min": 18, "max": 30}])]))
        self.assertEqual(low["overall"], "WITHIN_DOCUMENTED_SCOPE")
        self.assertEqual(high["overall"], "WITHIN_DOCUMENTED_SCOPE")
        self.assertEqual(outside["overall"], "CONDITION_MISMATCH")

    def test_no_specified_field_is_insufficient_and_invents_nothing(self):
        result = engine({})
        self.assertEqual(result["overall"], "INSUFFICIENT_INFORMATION")
        self.assertEqual(result["logical_fields"], [])
        self.assertTrue(result["limitations"])

    def test_logical_fields_reuse_documented_attributes_without_inventing_values(self):
        result = engine(
            {"fuel": "pmma", "apparatus": "cir"},
            investigation("A", [parameter("fuel", "exact_match", ["pmma"]),
                                parameter("apparatus", "exact_match", ["cir"])]))
        mapped = {row["key"]: row["source_field"] for row in result["logical_fields"]}
        self.assertEqual(mapped["fuel"], "fuel")
        self.assertEqual(mapped["material"], "fuel")
        self.assertEqual(mapped["configuration"], "apparatus")
        material = next(row for row in result["logical_fields"] if row["key"] == "material")
        self.assertIn("Shares the documented", material["note"])
        self.assertEqual(result["overall"], "WITHIN_DOCUMENTED_SCOPE")

    def test_evidence_items_carry_quote_locator_and_validation_status(self):
        result = engine({"oxygen_percent": 21.0},
                        investigation("A", [parameter("oxygen_percent", "exact_match", [21.0])]))
        evidence = result["field_outcomes"][0]["evidence"]
        self.assertEqual(evidence[0]["locator"], "p.1")
        self.assertEqual(evidence[0]["quote"], "q")
        self.assertEqual(evidence[0]["validation_status"], "automatic")


class TemperatureUnitTests(unittest.TestCase):
    def test_affine_conversion_from_celsius_and_fahrenheit(self):
        target, original = normalize_scenario(
            {"temperature_k": {"value": 25, "unit": "°C"},
             "pressure_kpa": {"value": 1, "unit": "atm"}})
        self.assertAlmostEqual(target["temperature_k"], 298.15, places=6)
        self.assertEqual(original["temperature_k"], {"value": 25, "unit": "°C"})
        fahrenheit, _ = normalize_scenario({"temperature_k": {"value": 32, "unit": "°F"}})
        self.assertAlmostEqual(fahrenheit["temperature_k"], 273.15, places=6)

    def test_kelvin_is_identity(self):
        target, _ = normalize_scenario({"temperature_k": {"value": 300, "unit": "K"}})
        self.assertEqual(target["temperature_k"], 300.0)

    def test_invalid_temperature_values_are_rejected(self):
        for scenario in ({"temperature_k": {"value": -5, "unit": "K"}},
                         {"temperature_k": {"value": 0, "unit": "K"}},
                         {"temperature_k": {"value": -273.15, "unit": "°C"}},
                         {"temperature_k": {"value": 300, "unit": "R"}},
                         {"temperature_k": 300}):
            with self.subTest(scenario=scenario):
                with self.assertRaises(ValueError):
                    normalize_scenario(scenario)


class TemperatureExtractionTests(unittest.TestCase):
    def chunk(self, text):
        return {"chunk_id": "c1", "source_id": "s1", "text": text, "experiment": "T",
                "locator": "p.1"}

    def temperature_records(self, text):
        return [row for row in extract_chunk(self.chunk(text)) if row["field"] == "temperature_k"]

    def test_reported_chamber_temperature_is_extracted_in_kelvin(self):
        rows = self.temperature_records(
            "The chamber temperature was held at 25 °C during every test.")
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["value"], 298.15, places=6)
        self.assertEqual(rows[0]["unit"], "K")
        self.assertEqual(rows[0]["scope"], "individual_test")
        self.assertEqual(rows[0]["review_status"], "machine_extracted_not_human_reviewed")

    def test_flame_and_outlet_temperatures_are_not_test_conditions(self):
        self.assertEqual(self.temperature_records(
            "Flame temperatures are low, about 800 K, in this configuration."), [])
        self.assertEqual(self.temperature_records(
            "The temperature at the outlet does not exceed 45 °C."), [])

    def test_sentence_without_a_temperature_word_is_not_extracted(self):
        self.assertEqual(self.temperature_records("The sample was 500 K hot."), [])

    def test_shipped_corpus_keeps_only_a_reported_initial_temperature(self):
        groups = investigations(load_chunks(ROOT))
        rows = [row for group in groups for row in group["records"]
                if row["field"] == "temperature_k"]
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["value"], 297.25, places=6)
        self.assertEqual(rows[0]["unit"], "K")
        self.assertIn("initial temperature", rows[0]["quote"])
        self.assertTrue(rows[0]["matching_eligible"])


class ScenarioIntegrationTests(unittest.TestCase):
    def test_catalog_exposes_temperature_with_its_units(self):
        meta = catalog(ROOT)
        field = next(row for row in meta["fields"] if row["field"] == "temperature_k")
        self.assertEqual(field["type"], "numeric")
        self.assertEqual(field["canonical_unit"], "K")
        self.assertIn("°C", field["units"])

    def test_assessment_includes_the_engine_block(self):
        result = assess(ROOT, {"scenario": {"gravity": "microgravity", "fuel": "SIBAL fabric"},
                               "save": False})
        block = result["applicability_engine"]
        self.assertEqual(block["schema_version"], "axiom-applicability-v1")
        self.assertIn(block["overall"], OVERALL_ORDER)
        self.assertEqual(set(block["specified_fields"]), {"gravity", "fuel"})
        self.assertTrue(block["necessary_not_sufficient"])


if __name__ == "__main__":
    unittest.main()
