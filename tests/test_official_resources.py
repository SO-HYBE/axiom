import json
from pathlib import Path
import tempfile
import unittest

from axiom.official_resources import (build_report, ingest_events, load_inventory,
                                     parse_webvtt, process_structured)
from axiom.research import load_chunks
from axiom.retrieval import search


ROOT = Path(__file__).resolve().parents[1]


class OfficialResourceTests(unittest.TestCase):
    def test_inventory_has_all_supplied_resources_and_categories(self):
        inventory = load_inventory(ROOT)
        self.assertEqual([row['resource_id'] for row in inventory['resources']],
                         [f'R{i}' for i in range(1, 11)])
        self.assertEqual(inventory['resources'][0]['category'], 'primary_experimental_data')
        self.assertEqual(inventory['resources'][7]['category'], 'technology_transfer')

    def test_resource_report_does_not_count_catalog_or_listing_as_raw_dataset(self):
        report = build_report(ROOT)
        psi = report['resources'][0]
        self.assertEqual(report['resource_count'], 10)
        self.assertEqual(psi['raw_experimental_files'], 0)
        self.assertEqual(psi['acquisition_status'], 'catalog_metadata_acquired_raw_datasets_not_acquired')
        self.assertEqual(report['extracted_experiment_record_count'], 0)
        self.assertEqual(len(psi['related_existing_source_records']), 3)
        self.assertTrue(all(row['assets'] for row in psi['related_existing_source_records']))

    def test_existing_psi_catalog_passages_use_shared_retrieval_as_explicit_descriptions(self):
        chunks = load_chunks(ROOT, include_named_sources=True)
        self.assertTrue(any(c.get('resource_id') == 'R1' and c.get('source_id') == 'psi-25' for c in chunks))
        self.assertEqual(search('BASS-II objective', chunks, source_ids=['psi-25']), [])
        hits = search('BASS-II objective', chunks, source_ids=['psi-25'],
                      include_source_descriptions=True)
        self.assertTrue(hits)
        self.assertEqual(hits[0]['ranking']['resource_id'], 'R1')
        self.assertEqual(hits[0]['ranking']['source_category'], 'repository_catalog')
        self.assertIn('not experimental data', hits[0]['ranking']['source_interpretation'])

    def test_duplicate_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            value = json.loads((ROOT / 'data/official_resources.json').read_text())
            value['resources'][1]['resource_id'] = 'R1'
            (root / 'data/official_resources.json').write_text(json.dumps(value))
            with self.assertRaises(ValueError):
                load_inventory(root)

    def test_structured_data_preserves_headers_values_and_xml_attributes(self):
        csv_value = process_structured(b'id,oxygen\nA,21 vol%\n', 'text/csv')
        self.assertEqual(csv_value['columns'], ['id', 'oxygen'])
        self.assertEqual(csv_value['records'][0], {'id': 'A', 'oxygen': '21 vol%'})
        xml_value = process_structured(b'<run unit="kPa"><pressure>101.3</pressure></run>', 'application/xml')
        self.assertEqual(xml_value['value']['attributes'], {'unit': 'kPa'})
        self.assertEqual(xml_value['value']['children'][0]['text'], '101.3')

    def test_caption_parser_keeps_timecodes(self):
        cues = parse_webvtt(b'WEBVTT\n\n00:00:01.000 --> 00:00:02.500\nFlame study\n')
        self.assertEqual(cues, [{'start': '00:00:01.000', 'end': '00:00:02.500', 'text': 'Flame study'}])

    def test_ingestion_events_are_versioned_hashed_and_reject_unknown_stage(self):
        trace = ingest_events('R2', [{'type': 'RESOURCE_DISCOVERED', 'timestamp': '2026-11-13T00:00:00Z'}])
        self.assertEqual(trace['schema_version'], 'axiom-resource-events-v1')
        self.assertEqual(trace['manifest']['event_count'], 1)
        self.assertEqual(len(trace['events'][0]['content_hash']), 64)
        with self.assertRaises(ValueError):
            ingest_events('R2', [{'type': 'CLAIM_VERIFIED'}])


if __name__ == '__main__':
    unittest.main()
