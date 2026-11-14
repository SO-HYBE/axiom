"""Tests for deterministic trace mutations, seeded faults and lab metrics.

The mutation operators model an unreliable channel; the seeded faults model a
buggy pipeline. Both are measured against verdicts on the unmutated trace, so
these tests check the mechanics and the declared labels, not the empirical
detection numbers (those live in ``runs/axiom/trace_lab/results.json``).
"""
import json
import unittest
from pathlib import Path

from axiom.faults import FAULTS, inject
from axiom.monitor import MANDATORY, evaluate
from axiom.mutation_lab import _empty_counts, _finalise, run_channel_lab
from axiom.mutations import (ADVERSARIAL_OPERATORS, CHANNEL_OPERATORS, OPERATORS,
                             apply, describe)
from axiom.trace import content_hash, integrity, make_event, make_trace

CHANNEL_PAYLOAD = ("corrupt_payload", "corrupt_evidence_ref", "corrupt_seq",
                   "corrupt_timestamp", "delay")


class Builder:
    """A complete, internally consistent ignis-shaped trace."""

    def __init__(self, run_id="run-a"):
        self.run_id = run_id
        self.rows = []

    def add(self, event_type, **fields):
        self.rows.append(make_event(event_type, self.run_id, len(self.rows) + 1,
                                    timestamp=(len(self.rows) + 1) * 1000, **fields))
        return self

    def standard(self, *, check=True, verify=True, publish=True, outcome="WITHIN_DOCUMENTED_SCOPE",
                 verdict="supported", label="verified"):
        self.add("QUERY_RECEIVED", question="q")
        self.add("EVIDENCE_RETRIEVED", evidence_ids=["e1"])
        self.add("METADATA_EXTRACTED", metadata_version="m1", fields={})
        self.add("METADATA_VALIDATED", metadata_version="m1", validation_status="automatic",
                 valid=True)
        self.add("CLAIM_GENERATED", claim_id="c1", text="t")
        self.add("CLAIM_LINKED_TO_EVIDENCE", claim_id="c1", evidence_ids=["e1"],
                 citations=[{"chunk_id": "e1", "quote": "q"}])
        if check:
            self.add("APPLICABILITY_CHECKED", claim_id="c1", scenario_id="s",
                     scenario_version="s1", outcome=outcome)
        if verify:
            self.add("CLAIM_VERIFIED", claim_id="c1", verdict=verdict, evidence_ids=["e1"],
                     scenario_version="s1", metadata_version="m1",
                     applicability_outcome=outcome,
                     required_checks=["METADATA_VALIDATED", "APPLICABILITY_CHECKED"])
        if publish:
            self.add("CLAIM_PUBLISHED", claim_id="c1", label=label, evidence_ids=["e1"],
                     scenario_version="s1", metadata_version="m1")
        return self

    def trace(self):
        return make_trace(self.run_id, self.rows, scenario_version="s1",
                          metadata_version="m1")


def snapshot(trace):
    return json.dumps(trace, sort_keys=True)


def verdicts(report):
    return {row["registry"]["id"]: row["verdict"] for row in report["properties"]}


def hashes_valid(trace):
    return all(event.get("content_hash") == content_hash(event) for event in trace["events"])


class OperatorSurfaceTests(unittest.TestCase):
    def test_every_operator_is_described_and_classified(self):
        self.assertEqual(OPERATORS, CHANNEL_OPERATORS + ADVERSARIAL_OPERATORS)
        self.assertFalse(set(CHANNEL_OPERATORS) & set(ADVERSARIAL_OPERATORS))
        for operator in OPERATORS:
            self.assertTrue(describe(operator))
        with self.assertRaises(ValueError):
            apply(Builder().standard().trace(), "not-an-operator", 0)


