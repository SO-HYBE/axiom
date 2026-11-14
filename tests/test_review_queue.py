import unittest
from axiom.review_queue import build_queue
from test_research import corpus

class ReviewQueueTests(unittest.TestCase):
    def test_queue_is_deterministic_and_never_approval(self):
        chunks=corpus(); records=[{'record_id':'r1','chunk_id':'c1'}]
        a=build_queue(chunks,records)
        self.assertEqual(a,build_queue(chunks,records))
        self.assertEqual(len(a),1)
        self.assertEqual(a[0]['review_status'],'pending_human_review')
        self.assertIsNone(a[0]['reviewer'])
        self.assertEqual(a[0]['condition_record_ids'],['r1'])
    def test_empty_corpus_terminates(self):
        self.assertEqual(build_queue([],[]),[])
