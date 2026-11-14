import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from axiom.run_records import list_scenarios, load_scenario, save_scenario
from axiom.scenario import assess, catalog, plan


def passage(chunk_id, source_id, text, experiment, locator):
    return {"chunk_id": chunk_id, "source_id": source_id, "text": text,
            "experiment": experiment, "locator": locator,
            "sha256": hashlib.sha256(text.encode()).hexdigest()}


TEXTS = [
    passage("bass-1", "source-bass",
            "BASS-II burned SIBAL fabric sheets in microgravity at 21% oxygen. "
            "The chamber pressure was 101.325 kPa with a forced flow of 20 cm/s.",
            "BASS-II", "PDF page 3"),
    passage("saffire-1", "source-saffire",
            "SAFFIRE tests burned Nomex fabric in microgravity at 26.5% oxygen. "
            "The chamber pressure was 101.325 kPa and the air flow was 25 cm/s.",
            "SAFFIRE", "PDF page 7"),
    passage("flex-1", "source-flex",
            "FLEX studied methanol droplet combustion in microgravity at 21% oxygen.",
            "FLEX", "PDF page 2"),
]


class ScenarioTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "data/processed").mkdir(parents=True)
        (self.root / "data/processed/chunks.jsonl").write_text(
            "\n".join(json.dumps(row) for row in TEXTS), encoding="utf-8")
        (self.root / "data/sources.json").write_text('{"sources": []}', encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def request(self, scenario=None, **changes):
        body = {
            "scenario": scenario if scenario is not None else {
                "gravity": "microgravity", "fuel": "sibal fabric", "geometry": "fabric sheet",
                "oxygen_percent": {"value": 21, "unit": "%"},
                "pressure_kpa": {"value": 101.325, "unit": "kPa"},
                "flow_cm_s": {"value": 30, "unit": "cm/s"},
            },
            "interest": "flame_spread", "save": True,
            "description": "Synthetic test scenario, not a mission specification.",
        }
        body.update(changes)
        return body


class CatalogTests(ScenarioTestCase):
    def test_catalog_describes_only_available_fields_and_the_machine_review_state(self):
        meta = catalog(self.root)
        self.assertEqual(len(meta["fields"]), 10)
        self.assertEqual(meta["corpus"]["documents"], 3)
        self.assertEqual(meta["corpus"]["investigations"][0]["investigation_id"], "BASS-II")
        self.assertEqual(meta["corpus"]["review_status"], "machine_extracted_not_human_reviewed")
        self.assertTrue(meta["presets"])
        for preset in meta["presets"]:
            self.assertTrue(preset["synthetic"])
            self.assertIn("synthetic", preset["basis"].lower())


class AssessmentTests(ScenarioTestCase):
    def test_assessment_returns_traceable_comparisons_gaps_and_proposals(self):
        result = assess(self.root, self.request())
        self.assertTrue(result["saved_locally"])
        self.assertEqual(result["coverage"]["denominator"], 18)
        self.assertEqual(result["scenario_fields"],
                         ["gravity", "fuel", "geometry", "oxygen_percent", "pressure_kpa", "flow_cm_s"])
        self.assertTrue(result["gaps"])
        self.assertTrue(result["proposals"])
        self.assertEqual(result["proposals"][0]["label"][:7], "AXIOM P")
        for investigation in result["investigations"]:
            for parameter in investigation["parameters"]:
                for record in parameter["records"] + parameter["unqualified_records"]:
                    self.assertIn("quote", record)
                    self.assertIn("source_id", record)
                    self.assertIn("chunk_id", record)
        self.assertIn("not a fire-risk prediction", result["assessment_scope"].lower())

    def test_changing_one_parameter_changes_the_evidence_comparison(self):
        base = self.request()["scenario"]
        first = assess(self.root, self.request({**base, "flow_cm_s": {"value": 20, "unit": "cm/s"}}))
        second = assess(self.root, self.request({**base, "flow_cm_s": {"value": 80, "unit": "cm/s"}}))
        self.assertNotEqual(first["coverage"]["alignment_percent"], second["coverage"]["alignment_percent"])
        self.assertNotEqual([gap["kind"] for gap in first["gaps"]],
                            [gap["kind"] for gap in second["gaps"]])
        self.assertNotEqual([row["proposal_id"] for row in first["proposals"]],
                            [row["proposal_id"] for row in second["proposals"]])
        self.assertNotEqual(first["scenario_id"], second["scenario_id"])

    def test_unknown_parameter_stays_out_of_the_comparison_instead_of_matching(self):
        result = assess(self.root, self.request({"gravity": "microgravity"}))
        self.assertEqual(result["scenario_fields"], ["gravity"])
        self.assertEqual(result["coverage"]["denominator"], 3)
        parameter = result["investigations"][0]["parameters"][0]
        self.assertEqual(parameter["classification"], "exact_match")

    def test_empty_scenario_is_not_assessed_and_does_not_invent_proposals(self):
        result = assess(self.root, self.request({}))
        self.assertEqual(result["scenario_fields"], [])
        self.assertEqual(result["coverage"]["denominator"], 0)
        self.assertIsNone(result["coverage"]["documented_percent"])
        self.assertEqual(result["gaps"], [])
        self.assertEqual(result["proposals"], [])

    def test_invalid_requests_fail_closed(self):
        invalid = [
            {"scenario": {"unknown": "value"}},
            {"scenario": {"oxygen_percent": 21}},
            {"scenario": {"oxygen_percent": {"value": 21, "unit": "furlong"}}},
            {"scenario": {"oxygen_percent": {"value": 150, "unit": "%"}}},
            {"scenario": {"pressure_kpa": {"value": -1, "unit": "kPa"}}},
            {"interest": "explosion"},
            {"save": "yes"},
            {"description": "x" * 2001},
            {"extra": True},
        ]
        for body in invalid:
            with self.subTest(body=body), self.assertRaises(ValueError):
                assess(self.root, body)

    def test_save_false_does_not_create_a_local_record(self):
        result = assess(self.root, self.request(save=False))
        self.assertFalse(result["saved_locally"])
        self.assertFalse((self.root / "runs/scenarios" / (result["scenario_id"] + ".json")).exists())


class PersistenceTests(ScenarioTestCase):
    def test_saved_assessment_can_be_listed_reloaded_and_planned_without_new_retrieval(self):
        result = assess(self.root, self.request())
        identifier = result["scenario_id"]
        reopened = load_scenario(self.root, identifier)
        self.assertEqual(reopened, result)
        listed = list_scenarios(self.root)
        self.assertEqual(listed["total"], 1)
        self.assertEqual(listed["scenarios"][0]["scenario_id"], identifier)
        self.assertEqual(listed["scenarios"][0]["coverage_percent"],
                         result["coverage"]["documented_percent"])
        self.assertEqual(listed["scenarios"][0]["alignment_percent"],
                         result["coverage"]["alignment_percent"])
        planned = plan(self.root, {"scenario_id": identifier})
        self.assertTrue(planned["reused_assessment"])
        self.assertEqual(planned["target"], result["target"])
        self.assertEqual(planned["proposals"], result["proposals"])
        self.assertIn("NOT EXECUTED", planned["label"])

    def test_plan_can_filter_by_gap(self):
        result = assess(self.root, self.request())
        gap_id = result["gaps"][0]["gap_id"]
        planned = plan(self.root, {"scenario_id": result["scenario_id"], "gap_ids": [gap_id]})
        self.assertTrue(all(row["gap_id"] == gap_id for row in planned["proposals"]))
        self.assertTrue(all(row["gap_id"] == gap_id for row in planned["gaps"]))

    def test_listing_supports_search_and_pagination(self):
        first = assess(self.root, self.request(description="SIBAL fabric case"))
        second = assess(self.root, self.request(description="Nomex case"))
        matched = list_scenarios(self.root, query="SIBAL")
        self.assertEqual(matched["total"], 1)
        self.assertEqual(matched["scenarios"][0]["scenario_id"], first["scenario_id"])
        page_one = list_scenarios(self.root, limit=1, offset=0)
        page_two = list_scenarios(self.root, limit=1, offset=1)
        self.assertEqual(page_one["total"], 2)
        self.assertEqual({page_one["scenarios"][0]["scenario_id"], page_two["scenarios"][0]["scenario_id"]},
                         {first["scenario_id"], second["scenario_id"]})
        for bad in ({"limit": 0}, {"limit": 101}, {"offset": -1}, {"limit": "1"}, {"query": "x" * 501}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                list_scenarios(self.root, **bad)

    def test_save_and_load_reject_malformed_records_and_paths(self):
        with self.assertRaises(ValueError):
            save_scenario(self.root, {"scenario_id": "missing-coverage"})
        with self.assertRaises(FileNotFoundError):
            load_scenario(self.root, "absent")
        for bad in ("../secret", "nested/id", ""):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                load_scenario(self.root, bad)


if __name__ == "__main__":
    unittest.main()
