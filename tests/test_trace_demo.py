import json
import tempfile
import unittest
from pathlib import Path

from axiom.trace_demo import build_demo


def _benchmark(root):
    jobs = root / 'runs/benchmarks/3c3cc0f1e4b949a8a33296e94417f13c/jobs'
    jobs.mkdir(parents=True)
    run = {
        'run_id': 'saved-run', 'system': 'ignis', 'question': 'q', 'abstained': False,
        'evidence': [{'chunk_id': 'e1', 'conditions': {}}], 'target': {},
        'claims': [{'text': 'claim', 'citations': [{'chunk_id': 'e1', 'quote': 'q',
                                                    'source_id': 's1'}],
                    'evidence_status': 'supported', 'applicability': 'documented_alignment'}],
        'applicability_requested': True,
    }
    (jobs / 'Q001--ignis.json').write_text(json.dumps({'question_id': 'Q001', 'run': run}),
                                           encoding='utf-8')


class TraceDemoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        _benchmark(self.root)

    def test_remove_validation_is_separate_from_original(self):
        demo = build_demo(self.root, 'remove_validation')
        self.assertIn('METADATA_VALIDATED', [event['type'] for event in demo['original']['events']])
        self.assertNotIn('METADATA_VALIDATED', [event['type'] for event in demo['mutated']['events']])
        self.assertEqual(demo['mutation']['event_type'], 'METADATA_VALIDATED')
        self.assertEqual(demo['mutated']['manifest'], demo['original']['manifest'])

    def test_publish_before_verify_changes_delivery_order_only(self):
        demo = build_demo(self.root, 'publish_before_verify')
        types = [event['type'] for event in demo['mutated']['events']]
        self.assertLess(types.index('CLAIM_PUBLISHED'), types.index('CLAIM_VERIFIED'))
        seqs = [event['seq'] for event in demo['mutated']['events']]
        self.assertEqual(sorted(seqs), list(range(1, len(seqs) + 1)))
        self.assertNotEqual(seqs, sorted(seqs))
        self.assertFalse(demo['mutated_verdict']['trust']['flags']['delivery_order_reliable'])

    def test_corrupt_evidence_reference_keeps_stale_hash(self):
        demo = build_demo(self.root, 'corrupt_evidence_id')
        integrity = demo['mutated_verdict']['trust']
        self.assertTrue(integrity['flags']['hash_mismatch'])
        self.assertEqual(demo['original']['events'][1]['evidence_ids'], ['e1'])

    def test_unknown_preset_is_rejected(self):
        with self.assertRaises(ValueError):
            build_demo(self.root, 'invented')


if __name__ == '__main__':
    unittest.main()