class DeterminismTests(unittest.TestCase):
    def test_the_same_seed_reproduces_the_same_mutation(self):
        trace = Builder().standard().trace()
        for operator in OPERATORS:
            with self.subTest(operator=operator):
                first, record = apply(trace, operator, 4)
                second, again = apply(trace, operator, 4)
                self.assertIsNotNone(first)
                self.assertEqual(snapshot(first), snapshot(second))
                self.assertEqual(record, again)
                self.assertEqual(record["operator"], operator)
                self.assertEqual(record["seed"], 4)

    def test_the_input_trace_is_never_modified(self):
        trace = Builder().standard().trace()
        before = snapshot(trace)
        for operator in OPERATORS:
            with self.subTest(operator=operator):
                apply(trace, operator, 0)
                self.assertEqual(before, snapshot(trace))

    def test_seed_selects_the_target_but_stays_reproducible(self):
        trace = Builder().standard().trace()
        for seed in range(16):
            first, _ = apply(trace, "loss", seed)
            second, _ = apply(trace, "loss", seed)
            self.assertEqual(len(first["events"]), len(trace["events"]) - 1)
            self.assertEqual(snapshot(first), snapshot(second))
        # The removed event differs across seeds, so the seed is a real input.
        targets = {apply(trace, "loss", seed)[1]["event_id"] for seed in range(16)}
        self.assertGreater(len(targets), 1)


class ChannelOperatorTests(unittest.TestCase):
    def setUp(self):
        self.trace = Builder().standard().trace()
        self.count = len(self.trace["events"])

    def mutate(self, operator, seed=0):
        mutated, record = apply(self.trace, operator, seed)
        self.assertIsNotNone(mutated)
        return mutated, record

    def test_loss_removes_exactly_one_event_and_is_reported_as_a_gap(self):
        mutated, record = self.mutate("loss")
        self.assertEqual(len(mutated["events"]), self.count - 1)
        self.assertNotIn(record["event_id"],
                         [event["event_id"] for event in mutated["events"]])
        flags = integrity(mutated)["flags"]
        self.assertTrue(flags["gap_detected"] or flags["run_incomplete"])
        self.assertTrue(hashes_valid(mutated))

    def test_reorder_changes_delivery_order_only(self):
        mutated, _ = self.mutate("reorder")
        self.assertEqual(len(mutated["events"]), self.count)
        self.assertEqual(sorted(event["event_id"] for event in mutated["events"]),
                         sorted(event["event_id"] for event in self.trace["events"]))
        flags = integrity(mutated)["flags"]
        self.assertFalse(flags["delivery_order_reliable"])
        self.assertTrue(flags["ordering_recoverable"])
        self.assertTrue(hashes_valid(mutated))

    def test_identical_duplicate_is_idempotent_for_trust_and_passes_p7(self):
        mutated, _ = self.mutate("duplicate_identical")
        self.assertEqual(len(mutated["events"]), self.count + 1)
        result = integrity(mutated)
        self.assertEqual(len(result["flags"]["duplicate_identical"]), 1)
        self.assertEqual(result["events_trusted"], self.count)
        self.assertEqual(verdicts(evaluate(mutated))["P7"], "PASS")

    def test_content_corruptions_leave_a_stale_hash_that_is_detected(self):
        for operator in CHANNEL_PAYLOAD:
            with self.subTest(operator=operator):
                mutated, record = self.mutate(operator)
                self.assertFalse(hashes_valid(mutated))
                flags = integrity(mutated)["flags"]
                self.assertEqual([row["event_id"] for row in flags["hash_mismatch"]],
                                 [record["event_id"]])
                self.assertEqual(verdicts(evaluate(mutated))["P7"], "UNKNOWN")

    def test_corrupt_evidence_ref_fabricates_an_identifier_without_rehashing(self):
        mutated, record = self.mutate("corrupt_evidence_ref")
        target = next(event for event in mutated["events"]
                      if event["event_id"] == record["event_id"])
        self.assertIn("ghost-evidence", target["evidence_ids"])
        self.assertNotEqual(target["content_hash"], content_hash(target))

    def test_corrupt_seq_changes_one_sequence_number(self):
        mutated, record = self.mutate("corrupt_seq")
        target = next(event for event in mutated["events"]
                      if event["event_id"] == record["event_id"])
        original = next(event for event in self.trace["events"]
                        if event["event_id"] == record["event_id"])
        self.assertEqual(target["seq"], original["seq"] + 1000)

    def test_corrupt_timestamp_changes_only_the_timestamp(self):
        mutated, record = self.mutate("corrupt_timestamp")
        target = next(event for event in mutated["events"]
                      if event["event_id"] == record["event_id"])
        original = next(event for event in self.trace["events"]
                        if event["event_id"] == record["event_id"])
        self.assertEqual(target["seq"], original["seq"])
        self.assertGreater(target["timestamp"], original["timestamp"])

    def test_delay_moves_one_event_to_the_end(self):
        mutated, record = self.mutate("delay")
        self.assertEqual(mutated["events"][-1]["event_id"], record["event_id"])
        self.assertEqual(len(mutated["events"]), self.count)
        self.assertFalse(integrity(mutated)["flags"]["delivery_order_reliable"])

    def test_channel_operators_are_never_marked_adversarial(self):
        for operator in CHANNEL_OPERATORS:
            with self.subTest(operator=operator):
                _, record = self.mutate(operator)
                self.assertFalse(record["adversarial"])


