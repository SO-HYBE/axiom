import unittest
import json
from pathlib import Path
from unittest.mock import patch
from axiom.corpus_audit import audit
from test_research import corpus

class AuditTests(unittest.TestCase):
    def test_ai_draft_does_not_pass_review_gate(self):
        records = [{'record_id': 'r1', 'chunk_id': 'c1', 'review_status': 'ai_draft', 'reviewer': None}]
        with patch('axiom.corpus_audit.load_chunks', return_value=corpus()), patch.object(Path,'exists',return_value=True), patch.object(Path,'read_text', return_value='\n'.join(map(json.dumps,records))):
            result = audit(Path('.'))
        self.assertEqual(result['condition_records'],1)
        self.assertEqual(result['human_reviewed_condition_records'],0)
        self.assertFalse(any(result['gates'].values()))
