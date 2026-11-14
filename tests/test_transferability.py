import unittest

from axiom.transferability import (
    GAP_ORDER, GAP_PRIORITY_NOTE, assess, audit, identify_gaps, normalize_scenario, propose,
)


def record(field, value, unit=None, **changes):
    row = {
        "source_id": "source-1", "chunk_id": "chunk-1", "locator": "PDF page 4",
        "quote": "quoted source text", "field": field, "value": value, "unit": unit,
        "scope": "individual_test", "evidence_status": "reported", "matching_eligible": True,
    }
    row.update(changes)
    return row


def investigation(records, key="BASS-II", behaviors=("flame_spread",), domain="solid_fuel_flame_spread"):
    return {"investigation_id": key, "label": key, "domain": domain,
            "behaviors": list(behaviors), "source_ids": ["source-1"], "records": records}


class NormalizationTests(unittest.TestCase):
    def test_units_are_converted_without_losing_the_user_input(self):
        target, original = normalize_scenario({
            "pressure_kpa": {"value": 1, "unit": "atm"},
            "flow_cm_s": {"value": 0.2, "unit": "m/s"},
            "oxygen_percent": {"value": 21, "unit": "%"},
        })
        self.assertEqual(target["pressure_kpa"], 101.325)
        self.assertEqual(target["flow_cm_s"], 20.0)
        self.assertEqual(original["pressure_kpa"], {"value": 1, "unit": "atm"})

    def test_unknown_fields_are_absent_not_defaulted(self):
        target, _ = normalize_scenario({"gravity": "microgravity", "fuel": ""})
        self.assertEqual(target, {"gravity": "microgravity"})

    def test_invalid_values_fail_closed(self):
        for scenario in ({"oxygen_percent": {"value": 101, "unit": "%"}},
                         {"pressure_kpa": {"value": -1, "unit": "kPa"}},
                         {"flow_cm_s": {"value": float("nan"), "unit": "cm/s"}},
                         {"pressure_kpa": {"value": 1, "unit": "furlong"}},
                         {"unknown_field": "x"}):
            with self.subTest(scenario=scenario), self.assertRaises(ValueError):
                normalize_scenario(scenario)


class ClassificationTests(unittest.TestCase):
    def test_exact_partial_mismatch_and_unknown_are_distinct(self):
        target, _ = normalize_scenario({
            "oxygen_percent": {"value": 21, "unit": "%"},
            "flow_cm_s": {"value": 20, "unit": "cm/s"},
            "pressure_kpa": {"value": 200, "unit": "kPa"},
            "ignition": "hot wire",
        })
        result = assess(target, [investigation([
            record("oxygen_percent", 21.0, "%"),
            record("flow_cm_s", {"min": 1.0, "max": 40.0}, "cm/s", scope="experiment_range"),
            record("pressure_kpa", 101.325, "kPa"),
            record("ignition", "spark", None),
        ])], "flame_spread")
        parameters = {row["field"]: row for row in result["investigations"][0]["parameters"]}
        self.assertEqual(parameters["oxygen_percent"]["classification"], "exact_match")
        self.assertEqual(parameters["flow_cm_s"]["classification"], "partial_match")
        self.assertEqual(parameters["pressure_kpa"]["classification"], "mismatch")
        self.assertEqual(parameters["ignition"]["classification"], "mismatch")

    def test_units_differ_but_represent_the_same_quantity(self):
        target, _ = normalize_scenario({"pressure_kpa": {"value": 1, "unit": "atm"}})
        result = assess(target, [investigation([record("pressure_kpa", 101.325, "kPa")])], None)
        self.assertEqual(result["investigations"][0]["parameters"][0]["classification"], "exact_match")

    def test_alias_table_matches_categorical_terms(self):
        target, _ = normalize_scenario({"fuel": "SIBAL fabric", "gravity": "micro-gravity"})
        result = assess(target, [investigation([
            record("fuel", "sibal_fabric", None),
            record("gravity", "microgravity", None),
        ])], None)
        classifications = {row["field"]: row["classification"]
                           for row in result["investigations"][0]["parameters"]}
        self.assertEqual(classifications, {"gravity": "exact_match", "fuel": "exact_match"})

    def test_unreported_condition_is_unknown_not_a_match(self):
        target, _ = normalize_scenario({"pressure_kpa": {"value": 101.325, "unit": "kPa"}})
        parameter = assess(target, [investigation([])], None)["investigations"][0]["parameters"][0]
        self.assertEqual(parameter["classification"], "unknown")
        self.assertEqual(parameter["basis"], "not_documented_in_available_corpus")
        self.assertIn("not evidence", parameter["reason"])

    def test_unqualified_mention_is_unknown_and_visible(self):
        target, _ = normalize_scenario({"oxygen_percent": {"value": 21, "unit": "%"}})
        parameter = assess(target, [investigation([
            record("oxygen_percent", 21.0, "%", evidence_status="proposed", matching_eligible=False)
        ])], None)["investigations"][0]["parameters"][0]
        self.assertEqual(parameter["classification"], "unknown")
        self.assertEqual(parameter["basis"], "no_qualified_condition")
        self.assertEqual(len(parameter["unqualified_records"]), 1)
        self.assertIn("proposed", parameter["reason"].lower())

    def test_contextual_domain_is_not_direct_evidence(self):
        target, _ = normalize_scenario({"gravity": "microgravity"})
        result = assess(target, [investigation([record("gravity", "microgravity")], behaviors=("burning_rate",))],
                        "flame_spread")
        self.assertEqual(result["investigations"][0]["relevance"]["evidence_type"], "contextual")

    def test_coverage_counts_cells_and_defines_its_denominator(self):
        target, _ = normalize_scenario({"gravity": "microgravity",
                                        "oxygen_percent": {"value": 21, "unit": "%"}})
        result = assess(target, [
            investigation([record("gravity", "microgravity"), record("oxygen_percent", 21.0, "%")], "A"),
            investigation([], "B"),
        ], None)
        coverage = result["coverage"]
        self.assertEqual((coverage["numerator"], coverage["denominator"]), (2, 4))
        self.assertEqual(coverage["documented_percent"], 50.0)
        self.assertEqual(coverage["alignment_percent"], 50.0)
        self.assertIn("not a probability", coverage["limitations"])


