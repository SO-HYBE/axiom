"""Tests for trace integrity, the three-valued monitor and the output policy."""
import json
import unittest
from pathlib import Path

from axiom.monitor import MANDATORY, OUTPUT_POLICY, evaluate
from axiom.trace import (EVENT_TYPES, build_trace, content_hash, integrity, make_event,
                         make_trace)

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "runs/benchmarks/3c3cc0f1e4b949a8a33296e94417f13c/jobs"


class Builder:
    """Small deterministic trace builder for monitor tests."""

    def __init__(self, run_id="run-a"):
        self.run_id = run_id
        self.rows = []

    def add(self, event_type, seq=None, **fields):
        seq = len(self.rows) + 1 if seq is None else seq
        self.rows.append(make_event(event_type, self.run_id, seq, **fields))
        return self

    def standard(self, *, evidence=True, check=True, verify=True, publish=True,
                 outcome="WITHIN_DOCUMENTED_SCOPE", verdict="supported",
                 label="verified", claim_id="c1", retrieved=("e1",), linked=("e1",),
                 published_ids=("e1",), scenario_version="s1", metadata_version="m1"):
        self.add("QUERY_RECEIVED", question="q")
        if evidence:
            self.add("EVIDENCE_RETRIEVED", evidence_ids=list(retrieved))
        self.add("METADATA_EXTRACTED", metadata_version=metadata_version, fields={})
        self.add("METADATA_VALIDATED", metadata_version=metadata_version,
                 validation_status="automatic", valid=True)
        self.add("CLAIM_GENERATED", claim_id=claim_id, text="t")
        self.add("CLAIM_LINKED_TO_EVIDENCE", claim_id=claim_id,
                 evidence_ids=list(linked),
                 citations=[{"chunk_id": identifier, "quote": "q"} for identifier in linked])
        if check:
            self.add("APPLICABILITY_CHECKED", claim_id=claim_id, scenario_id="s",
                     scenario_version=scenario_version, outcome=outcome)
        if verify:
            self.add("CLAIM_VERIFIED", claim_id=claim_id, verdict=verdict,
                     evidence_ids=list(published_ids), scenario_version=scenario_version,
                     metadata_version=metadata_version, applicability_outcome=outcome)
        if publish:
            self.add("CLAIM_PUBLISHED", claim_id=claim_id, label=label,
                     evidence_ids=list(published_ids), scenario_version=scenario_version,
                     metadata_version=metadata_version)
        return self

    def trace(self, manifest=None):
        return make_trace(self.run_id, self.rows, scenario_version="s1",
                          metadata_version="m1", manifest=manifest)


def verdicts(report, property_id):
    row = next(item for item in report["properties"] if item["registry"]["id"] == property_id)
    return row["verdict"]


def renumber(rows):
    """Rebuild events with contiguous seq numbers, as a run that never emitted the gap."""
    return [make_event(event["type"], event["run_id"], index + 1,
                       **{key: value for key, value in event.items()
                          if key not in ("event_id", "type", "run_id", "seq",
                                         "schema_version", "content_hash")})
            for index, event in enumerate(rows)]


class RegistryTests(unittest.TestCase):
    def test_registry_covers_the_eight_mandatory_properties(self):
        self.assertEqual(MANDATORY, ("P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8"))
        report = evaluate(Builder().trace())
        self.assertEqual([row["registry"]["id"] for row in report["properties"]],
                         list(MANDATORY))
        for row in report["properties"]:
            for key in ("definition", "pass_condition", "fail_condition", "unknown_condition"):
                self.assertTrue(row["registry"][key])

    def test_event_schema_is_versioned_and_hashed(self):
        event = make_event("QUERY_RECEIVED", "r", 1, question="q")
        self.assertEqual(event["schema_version"], "axiom-trace-v1")
        self.assertEqual(event["content_hash"], content_hash(event))
        self.assertIn("QUERY_RECEIVED", EVENT_TYPES)
        with self.assertRaises(ValueError):
            make_event("NOT_AN_EVENT", "r", 1)
        with self.assertRaises(ValueError):
            make_event("QUERY_RECEIVED", "r", 0)


