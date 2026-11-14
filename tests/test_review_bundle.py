"""Synthetic public handoff exports; no scientific grades or model calls."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from axiom.benchmark_run import _checkpoint, _directory, _hash, _read, _write, prepare_review_packet
from axiom.review_bundle import DECLARATIONS, MEMBERS, prepare_review_bundle


class ReviewBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run_id = 'synthetic-review-export'
        self.directory = _directory(self.root, self.run_id)
        self.directory.mkdir(parents=True)
        text = 'Synthetic source text only.'
        self.corpus = [dict(source_id='source', chunk_id='chunk', text=text,
                            sha256=hashlib.sha256(text.encode()).hexdigest())]
        inputs = dict(questions=[dict(question_id='Q001',question='Synthetic question?',rubric='RUBRIC_NOT_FOR_REVIEW'),
                                 dict(question_id='Q002',question='Synthetic failed question?')],
                      corpus_sha256=_hash(self.corpus))
        self.manifest = dict(run_id=self.run_id,status='completed_with_errors',inputs=inputs,
                             input_fingerprint=_hash(inputs),jobs=[
                                 dict(question_id='Q001',system='baseline',split='dev',block_reason=None),
                                 dict(question_id='Q001',system='ignis',split='dev',block_reason=None),
                                 dict(question_id='Q002',system='baseline',split='test',block_reason=None)])
        for job in self.manifest['jobs']:
            failed = job['question_id'] == 'Q002'
            prediction = dict(question_id=job['question_id'],system=job['system'],answer='' if failed else 'Synthetic answer.',
                              abstained=failed,claims=[] if failed else [dict(text='Synthetic claim.',verdict='unreviewed',citations=[])],
                              model_calls=[],latency_ms=1)
            if failed:
                prediction['execution_error'] = 'FAILED_BODY_NOT_FOR_REVIEW'
            record = dict(question_id=job['question_id'],system=job['system'],prediction=prediction,
                          run={'run_id':'synthetic'},generation_scope='Synthetic named source.',
                          input_fingerprint=self.manifest['input_fingerprint'])
            record['record_sha256'] = _hash(record)
            _write(self.directory/'jobs'/(job['question_id']+'--'+job['system']+'.json'),record)
        _write(self.directory/'corpus_snapshot.json',self.corpus)
        _checkpoint(self.directory,self.manifest)
        (self.root/'data').mkdir()
        _write(self.root/'data/sources.json',{'sources':[]})
        _write(self.root/'data/benchmark_sources.json',{'sources':[]})
        (self.root/'docs').mkdir()
        (self.root/'docs/INDEPENDENT_REVIEW.md').write_text('Synthetic reviewer instructions. Unknown grades stay pending.')
        (self.directory/'credentials.private.json').write_text('PRIVATE_VALUE_NOT_FOR_REVIEW')

    def export(self):
        with patch('axiom.benchmark_run.make_model',side_effect=AssertionError('No inference')):
            return prepare_review_bundle(self.root,self.run_id)

    def test_public_archive_has_fixed_members_and_no_private_labels_or_failed_bodies(self):
        result = self.export()
        self.assertEqual(result['items'],2)
        self.assertEqual(result['grades_created'],0)
        self.assertFalse(result['private_mapping_included'])
        with zipfile.ZipFile(result['bundle']) as archive:
            self.assertEqual(set(archive.namelist()),MEMBERS)
            combined=b'\n'.join(archive.read(name) for name in archive.namelist())
            for secret in (b'RUBRIC_NOT_FOR_REVIEW',b'PRIVATE_VALUE_NOT_FOR_REVIEW',b'FAILED_BODY_NOT_FOR_REVIEW'):
                self.assertNotIn(secret,combined)
            self.assertEqual(archive.read('review_packet.json'),(self.directory/'review_packet.json').read_bytes())
            template=json.loads(archive.read('review_packet.template.json'))
            for field in ('reviewer','qualification','reviewed_at','independence_declaration','independent','human_review'):
                self.assertIsNone(template[field])
            self.assertTrue(all(item['grading'] is None for item in template['items']))
            manifest=json.loads(archive.read('bundle_manifest.json'))
            for item in manifest['files']:
                self.assertEqual(hashlib.sha256(archive.read(item['path'])).hexdigest(),item['sha256'])

    def test_reexport_is_byte_identical_and_does_not_regenerate_shuffled_ids(self):
        first=self.export();blob=Path(first['bundle']).read_bytes()
        packet=(self.directory/'review_packet.json').read_bytes()
        private=(self.directory/'review_key.private.json').read_bytes()
        with patch('axiom.review_bundle.prepare_review_packet',wraps=prepare_review_packet) as prepare:
            second=self.export()
        prepare.assert_called_once_with(self.root,self.run_id)
        self.assertEqual(first['bundle_sha256'],second['bundle_sha256'])
        self.assertEqual(Path(second['bundle']).read_bytes(),blob)
        self.assertEqual((self.directory/'review_packet.json').read_bytes(),packet)
        self.assertEqual((self.directory/'review_key.private.json').read_bytes(),private)

    def test_incomplete_existing_mapping_pair_is_not_regenerated(self):
        _write(self.directory/'review_key.private.json',{'benchmark_run_id':self.run_id,'keys':[]})
        with self.assertRaisesRegex(ValueError,'Incomplete'):
            self.export()
        self.assertFalse((self.directory/'review_packet.json').exists())

    def test_packet_text_or_private_hash_tampering_fails_closed(self):
        self.export()
        path=self.directory/'review_packet.json';original=path.read_bytes()
        packet=json.loads(original);packet['items'][0]['answer']='Forged answer';_write(path,packet)
        with self.assertRaisesRegex(ValueError,'answer or grades'):
            self.export()
        path.write_bytes(original)
        key=self.directory/'review_key.private.json';value=_read(key);value['keys'][0]['prediction_sha256']='0'*64;_write(key,value)
        with self.assertRaisesRegex(ValueError,'hash is stale'):
            self.export()

    def test_filled_template_is_preserved_instead_of_overwritten(self):
        result=self.export();path=Path(result['template']);value=_read(path);value['human_review']=True;_write(path,value)
        original=path.read_bytes();bundle=Path(result['bundle']).read_bytes()
        with self.assertRaisesRegex(ValueError,'template has been edited'):
            self.export()
        self.assertEqual(path.read_bytes(),original)
        self.assertEqual(Path(result['bundle']).read_bytes(),bundle)

    def test_only_exact_null_declarations_are_blank_and_edits_remain_intact(self):
        result=self.export();path=Path(result['template']);blank=_read(path)
        bundle=Path(result['bundle']).read_bytes()
        for field in DECLARATIONS:
            for value in (False,0,'','filled',[],{}):
                with self.subTest(field=field,value=value):
                    edited=deepcopy(blank);edited[field]=value;_write(path,edited)
                    original=path.read_bytes()
                    with self.assertRaisesRegex(ValueError,'template has been edited'):
                        self.export()
                    self.assertEqual(path.read_bytes(),original)
                    self.assertEqual(Path(result['bundle']).read_bytes(),bundle)
            with self.subTest(field=field,value='missing'):
                edited=deepcopy(blank);del edited[field];_write(path,edited)
                original=path.read_bytes()
                with self.assertRaisesRegex(ValueError,'template has been edited'):
                    self.export()
                self.assertEqual(path.read_bytes(),original)
        _write(path,blank)

    def test_untouched_template_content_keeps_its_existing_format(self):
        result=self.export();path=Path(result['template'])
        blob=json.dumps(_read(path),separators=(',',':')).encode('utf-8')
        path.write_bytes(blob)
        result=self.export()
        self.assertEqual(path.read_bytes(),blob)
        with zipfile.ZipFile(result['bundle']) as archive:
            self.assertEqual(archive.read('review_packet.template.json'),blob)

    def test_corpus_mismatch_and_oversized_sources_are_rejected(self):
        self.export()
        corpus=self.directory/'corpus_snapshot.json';original=corpus.read_bytes();corpus.write_text('[]')
        with self.assertRaisesRegex(ValueError,'corpus snapshot'):
            self.export()
        corpus.write_bytes(original)
        (self.root/'docs/INDEPENDENT_REVIEW.md').write_bytes(b'x'*(2*1024*1024+1))
        with self.assertRaisesRegex(ValueError,'size limit'):
            self.export()

    def test_duplicate_packet_ids_are_rejected_without_creating_new_key(self):
        self.export();path=self.directory/'review_packet.json';value=_read(path)
        value['items'].append(deepcopy(value['items'][0]));_write(path,value)
        with self.assertRaisesRegex(ValueError,'duplicate'):
            self.export()

    def test_redirected_output_is_not_followed(self):
        self.export();bundle=self.directory/'review_bundle.zip';bundle.unlink()
        outside=self.root/'outside.zip';outside.write_bytes(b'KEEP')
        try:
            bundle.symlink_to(outside)
        except OSError:
            self.skipTest('Symlink creation unavailable on this host')
        with self.assertRaisesRegex(ValueError,'redirects'):
            self.export()
        self.assertEqual(outside.read_bytes(),b'KEEP')


if __name__=='__main__':
    unittest.main()