class AdversarialOperatorTests(unittest.TestCase):
    def setUp(self):
        self.trace = Builder().standard().trace()

    def test_adversarial_operators_are_flagged_and_rehash(self):
        for operator in ADVERSARIAL_OPERATORS:
            with self.subTest(operator=operator):
                mutated, record = apply(self.trace, operator, 0)
                self.assertIsNotNone(mutated)
                self.assertTrue(record["adversarial"])
                # A rehashed trace is internally consistent: the integrity layer
                # cannot see the change. That boundary is documented, not implied.
                self.assertTrue(hashes_valid(mutated))

    def test_conflicting_duplicate_is_a_detectable_violation(self):
        mutated, _ = apply(self.trace, "duplicate_conflicting", 0)
        self.assertEqual(len(integrity(mutated)["flags"]["duplicate_conflicting"]), 1)
        self.assertEqual(verdicts(evaluate(mutated))["P7"], "FAIL")

    def test_rehashed_evidence_fabrication_is_caught_by_provenance(self):
        mutated, _ = apply(self.trace, "corrupt_evidence_ref_rehash", 0)
        self.assertEqual(integrity(mutated)["flags"]["hash_mismatch"], [])
        self.assertEqual(verdicts(evaluate(mutated))["P1"], "FAIL")

    def test_rehashed_sequence_corruption_is_not_hidden_from_order_checks(self):
        mutated, _ = apply(self.trace, "corrupt_seq_rehash", 0)
        flags = integrity(mutated)["flags"]
        self.assertEqual(flags["hash_mismatch"], [])
        self.assertTrue(flags["gap_detected"])
        self.assertEqual(verdicts(evaluate(mutated))["P8"], "PASS")


class CompositionTests(unittest.TestCase):
    def test_two_mutations_compose_on_one_trace(self):
        trace = Builder().standard().trace()
        first, _ = apply(trace, "duplicate_identical", 0)
        second, _ = apply(first, "corrupt_timestamp", 1)
        self.assertEqual(len(second["events"]), len(trace["events"]) + 1)
        flags = integrity(second)["flags"]
        self.assertEqual(len(flags["duplicate_identical"]), 1)
        self.assertEqual(len(flags["hash_mismatch"]), 1)