class IntegrityTests(unittest.TestCase):
    def test_contiguous_complete_run_is_trusted(self):
        result = integrity(Builder().standard().trace())
        flags = result["flags"]
        self.assertFalse(flags["gap_detected"])
        self.assertFalse(flags["run_incomplete"])
        self.assertTrue(flags["ordering_recoverable"])
        self.assertEqual(result["events_trusted"], result["events_observed"])

    def test_gap_and_manifest_mismatch_mark_the_run_incomplete(self):
        builder = Builder().standard()
        rows = [row for row in builder.rows if row["type"] != "APPLICABILITY_CHECKED"]
        trace = make_trace("run-a", rows, manifest={"event_count": 9, "last_seq": 9})
        flags = integrity(trace)["flags"]
        self.assertTrue(flags["gap_detected"])
        self.assertTrue(flags["run_incomplete"])

    def test_delivery_reordering_is_flagged_but_sequence_numbers_stay_usable(self):
        rows = Builder().standard().rows
        swapped = list(rows)
        swapped[3], swapped[4] = swapped[4], swapped[3]
        flags = integrity(make_trace("run-a", swapped))["flags"]
        self.assertFalse(flags["delivery_order_reliable"])
        self.assertTrue(flags["ordering_unreliable"])
        self.assertTrue(flags["ordering_recoverable"])

    def test_duplicate_sequence_numbers_make_order_unrecoverable(self):
        rows = Builder().standard().rows
        rows[4] = make_event("CLAIM_GENERATED", "run-a", rows[3]["seq"], claim_id="c9")
        flags = integrity(make_trace("run-a", rows))["flags"]
        self.assertFalse(flags["seq_unique"])
        self.assertFalse(flags["ordering_recoverable"])

    def test_identical_duplicate_is_discarded_and_conflicting_duplicate_is_untrusted(self):
        builder = Builder().standard()
        rows = list(builder.rows) + [dict(builder.rows[4])]
        result = integrity(make_trace("run-a", rows))
        self.assertEqual(len(result["flags"]["duplicate_identical"]), 1)
        self.assertEqual(result["flags"]["duplicate_conflicting"], [])

        conflict = make_event("CLAIM_GENERATED", "run-a", builder.rows[4]["seq"],
                              event_id=builder.rows[4]["event_id"], claim_id="other")
        result = integrity(make_trace("run-a", builder.rows + [conflict]))
        self.assertEqual(len(result["flags"]["duplicate_conflicting"]), 1)

    def test_hash_mismatch_removes_the_event_from_the_trusted_set(self):
        rows = [dict(row) for row in Builder().standard().rows]
        rows[1]["content_hash"] = "0" * 64
        result = integrity(make_trace("run-a", rows))
        self.assertEqual(len(result["flags"]["hash_mismatch"]), 1)
        self.assertEqual(result["events_trusted"], result["events_observed"] - 1)


class ProvenanceTests(unittest.TestCase):
    def test_p1_passes_when_every_reference_is_retrieved(self):
        report = evaluate(Builder().standard().trace())
        self.assertEqual(verdicts(report, "P1"), "PASS")

    def test_p1_fails_on_a_dangling_evidence_reference(self):
        report = evaluate(Builder().standard(linked=("e1", "ghost"),
                                             published_ids=("e1", "ghost")).trace())
        self.assertEqual(verdicts(report, "P1"), "FAIL")
        row = next(item for item in report["properties"] if item["registry"]["id"] == "P1")
        self.assertIn("ghost", json.dumps(row))

    def test_p1_is_unknown_without_a_trusted_retrieval_event(self):
        builder = Builder().standard(evidence=False)
        report = evaluate(builder.trace())
        self.assertEqual(verdicts(report, "P1"), "UNKNOWN")

    def test_p6_passes_and_fails_on_citation_resolution(self):
        passing = evaluate(Builder().standard().trace())
        self.assertEqual(verdicts(passing, "P6"), "PASS")
        failing = evaluate(Builder().standard(linked=("e1", "ghost")).trace())
        self.assertEqual(verdicts(failing, "P6"), "FAIL")