class GapTests(unittest.TestCase):
    def gaps(self, target, rows, interest="flame_spread"):
        return identify_gaps(target, assess(target, rows, interest)["investigations"])

    def test_no_documented_condition_states_the_corpus_boundary(self):
        target, _ = normalize_scenario({"fuel": "thermoplastic"})
        gap = self.gaps(target, [investigation([])])[0]
        self.assertEqual(gap["kind"], "no_documented_condition_in_corpus")
        self.assertIn("not proof", gap["corpus_scope_note"].lower())

    def test_documented_mismatch_is_not_confused_with_missing_documentation(self):
        target, _ = normalize_scenario({"fuel": "thermoplastic"})
        gap = self.gaps(target, [investigation([record("fuel", "pmma")])])[0]
        self.assertEqual(gap["kind"], "documented_outside_scenario_condition")

    def test_range_only_coverage_remains_a_gap(self):
        target, _ = normalize_scenario({"flow_cm_s": {"value": 20, "unit": "cm/s"}})
        gap = self.gaps(target, [investigation([
            record("flow_cm_s", {"min": 1.0, "max": 40.0}, "cm/s", scope="experiment_range")
        ])])[0]
        self.assertEqual(gap["kind"], "partial_documentation_only")

    def test_contextual_match_remains_a_gap(self):
        target, _ = normalize_scenario({"fuel": "methanol"})
        gap = self.gaps(target, [investigation([record("fuel", "methanol")],
                                               behaviors=("burning_rate",))])[0]
        self.assertEqual(gap["kind"], "contextual_evidence_only")

    def test_planned_only_mention_remains_a_gap(self):
        target, _ = normalize_scenario({"flow_cm_s": {"value": 20, "unit": "cm/s"}})
        gap = self.gaps(target, [investigation([
            record("flow_cm_s", 20.0, "cm/s", evidence_status="proposed", matching_eligible=False)
        ])])[0]
        self.assertEqual(gap["kind"], "documented_only_as_plan_or_background")

    def test_combination_gap_appears_when_no_investigation_covers_every_field(self):
        target, _ = normalize_scenario({"gravity": "microgravity", "fuel": "pmma"})
        gaps = self.gaps(target, [
            investigation([record("gravity", "microgravity"), record("fuel", "sibal_fabric")], "A"),
            investigation([record("gravity", "terrestrial"), record("fuel", "pmma")], "B"),
        ])
        combination = [gap for gap in gaps if gap["kind"] == "combination_not_jointly_documented"]
        self.assertEqual(len(combination), 1)
        self.assertIsNone(combination[0]["field"])
        self.assertEqual(len(combination[0]["investigations"]["coverage"]), 2)

    def test_no_combination_gap_when_one_investigation_is_exactly_complete(self):
        target, _ = normalize_scenario({"gravity": "microgravity", "fuel": "pmma"})
        gaps = self.gaps(target, [investigation([record("gravity", "microgravity"), record("fuel", "pmma")])])
        self.assertFalse([gap for gap in gaps if gap["kind"] == "combination_not_jointly_documented"])


