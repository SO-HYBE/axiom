"""Release-integrity tests against the corpus and files actually shipped in this repository.

These tests exist because the repository migration is itself a change: it must
not silently drop a source, promote an unknown condition to a match, invent a
proposal value, or ship a credential.
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from axiom.research import load_chunks
from axiom.run_records import load_scenario
from axiom.scenario import PRESETS, assess, catalog, plan
from axiom.transferability import FIELDS, normalize_scenario

ROOT = Path(__file__).resolve().parents[1]
CLASSIFICATIONS = {"exact_match", "partial_match", "mismatch", "unknown"}


def _collapse(text):
    return " ".join(text.split()).casefold()


def _chunk_index():
    return {chunk["chunk_id"]: chunk for chunk in load_chunks(ROOT)}


class ShippedCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chunks = load_chunks(ROOT)
        cls.inventory = json.loads((ROOT / "data/sources.json").read_text(encoding="utf-8"))["sources"]
        cls.ingested = {chunk["source_id"] for chunk in cls.chunks}

    def test_core_corpus_keeps_twelve_ingested_documents_and_294_passages(self):
        self.assertEqual(12, len(self.ingested))
        self.assertEqual(294, len(self.chunks))
        manifest = json.loads((ROOT / "data/processed/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(294, manifest["chunk_count"])

    def test_every_ingested_source_is_declared_public_use_in_the_inventory(self):
        by_id = {source["source_id"]: source for source in self.inventory}
        for identifier in self.ingested:
            self.assertIn(identifier, by_id)
            self.assertEqual("allowed", by_id[identifier]["permission_status"], identifier)
            self.assertTrue(by_id[identifier]["url"].startswith("https://"), identifier)

    def test_inventory_only_review_required_sources_are_never_ingested(self):
        review = {source["source_id"] for source in self.inventory
                  if source.get("permission_status") == "review_required"}
        self.assertTrue(review)
        self.assertFalse(review & self.ingested)
        self.assertEqual(
            {"ntrs-20210011385", "ntrs-20240002981", "ntrs-20210017780"}, review)

    def test_condition_metadata_is_marked_machine_extracted(self):
        metadata = catalog(ROOT)
        self.assertEqual(12, metadata["corpus"]["documents"])
        self.assertEqual(294, metadata["corpus"]["passages"])
        self.assertEqual("machine_extracted_not_human_reviewed", metadata["corpus"]["review_status"])
        self.assertEqual(10, len(metadata["fields"]))
        self.assertGreater(metadata["corpus"]["condition_records"], 0)

    def test_catalog_lists_only_reported_values_with_source_links(self):
        metadata = catalog(ROOT)
        chunk_sources = {chunk["chunk_id"]: chunk["source_id"] for chunk in self.chunks}
        for field in metadata["fields"]:
            for row in field["documented_values"]:
                self.assertIn(row["source_id"], self.ingested)
                self.assertIsNotNone(row["value"])

    def test_unknown_classification_never_carries_evidence(self):
        result = assess(ROOT, {"scenario": dict(PRESETS[0]["scenario"]),
                               "interest": PRESETS[0]["interest"], "save": False})
        observed = set()
        for investigation in result["investigations"]:
            for parameter in investigation["parameters"]:
                observed.add(parameter["classification"])
                if parameter["classification"] == "unknown":
                    self.assertEqual([], parameter["records"])
                    self.assertIn(parameter["basis"],
                                  {"no_qualified_condition", "not_documented_in_available_corpus"})
        self.assertTrue(observed <= CLASSIFICATIONS)
        self.assertIn("unknown", observed)

    def test_every_quoted_condition_comes_from_the_chunk_it_cites(self):
        index = _chunk_index()
        result = assess(ROOT, {"scenario": dict(PRESETS[0]["scenario"]),
                               "interest": PRESETS[0]["interest"], "save": False})
        checked = 0
        for investigation in result["investigations"]:
            for parameter in investigation["parameters"]:
                for record in parameter["records"] + parameter["unqualified_records"]:
                    chunk = index[record["chunk_id"]]
                    self.assertEqual(chunk["source_id"], record["source_id"])
                    self.assertIn(_collapse(record["quote"]), _collapse(chunk["text"]))
                    self.assertTrue(record["locator"])
                    checked += 1
        self.assertGreater(checked, 0)

    def test_proposals_are_bounded_labelled_and_traceable(self):
        result = assess(ROOT, {"scenario": dict(PRESETS[0]["scenario"]),
                               "interest": PRESETS[0]["interest"], "save": False})
        self.assertGreaterEqual(len(result["proposals"]), 1)
        self.assertLessEqual(len(result["proposals"]), 3)
        index = _chunk_index()
        for proposal in result["proposals"]:
            self.assertIn("PROPOSED", proposal["label"])
            self.assertIn("NOT EXECUTED", proposal["label"])
            self.assertTrue(proposal["research_question"].endswith("?"))
            self.assertTrue(proposal["hypothesis"].startswith("Hypothesis (proposed, not observed)"))
            self.assertTrue(proposal["independent_variables"])
            self.assertTrue(proposal["controlled_variables"])
            self.assertTrue(proposal["dependent_variables"])
            self.assertEqual("documented_conditions_in_available_corpus",
                             proposal["scientific_motivation"]["basis"])
            for citation in proposal["scientific_motivation"]["evidence"]:
                chunk = index[citation["chunk_id"]]
                self.assertEqual(chunk["source_id"], citation["source_id"])
                self.assertIn(_collapse(citation["quote"]), _collapse(chunk["text"]))
            for value in proposal["proposed_values"]:
                self.assertEqual("user_scenario_value_not_measured", value["status"])

    def test_proposals_do_not_add_confidence_scores_or_risk_predictions(self):
        result = assess(ROOT, {"scenario": dict(PRESETS[0]["scenario"]),
                               "interest": PRESETS[0]["interest"], "save": False})
        blob = json.dumps(result["proposals"]).lower()
        for forbidden in ("confidence_score", "fire_risk", "probability_of_ignition"):
            self.assertNotIn(forbidden, blob)

    def test_coverage_reports_documented_and_alignment_separately(self):
        result = assess(ROOT, {"scenario": dict(PRESETS[1]["scenario"]),
                               "interest": PRESETS[1]["interest"], "save": False})
        coverage = result["coverage"]
        self.assertIn("documented_percent", coverage)
        self.assertIn("alignment_percent", coverage)
        self.assertLessEqual(coverage["alignment_numerator"], coverage["numerator"])
        self.assertIn("investigation cells", coverage["unit"])

    def test_all_presets_are_synthetic_and_assess_without_a_model(self):
        for preset in PRESETS:
            self.assertTrue(preset["synthetic"])
            result = assess(ROOT, {"scenario": dict(preset["scenario"]),
                                   "interest": preset["interest"], "save": False})
            self.assertEqual("corpus_condition_census", result["retrieval"]["mode"])
            self.assertFalse(result["saved_locally"])

    def test_scenario_persists_reopens_and_exports_as_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data/processed").mkdir(parents=True)
            shutil.copy(ROOT / "data/processed/chunks.jsonl", root / "data/processed/chunks.jsonl")
            shutil.copy(ROOT / "data/sources.json", root / "data/sources.json")
            saved = assess(root, {"scenario": dict(PRESETS[0]["scenario"]),
                                  "interest": PRESETS[0]["interest"],
                                  "description": "Release persistence check", "save": True})
            self.assertTrue(saved["saved_locally"])
            reopened = load_scenario(root, saved["scenario_id"])
            self.assertEqual(saved["target"], reopened["target"])
            exported = json.loads(json.dumps(reopened))
            self.assertEqual(saved["scenario_id"], exported["scenario_id"])
            planned = plan(root, {"scenario_id": saved["scenario_id"]})
            self.assertTrue(planned["reused_assessment"])
            self.assertIn("NOT EXECUTED", planned["label"])
            leftovers = list((root / "runs/scenarios").glob("*.tmp"))
            self.assertEqual([], leftovers)


class UnitNormalizationTests(unittest.TestCase):
    def test_numeric_units_convert_to_the_canonical_field_unit(self):
        target, _ = normalize_scenario({
            "oxygen_percent": {"value": 21, "unit": "percent"},
            "pressure_kpa": {"value": 1, "unit": "atm"},
            "flow_cm_s": {"value": 200, "unit": "mm/s"},
        })
        self.assertAlmostEqual(21.0, target["oxygen_percent"])
        self.assertAlmostEqual(101.325, target["pressure_kpa"])
        self.assertAlmostEqual(20.0, target["flow_cm_s"])

    def test_unsupported_unit_is_rejected_instead_of_guessed(self):
        with self.assertRaises(ValueError):
            normalize_scenario({"flow_cm_s": {"value": 1, "unit": "furlongs/fortnight"}})

    def test_blank_and_null_values_remain_unspecified(self):
        target, _ = normalize_scenario({"fuel": "  ", "gravity": None})
        for field in target:
            self.assertIn(field, FIELDS)
        self.assertEqual({}, target)


class ReleaseHygieneTests(unittest.TestCase):
    TEXT_SUFFIXES = {".py", ".md", ".json", ".jsonl", ".html", ".cff", ".yml", ".yaml",
                     ".toml", ".txt", ".cjs", ".example", ".ps1", ".cmd", ""}
    REQUIRED_DOCS = (
        "README.md", "LICENSE", "CITATION.cff", ".gitignore", ".env.example",
        "Dockerfile", "docker-compose.yml", "SUBMISSION.md", "THIRD_PARTY_NOTICES.md",
        "data/processed/chunks.jsonl", "data/sources.json",
        "docs/MISSION_SCENARIO.md", "docs/SCIENTIFIC_METHODOLOGY.md",
        "docs/DATA_SOURCES.md", "docs/SAFETY_AND_LIMITATIONS.md",
        "docs/DEPLOYMENT.md", "docs/DEMONSTRATION_GUIDE.md",
        "docs/RULES_AND_ELIGIBILITY.md", "PROJECT_WORK.md",
    )

    def test_required_release_files_are_present(self):
        for relative in self.REQUIRED_DOCS:
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_no_local_credentials_or_private_review_keys_are_shipped(self):
        self.assertFalse((ROOT / ".env").exists())
        self.assertEqual([], list(ROOT.rglob("review_key.private.json")))
        self.assertEqual([], list(ROOT.rglob("*.pdf")))

    def test_text_assets_contain_no_provider_keys_or_machine_paths(self):
        needles = ("gs" + "k_", "sk-" + "or-v1-", "C:" + "\\Users\\")
        for path in ROOT.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in self.TEXT_SUFFIXES:
                continue
            if ".venv" in path.parts or "__pycache__" in path.parts or ".git" in path.parts:
                continue
            if path == Path(__file__).resolve() or path.name.endswith(".whl"):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for needle in needles:
                self.assertNotIn(needle, text, path)

    def test_env_example_documents_every_runtime_variable(self):
        text = (ROOT / ".env.example").read_text(encoding="utf-8")
        for name in ("GROQ_KEY", "OPENROUTER_KEY", "GROQ_MODEL", "OPENROUTER_MODEL",
                     "AXIOM_HOST", "AXIOM_PORT", "AXIOM_ALLOWED_HOSTS",
                     "AXIOM_ALLOWED_ORIGINS", "AXIOM_LOG_REQUESTS"):
            self.assertIn(name, text)
        for line in text.splitlines():
            if line.strip().startswith(("GROQ_KEY=", "OPENROUTER_KEY=")):
                self.assertEqual("", line.split("=", 1)[1].strip(), line)


if __name__ == "__main__":
    unittest.main()