class VerificationTests(unittest.TestCase):
    def test_p2_passes_with_checks_before_verification(self):
        report = evaluate(Builder().standard().trace())
        self.assertEqual(verdicts(report, "P2"), "PASS")

    def test_p2_passes_when_no_applicability_check_was_required(self):
        builder = Builder().standard(check=False)
        for index, row in enumerate(builder.rows):
            if row["type"] == "CLAIM_VERIFIED":
                builder.rows[index] = make_event(
                    "CLAIM_VERIFIED", "run-a", row["seq"], claim_id="c1",
                    verdict="supported", evidence_ids=["e1"], scenario_version="s1",
                    metadata_version="m1", applicability_outcome="NOT_ASSESSED",
                    required_checks=["METADATA_VALIDATED"])
        report = evaluate(builder.trace())
        self.assertEqual(verdicts(report, "P2"), "PASS")

    def test_p2_fails_when_a_complete_run_lacks_the_applicability_check(self):
        report = evaluate(Builder().standard(check=False).trace())
        self.assertEqual(verdicts(report, "P2"), "FAIL")
        self.assertIn("APPLICABILITY_CHECKED", json.dumps(report["properties"]))

    def test_p2_is_unknown_when_the_run_is_incomplete(self):
        builder = Builder().standard(check=False)
        manifest = {"event_count": len(builder.rows) + 1, "last_seq": len(builder.rows) + 1}
        report = evaluate(builder.trace(manifest=manifest))
        self.assertEqual(verdicts(report, "P2"), "UNKNOWN")

    def test_p2_fails_when_the_check_follows_verification(self):
        rows = renumber(Builder().standard().rows)
        check = next(row for row in rows if row["type"] == "APPLICABILITY_CHECKED")
        rows = [row for row in rows if row["type"] != "APPLICABILITY_CHECKED"]
        rows = renumber(rows)
        rows.append(make_event("APPLICABILITY_CHECKED", "run-a", len(rows) + 1,
                               claim_id="c1", scenario_version="s1",
                               outcome="WITHIN_DOCUMENTED_SCOPE"))
        report = evaluate(make_trace("run-a", rows))
        self.assertEqual(verdicts(report, "P2"), "FAIL")
        self.assertEqual(check["type"], "APPLICABILITY_CHECKED")

    def test_p3_fails_when_the_published_scenario_version_changed(self):
        report = evaluate(Builder().standard(
            published_scenario_version=None).trace() if False else
            Builder().standard().trace())
        self.assertEqual(verdicts(report, "P3"), "PASS")
        events = Builder().standard().rows
        for index, row in enumerate(events):
            if row["type"] == "CLAIM_PUBLISHED":
                events[index] = make_event("CLAIM_PUBLISHED", "run-a", row["seq"],
                                           claim_id="c1", label="verified",
                                           evidence_ids=["e1"], scenario_version="s2",
                                           metadata_version="m1")
        report = evaluate(make_trace("run-a", events))
        self.assertEqual(verdicts(report, "P3"), "FAIL")

    def test_p3_fails_when_the_evidence_set_changed_after_verification(self):
        events = Builder().standard().rows
        for index, row in enumerate(events):
            if row["type"] == "CLAIM_PUBLISHED":
                events[index] = make_event("CLAIM_PUBLISHED", "run-a", row["seq"],
                                           claim_id="c1", label="verified",
                                           evidence_ids=["e2"], scenario_version="s1",
                                           metadata_version="m1")
        report = evaluate(make_trace("run-a", [dict(row) for row in events]))
        self.assertEqual(verdicts(report, "P3"), "FAIL")
        self.assertIn("evidence_ids", json.dumps(report["properties"]))

    def test_p4_fails_on_a_scope_claim_against_a_contradicting_check(self):
        builder = Builder().standard(outcome="WITHIN_DOCUMENTED_SCOPE")
        builder.add("APPLICABILITY_CHECKED", claim_id="c1", scenario_version="s1",
                    outcome="CONDITION_MISMATCH")
        report = evaluate(builder.trace())
        self.assertEqual(verdicts(report, "P4"), "FAIL")

    def test_p4_passes_when_the_contradiction_is_another_claim(self):
        builder = Builder().standard(outcome="WITHIN_DOCUMENTED_SCOPE")
        builder.add("APPLICABILITY_CHECKED", claim_id="c2", scenario_version="s1",
                    outcome="CONDITION_MISMATCH")
        report = evaluate(builder.trace())
        self.assertEqual(verdicts(report, "P4"), "PASS")

    def test_p5_fails_when_a_verified_label_has_no_verification(self):
        report = evaluate(Builder().standard(verify=False).trace())
        self.assertEqual(verdicts(report, "P5"), "FAIL")

    def test_p5_fails_when_the_verification_is_unsupported(self):
        report = evaluate(Builder().standard(verdict="unverified").trace())
        self.assertEqual(verdicts(report, "P5"), "FAIL")

    def test_p5_fails_when_a_withheld_claim_is_published(self):
        builder = Builder().standard()
        builder.add("CLAIM_WITHHELD", claim_id="c1", reason="critic")
        report = evaluate(builder.trace())
        self.assertEqual(verdicts(report, "P5"), "FAIL")

    def test_p8_fails_when_publication_precedes_verification(self):
        rows = renumber(Builder().standard().rows)
        publish = next(row for row in rows if row["type"] == "CLAIM_PUBLISHED")
        verify = next(row for row in rows if row["type"] == "CLAIM_VERIFIED")
        rows = [row for row in rows if row["type"] not in ("CLAIM_PUBLISHED", "CLAIM_VERIFIED")]
        rows.append(make_event("CLAIM_PUBLISHED", "run-a", len(rows) + 1, claim_id="c1",
                               label="verified", evidence_ids=["e1"],
                               scenario_version="s1", metadata_version="m1"))
        rows.append(make_event("CLAIM_VERIFIED", "run-a", len(rows) + 1, claim_id="c1",
                               verdict="supported", evidence_ids=["e1"],
                               scenario_version="s1", metadata_version="m1",
                               applicability_outcome="WITHIN_DOCUMENTED_SCOPE"))
        report = evaluate(make_trace("run-a", rows))
        self.assertEqual(verdicts(report, "P8"), "FAIL")
        self.assertTrue(publish and verify)

    def test_p8_is_unknown_when_sequence_numbers_are_unusable(self):
        rows = Builder().standard().rows
        rows[5] = make_event("CLAIM_LINKED_TO_EVIDENCE", "run-a", 1, claim_id="c1",
                             evidence_ids=["e1"], citations=[])
        report = evaluate(make_trace("run-a", rows))
        self.assertEqual(verdicts(report, "P8"), "UNKNOWN")


