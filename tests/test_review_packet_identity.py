"""Prepared review IDs are immutable across retries and concurrent exports."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from axiom.benchmark_run import _hash, _read, _write, prepare_review_packet
import test_review_bundle as fixtures


class ReviewPacketIdentityTests(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.ReviewBundleTests('runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.root,self.directory,self.run_id=fixture.root,fixture.directory,fixture.run_id

    def prepare(self):
        with patch('axiom.benchmark_run.make_model',side_effect=AssertionError('No inference')):
            return prepare_review_packet(self.root,self.run_id)

    def pair(self):
        return {name:(self.directory/name).read_bytes()
                for name in ('review_packet.json','review_key.private.json')}

    def test_second_call_validates_without_new_ids_or_file_rewrites(self):
        first=self.prepare();before=self.pair()
        with patch('axiom.benchmark_run.uuid4',side_effect=AssertionError('Existing IDs are immutable')):
            self.assertEqual(self.prepare(),first)
        self.assertEqual(self.pair(),before)
        self.assertEqual(first['items'],2)  # The failed output is never a review item.

    def test_concurrent_preparation_creates_one_pair_only(self):
        start=threading.Barrier(2)
        def worker():
            start.wait(timeout=3)
            return prepare_review_packet(self.root,self.run_id)
        with patch('axiom.benchmark_run.uuid4',wraps=uuid4) as identifiers:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(lambda _:worker(),range(2)))
        self.assertEqual(results[0],results[1])
        self.assertEqual(identifiers.call_count,2)
        before=self.pair();self.prepare();self.assertEqual(self.pair(),before)

    def test_either_partial_pair_is_refused_and_preserved(self):
        self.prepare();original=self.pair()
        for missing in original:
            with self.subTest(missing=missing):
                for name,blob in original.items():
                    (self.directory/name).write_bytes(blob)
                (self.directory/missing).unlink()
                with self.assertRaisesRegex(ValueError,'Incomplete'):
                    self.prepare()
                self.assertFalse((self.directory/missing).exists())
                for name,blob in original.items():
                    if name!=missing:
                        self.assertEqual((self.directory/name).read_bytes(),blob)

    def test_changed_answer_claim_count_private_mapping_or_duplicate_id_is_refused(self):
        self.prepare();original=self.pair()
        packet=_read(self.directory/'review_packet.json')
        private=_read(self.directory/'review_key.private.json')
        for mode in ('answer','claims','hash','duplicate','unknown','missing'):
            with self.subTest(mode=mode):
                for name,blob in original.items():
                    (self.directory/name).write_bytes(blob)
                edited=deepcopy(private if mode=='hash' else packet)
                if mode=='hash':
                    edited['keys'][0]['prediction_sha256']='0'*64
                    name='review_key.private.json'
                else:
                    name='review_packet.json'
                    if mode=='answer':edited['items'][0]['answer']='Changed text'
                    elif mode=='claims':edited['items'][0]['claims']=[]
                    elif mode=='duplicate':edited['items'].append(deepcopy(edited['items'][0]))
                    elif mode=='unknown':edited['items'][0]['item_id']='unknown-id'
                    else:edited['items'].pop()
                _write(self.directory/name,edited)
                before=self.pair()
                with self.assertRaises(ValueError):self.prepare()
                self.assertEqual(self.pair(),before)

    def test_changed_authoritative_prediction_refuses_stale_packet(self):
        self.prepare();before=self.pair()
        path=self.directory/'jobs/Q001--baseline.json';record=_read(path)
        record.pop('record_sha256')
        record['prediction']['answer']='New saved answer after packet preparation'
        record['record_sha256']=_hash(record);_write(path,record)
        with self.assertRaisesRegex(ValueError,'hash is stale'):
            self.prepare()
        self.assertEqual(self.pair(),before)


if __name__=='__main__':
    unittest.main()
