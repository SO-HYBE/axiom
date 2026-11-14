import json
import tempfile
import unittest
from pathlib import Path

from axiom.server import load_axiom_result


class AxiomResultLoadingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_missing_is_explicitly_not_run(self):
        self.assertEqual(load_axiom_result(self.root, 'evaluation'),
                         {'status': 'not_run', 'results': None})

    def test_allowlisted_json_is_returned(self):
        target = self.root / 'runs/axiom/evaluation/results.json'
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps({'dataset': {'questions': 36}}), encoding='utf-8')
        self.assertEqual(load_axiom_result(self.root, 'evaluation'), {
            'status': 'available', 'results': {'dataset': {'questions': 36}}})

    def test_malformed_or_non_object_results_are_rejected(self):
        target = self.root / 'runs/axiom/trace_lab/results.json'
        target.parent.mkdir(parents=True)
        target.write_text('[1, 2]', encoding='utf-8')
        with self.assertRaises(ValueError):
            load_axiom_result(self.root, 'trace-lab')
        target.write_text('{bad json', encoding='utf-8')
        with self.assertRaises(json.JSONDecodeError):
            load_axiom_result(self.root, 'trace-lab')

    def test_unknown_result_name_is_rejected(self):
        with self.assertRaises(KeyError):
            load_axiom_result(self.root, '../secret')


if __name__ == '__main__':
    unittest.main()