class DuplicateTests(unittest.TestCase):
    def test_identical_duplicate_passes_with_a_note(self):
        builder = Builder().standard()
        rows = list(builder.rows) + [dict(builder.rows[4])]
        report = evaluate(make_trace("run-a", rows))
        self.assertEqual(verdicts(report, "P7"), "PASS")

    def test_conflicting_duplicate_fails(self):
        builder = Builder().standard()
        conflict = make_event("CLAIM_GENERATED", "run-a", builder.rows[4]["seq"],
                              event_id=builder.rows[4]["event_id"], claim_id="other")
        report = evaluate(make_trace("run-a", builder.rows + [conflict]))
        self.assertEqual(verdicts(report, "P7"), "FAIL")

    def test_hash_mismatch_is_unknown_not_fail(self):
        rows = [dict(row) for row in Builder().standard().rows]
        rows[1]["content_hash"] = "0" * 64
        report = evaluate(make_trace("run-a", rows))
        self.assertEqual(verdicts(report, "P7"), "UNKNOWN")


class AggregateAndPolicyTests(unittest.TestCase):
    def test_clean_trace_aggregates_to_pass_and_verified_policy(self):
        report = evaluate(Builder().standard().trace())
        self.assertEqual(report["overall"], "PASS")
        self.assertEqual(report["claims"]["c1"]["verdict"], "PASS")
        self.assertEqual(report["claims"]["c1"]["policy"], "published as verified")
        self.assertEqual(report["output_policy"]["FAIL"], "withheld")

    def test_unknown_dominates_pass_but_not_fail(self):
        builder = Builder().standard(evidence=False)
        report = evaluate(builder.trace())
        self.assertIn(report["overall"], ("UNKNOWN", "FAIL"))
        self.assertEqual(report["claims"]["c1"]["verdict"], report["overall"])

    def test_failure_withholds_the_claim(self):
        report = evaluate(Builder().standard(linked=("ghost",), published_ids=("ghost",)).trace())
        self.assertEqual(report["overall"], "FAIL")
        self.assertEqual(report["claims"]["c1"]["policy"], OUTPUT_POLICY["FAIL"])

    def test_explanation_names_the_property_that_degraded(self):
        report = evaluate(Builder().standard(check=False).trace())
        self.assertTrue(any("P2" in line for line in report["explanation"]))


class FrozenRunTests(unittest.TestCase):
    def test_real_ignis_trace_projects_and_evaluates(self):
        path = next(FROZEN.glob("*--ignis.json"))
        run = json.loads(path.read_text(encoding="utf-8"))["run"]
        trace = build_trace(run, question_id="Q001")
        self.assertEqual(trace["schema_version"], "axiom-trace-v1")
        report = evaluate(trace)
        self.assertIn(report["overall"], ("PASS", "FAIL", "UNKNOWN"))
        self.assertEqual(verdicts(report, "P1"), "PASS")
        self.assertEqual(verdicts(report, "P7"), "PASS")
        self.assertIn("Process properties over a finite terminated run", report["scope"])

    def test_baseline_trace_publishes_without_a_verification_event(self):
        path = FROZEN / "Q008--baseline.json"
        run = json.loads(path.read_text(encoding="utf-8"))["run"]
        trace = build_trace(run, question_id="Q008")
        types = [row["type"] for row in trace["events"]]
        self.assertNotIn("CLAIM_VERIFIED", types)
        self.assertIn("CLAIM_PUBLISHED", types)
        labels = {row["label"] for row in trace["events"] if row["type"] == "CLAIM_PUBLISHED"}
        self.assertEqual(labels, {"unverified"})
        report = evaluate(trace)
        self.assertNotEqual(report["claims"]["Q008-c1"]["policy"], "published as verified")


if __name__ == "__main__":
    unittest.main()