class ProposalTests(unittest.TestCase):
    def build(self, scenario, rows, interest="flame_spread"):
        target, _ = normalize_scenario(scenario)
        result = assess(target, rows, interest)
        gaps = identify_gaps(target, result["investigations"])
        proposals = propose(gaps, target, interest, result["investigations"])
        return target, result, gaps, proposals, audit({**result, "target": target, "gaps": gaps,
                                                       "proposals": proposals})

    def test_every_proposal_is_labelled_proposed_and_tied_to_a_gap(self):
        target, _, gaps, proposals, critic = self.build(
            {"fuel": "thermoplastic"}, [investigation([record("fuel", "pmma")])])
        self.assertTrue(proposals)
        gap_ids = {gap["gap_id"] for gap in gaps}
        for proposal in proposals:
            self.assertIn("PROPOSED", proposal["label"])
            self.assertIn(proposal["gap_id"], gap_ids)
            self.assertIn("Hypothesis (proposed, not observed)", proposal["hypothesis"])
            self.assertEqual(proposal["priority"]["method"], GAP_PRIORITY_NOTE)
        self.assertNotEqual(critic["summary"]["verdict"], "withheld")

    def test_no_numeric_range_is_invented_for_a_missing_condition(self):
        target, _, _, proposals, critic = self.build(
            {"flow_cm_s": {"value": 20, "unit": "cm/s"}}, [investigation([])])
        proposal = proposals[0]
        self.assertIn("20 cm/s", proposal["research_question"])
        self.assertNotRegex(proposal["experimental_design"], r"\d")
        self.assertNotEqual(critic["summary"]["verdict"], "withheld")

    def test_priority_is_lexicographic_gap_kind_order_without_a_scalar_score(self):
        target, _, gaps, proposals, _ = self.build(
            {"fuel": "thermoplastic", "oxygen_percent": {"value": 30, "unit": "%"}},
            [investigation([record("fuel", "pmma"), record("oxygen_percent", 21.0, "%")])])
        ordered_kinds = [gap["kind"] for gap in
                         sorted(gaps, key=lambda gap: GAP_ORDER[gap["kind"]])]
        self.assertEqual([row["gap_kind"] for row in proposals], ordered_kinds[:len(proposals)])
        self.assertEqual([row["priority"]["rank"] for row in proposals], list(range(1, len(proposals) + 1)))
        self.assertNotIn("score", proposals[0]["priority"])

    def test_critic_withholds_a_proposal_whose_hypothesis_is_not_marked_proposed(self):
        target, result, gaps, proposals, _ = self.build(
            {"flow_cm_s": {"value": 20, "unit": "cm/s"}}, [investigation([])])
        tampered = dict(proposals[0], hypothesis="Hypothesis: flame spread changes at this value.")
        critic = audit({**result, "target": target, "gaps": gaps, "proposals": [tampered]})
        check = next(row for row in critic["checks"] if row["subject"] == tampered["proposal_id"])
        self.assertEqual(check["verdict"], "withheld")
        self.assertIn("proposal_not_clearly_labelled", check["issues"])

    def test_critic_withholds_a_proposal_with_an_uninvented_numeric_claim(self):
        target, result, gaps, proposals, _ = self.build(
            {"flow_cm_s": {"value": 20, "unit": "cm/s"}}, [investigation([])])
        tampered = dict(proposals[0], experimental_design="A qualified team would test at 77 cm/s.")
        critic = audit({**result, "target": target, "gaps": gaps, "proposals": [tampered]})
        check = next(row for row in critic["checks"] if row["subject"] == tampered["proposal_id"])
        self.assertEqual(check["verdict"], "withheld")
        self.assertIn("unsupported_numeric_value", check["issues"])

    def test_critic_withholds_an_absence_treated_as_a_negative_result(self):
        target, result, gaps, proposals, _ = self.build(
            {"fuel": "thermoplastic"}, [investigation([record("fuel", "pmma")])])
        gaps[0]["what_is_missing"] = "The material was never tested, so it cannot burn."
        critic = audit({**result, "target": target, "gaps": gaps, "proposals": proposals})
        check = next(row for row in critic["checks"] if row["subject"] == gaps[0]["gap_id"])
        self.assertEqual(check["verdict"], "withheld")
        self.assertIn("absence_treated_as_negative_result", check["issues"])

    def test_critic_flags_a_proposal_without_cited_evidence_as_qualified(self):
        target, result, gaps, proposals, critic = self.build(
            {"ignition": "spark"}, [investigation([])])
        check = next(row for row in critic["checks"] if row["subject"] == proposals[0]["proposal_id"])
        self.assertEqual(check["verdict"], "qualified")
        self.assertIn("motivation_has_no_documented_condition", check["issues"])


if __name__ == "__main__":
    unittest.main()