class SeededFaultTests(unittest.TestCase):
    def setUp(self):
        self.trace = Builder().standard().trace()

    def test_control_trace_passes_every_property(self):
        report = evaluate(self.trace)
        self.assertEqual(set(verdicts(report).values()), {"PASS"})
        self.assertEqual(report["overall"], "PASS")

    def test_registry_lists_ten_faults_with_mandatory_properties(self):
        self.assertEqual(len(FAULTS), 10)
        names = [name for name, _, _ in FAULTS]
        self.assertEqual(len(names), len(set(names)))
        for name, property_id, description in FAULTS:
            self.assertIn(property_id, MANDATORY)
            self.assertTrue(description)
        with self.assertRaises(ValueError):
            inject(self.trace, "not-a-fault")

    def test_every_seeded_fault_is_detected_by_its_declared_property(self):
        for name, property_id, _ in FAULTS:
            with self.subTest(fault=name):
                faulty, label = inject(self.trace, name)
                self.assertIsNotNone(faulty)
                self.assertEqual(label["fault"], name)
                self.assertEqual(label["expected_property"], property_id)
                self.assertEqual(label["expected_verdict"], "FAIL")
                self.assertTrue(label["applicable"])
                self.assertTrue(hashes_valid(faulty))
                self.assertEqual(verdicts(evaluate(faulty))[property_id], "FAIL")

    def test_a_fault_is_skipped_when_its_pattern_is_absent(self):
        trace = Builder().standard(publish=False).trace()
        faulty, label = inject(trace, "publish_before_verify")
        self.assertIsNone(faulty)
        self.assertIsNone(label)

    def test_the_original_trace_is_not_modified_by_injection(self):
        before = snapshot(self.trace)
        for name, _, _ in FAULTS:
            inject(self.trace, name)
        self.assertEqual(before, snapshot(self.trace))


class LabMetricTests(unittest.TestCase):
    def test_counts_partition_the_cases_and_rates_follow_the_counts(self):
        trace = Builder().standard().trace()
        cases = [{"question_id": "Q1", "system": "synthetic", "trace": trace,
                  "reference": evaluate(trace)}]
        result = run_channel_lab(cases, seeds=(0,))
        for mode in ("on", "off"):
            bucket = result["overall"][mode]
            self.assertEqual(bucket["cases"],
                             bucket["correct"] + bucket["false"] + bucket["unknown"])
            self.assertEqual(bucket["conclusive"], bucket["correct"] + bucket["false"])
            self.assertEqual(bucket["false_conclusive_rate"],
                             round(bucket["false"] / bucket["cases"], 4))
            self.assertEqual(bucket["trustworthy_conclusive_rate"],
                             round(bucket["correct"] / bucket["conclusive"], 4))
        for operator in CHANNEL_OPERATORS:
            for property_id in MANDATORY:
                self.assertIn(property_id, result["matrix"]["on"][operator])

    def test_an_unknown_reference_property_is_excluded_from_the_denominator(self):
        # A publication without any verification makes P3 unknown, so channel
        # damage cannot produce a wrong conclusive P3 verdict for this trace.
        trace = Builder().standard(verify=False, label="unverified").trace()
        reference = evaluate(trace)
        self.assertEqual(verdicts(reference)["P3"], "UNKNOWN")
        cases = [{"question_id": "Q1", "system": "synthetic", "trace": trace,
                  "reference": reference}]
        bucket = run_channel_lab(cases, seeds=(0,))["matrix"]["on"]["loss"]["P3"]
        self.assertEqual(bucket["cases"], 0)
        self.assertIsNone(bucket["coverage"])
        self.assertIsNone(bucket["trustworthy_conclusive_rate"])
        self.assertGreaterEqual(bucket["reference_inconclusive"], 1)

    def test_undefined_rates_are_null_not_zero(self):
        bucket = _finalise(_empty_counts())
        self.assertEqual(bucket["cases"], 0)
        for key in ("coverage", "trustworthy_conclusive_rate", "false_conclusive_rate",
                    "inconclusive_rate"):
            self.assertIsNone(bucket[key])


if __name__ == "__main__":
    unittest.main()
