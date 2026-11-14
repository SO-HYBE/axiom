import unittest

from axiom.experiment_metadata import extract_chunk, investigations


def chunk(text, experiment="BASS-II", chunk_id="c1", source_id="source-1", locator="PDF page 4"):
    return {"chunk_id": chunk_id, "source_id": source_id, "text": text,
            "experiment": experiment, "locator": locator}


def fields(records):
    return {record["field"]: record for record in records}


class ExtractionTests(unittest.TestCase):
    def test_pressure_and_oxygen_keep_exact_quotation_and_convert_units(self):
        text = "The chamber pressure was 1.0 atm and the oxygen concentration was 30%."
        records = extract_chunk(chunk(text))
        by_field = fields(records)
        self.assertEqual(by_field["pressure_kpa"]["value"], 101.325)
        self.assertEqual(by_field["pressure_kpa"]["unit"], "kPa")
        self.assertEqual(by_field["oxygen_percent"]["value"], 30.0)
        self.assertEqual(by_field["oxygen_percent"]["unit"], "%")
        for record in records:
            self.assertEqual(record["quote"], text)
            self.assertEqual(record["locator"], "PDF page 4")
            self.assertEqual(record["review_status"], "machine_extracted_not_human_reviewed")
            self.assertTrue(record["matching_eligible"])

    def test_repeated_unit_ranges_become_ranges_not_endpoint_tests(self):
        text = ("Ambient oxygen was varied from 21% down to 16% and flow speed "
                "from 40 cm/s down to 1 cm/s.")
        by_field = fields(extract_chunk(chunk(text)))
        self.assertEqual(by_field["flow_cm_s"]["value"], {"min": 1.0, "max": 40.0})
        self.assertEqual(by_field["flow_cm_s"]["scope"], "experiment_range")
        self.assertEqual(by_field["oxygen_percent"]["value"], {"min": 16.0, "max": 21.0})
        self.assertEqual(by_field["oxygen_percent"]["scope"], "experiment_range")

    def test_single_number_before_a_range_keeps_its_reported_scope(self):
        text = "Tests were performed at 18.7% O2 in 1 atm."
        by_field = fields(extract_chunk(chunk(text)))
        self.assertEqual(by_field["oxygen_percent"]["value"], 18.7)
        self.assertEqual(by_field["pressure_kpa"]["value"], 101.325)

    def test_named_species_is_not_inferred_as_oxygen(self):
        text = "The chamber was held at 1 atm in 20% O2 / 75% CO2 / 5% N2."
        by_field = fields(extract_chunk(chunk(text)))
        self.assertEqual(by_field["oxygen_percent"]["value"], 20.0)

    def test_gas_composition_without_oxygen_produces_no_oxygen_record(self):
        records = extract_chunk(chunk("The atmosphere contained 5% CO2 and 95% nitrogen."))
        self.assertNotIn("oxygen_percent", fields(records))

    def test_planned_and_background_mentions_never_become_matching_evidence(self):
        planned = fields(extract_chunk(chunk("Saffire-I will be conducted at an air flow of 20 cm/s.")))
        background = fields(extract_chunk(chunk("Previous studies reported 21% oxygen in the chamber.")))
        self.assertEqual(planned["flow_cm_s"]["evidence_status"], "proposed")
        self.assertFalse(planned["flow_cm_s"]["matching_eligible"])
        self.assertEqual(background["oxygen_percent"]["evidence_status"], "background")
        self.assertFalse(background["oxygen_percent"]["matching_eligible"])

    def test_instrument_resolution_is_not_a_test_condition(self):
        record = fields(extract_chunk(chunk("The resolution of the CSA-CO was 0.1% O2.")))["oxygen_percent"]
        self.assertEqual(record["scope"], "instrument_metadata")
        self.assertFalse(record["matching_eligible"])

    def test_text_metadata_is_keyworded_with_quotes_and_matching_eligibility(self):
        text = "Cast PMMA rods were burned in microgravity using a hot-wire igniter."
        by_field = fields(extract_chunk(chunk(text)))
        self.assertEqual(by_field["gravity"]["value"], "microgravity")
        self.assertEqual(by_field["fuel"]["value"], "pmma")
        self.assertEqual(by_field["geometry"]["value"], "rod")
        self.assertEqual(by_field["ignition"]["value"], "hot_wire")
        for record in by_field.values():
            self.assertTrue(record["matching_eligible"])
            self.assertIn(record["quote"], text)

    def test_flame_spread_rates_are_not_treated_as_imposed_airflow(self):
        records = extract_chunk(chunk("The flame spread rate was 0.5 cm/s in the sample."))
        self.assertNotIn("flow_cm_s", fields(records))


class InvestigationGroupingTests(unittest.TestCase):
    def test_bass_aliases_share_one_investigation_without_duplicate_records(self):
        text = "Cast PMMA rods were burned in microgravity."
        chunks = [chunk(text, experiment="BASS", chunk_id="c1", source_id="s1"),
                  chunk(text, experiment="BASS-II", chunk_id="c2", source_id="s2")]
        groups = investigations(chunks)
        self.assertEqual([group["investigation_id"] for group in groups], ["BASS-II"])
        group = groups[0]
        self.assertEqual(group["experiment_names"], ["BASS", "BASS-II"])
        self.assertEqual(group["source_ids"], ["s1", "s2"])
        self.assertEqual(len(group["records"]), 6)
        for source_id in ("s1", "s2"):
            self.assertEqual(sum(row["source_id"] == source_id for row in group["records"]), 3)
        for record in group["records"]:
            self.assertIn(record["quote"], text)

    def test_a_source_without_conditions_does_not_create_invented_metadata(self):
        groups = investigations([chunk("An unrelated abstract about mission planning.")])
        self.assertNotIn("BASS-II", [group["investigation_id"] for group in groups])


if __name__ == "__main__":
    unittest.main()
