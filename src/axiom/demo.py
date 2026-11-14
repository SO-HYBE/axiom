"""Verified offline replays of three observed research behaviors.

No inference or network client is called. Records remain unchanged; a returned
presentation copy clearly identifies replay and retains historical call audits.
Hashes establish local integrity, not scientific truth or publisher authorship.
"""
from copy import deepcopy
import hashlib
from pathlib import Path
import re

from .benchmark_run import _directory, _hash, _read, _records, _write
from .critic import normalized
from .review import review_read_lock, review_write_lock


RUN_ID = '3c3cc0f1e4b949a8a33296e94417f13c'
MANIFEST = 'data/demo.json'
SCHEMA = 'ignis-demos-v1'
REPLAY_NOTICE = 'Saved demonstration replay; no new model request was made. Scientific review is still pending.'
CASES = (
    dict(id='source-description', question_id='Q002', system='ignis',
         title='An answer with its source', behavior='source_description',
         description='Open the FLEX source description and its exact cited words. The model-checked claim remains provisional.'),
    dict(id='scope-check', question_id='Q008', system='ignis',
         title='A conclusion held back', behavior='scope_withheld',
         description='A whole-cabin guarantee is withheld because the recorded conditions and applicability evidence are incomplete.'),
    dict(id='insufficient-measurements', question_id='Q022', system='ignis',
         title='A source without the requested measurements', behavior='scope_insufficient',
         description='The requested abstract is supplied as context. The saved answer withholds confidence intervals that the abstract does not provide.'),
)
CARD_FIELDS = ('id', 'title', 'description', 'behavior', 'question_id', 'system')


def _manifest_path(root):
    path = root / MANIFEST
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError('Demo manifest redirects outside the project')
    return path


def _validate_manifest(value):
    if not isinstance(value, dict) or value.get('schema_version') != SCHEMA:
        raise ValueError('Invalid demo manifest')
    if value.get('benchmark_run_id') != RUN_ID:
        raise ValueError('Unexpected demo benchmark identity')
    for field in ('input_fingerprint', 'corpus_sha256'):
        if not isinstance(value.get(field), str) or not re.fullmatch('[a-f0-9]{64}', value[field]):
            raise ValueError('Invalid demo source digest')
    entries = value.get('demos')
    if not isinstance(entries, list) or len(entries) != len(CASES):
        raise ValueError('Demo manifest must contain the three documented cases')
    if len({entry.get('id') for entry in entries if isinstance(entry, dict)}) != len(CASES):
        raise ValueError('Duplicate demo identity')
    for entry, expected in zip(entries, CASES):
        if not isinstance(entry, dict) or any(entry.get(key) != expected[key] for key in CARD_FIELDS):
            raise ValueError('Demo case identity or description mismatch')
        if not isinstance(entry.get('record_sha256'), str) or not re.fullmatch('[a-f0-9]{64}', entry['record_sha256']):
            raise ValueError('Invalid demo record digest')
    return entries


def _load_records(root, entries):
    directory = _directory(root, RUN_ID)
    manifest = _read(directory / 'manifest.json')
    if (not isinstance(manifest, dict) or manifest.get('run_id') != RUN_ID
            or not isinstance(manifest.get('inputs'), dict)
            or _hash(manifest['inputs']) != manifest.get('input_fingerprint')):
        raise ValueError('Demo benchmark input integrity mismatch')
    selected = {(entry['question_id'], entry['system']) for entry in entries}
    jobs = [job for job in manifest.get('jobs', [])
            if (job.get('question_id'), job.get('system')) in selected]
    if len(jobs) != len(selected) or any(job.get('block_reason') for job in jobs):
        raise ValueError('Demo job is missing or source-blocked')
    records = _records(directory, dict(manifest, jobs=jobs))
    if len(records) != len(selected):
        raise ValueError('A saved demo job is missing')
    corpus = _read(directory / 'corpus_snapshot.json')
    if not isinstance(corpus, list) or _hash(corpus) != manifest['inputs'].get('corpus_sha256'):
        raise ValueError('Demo corpus snapshot integrity mismatch')
    by_chunk = {}
    for chunk in corpus:
        if (not isinstance(chunk, dict) or not isinstance(chunk.get('chunk_id'), str)
                or chunk['chunk_id'] in by_chunk or not isinstance(chunk.get('text'), str)
                or hashlib.sha256(chunk['text'].encode()).hexdigest() != chunk.get('sha256')):
            raise ValueError('Invalid frozen demo source passage')
        by_chunk[chunk['chunk_id']] = chunk
    return manifest, {(record['question_id'], record['system']): record for record in records}, by_chunk


def _check_record(entry, record, manifest, by_chunk):
    run, prediction = record['run'], record['prediction']
    if record['record_sha256'] != entry['record_sha256']:
        raise ValueError('Demo saved record changed')
    if prediction.get('execution_error') or prediction.get('error') or run.get('error'):
        raise ValueError('A failed execution cannot be a successful demonstration')
    if any(prediction.get(field) != run.get(field) for field in ('answer', 'abstained', 'claims')):
        raise ValueError('Demo prediction differs from its recorded answer')
    scope = next((row for row in manifest['inputs'].get('scope_plan', [])
                  if row.get('question_id') == entry['question_id']), None)
    if not scope or not scope.get('all_reference_scopes_available'):
        raise ValueError('Demo named source scope is unavailable')
    allowed = set(scope.get('allowed_chunk_ids', []))
    evidence = run.get('evidence')
    if not isinstance(evidence, list):
        raise ValueError('Invalid demo evidence')
    selected = {}
    for chunk in evidence:
        identifier = chunk.get('chunk_id') if isinstance(chunk, dict) else None
        frozen = by_chunk.get(identifier)
        if (identifier not in allowed or frozen is None
                or any(chunk.get(field) != frozen.get(field) for field in ('source_id', 'sha256', 'text', 'locator'))):
            raise ValueError('Demo evidence is outside its frozen source scope')
        selected[identifier] = chunk
    claims = run.get('claims', [])
    checks = run.get('draft_checks', [])
    citations = [citation for claim in claims + checks for citation in claim.get('citations', [])]
    for citation in citations:
        chunk = selected.get(citation.get('chunk_id'))
        quote = citation.get('quote')
        if (chunk is None or citation.get('source_id') != chunk['source_id']
                or not isinstance(quote, str) or not normalized(quote)
                or normalized(quote) not in normalized(chunk['text'])):
            raise ValueError('Demo citation is not traceable to its exact supplied passage')
    behavior = entry['behavior']
    if behavior == 'source_description':
        if run['abstained'] or not claims or not citations:
            raise ValueError('Source-description demonstration behavior changed')
    elif behavior == 'scope_withheld':
        reasons = [reason for check in checks for reason in check.get('issues', [])]
        if (not run['abstained'] or claims or not checks or not any(
                reason.startswith('condition_unknown:') or reason == 'operational_inference_requires_expert_review'
                for reason in reasons)):
            raise ValueError('Scope-withholding demonstration behavior changed')
    elif behavior == 'scope_insufficient':
        selection = run.get('evidence_selection', {})
        if (not run['abstained'] or claims or not evidence
                or selection.get('mode') != 'explicit_source_scope'
                or selection.get('explicit_scope_complete') is not True):
            raise ValueError('Source-insufficiency demonstration behavior changed')


def _bundle(root):
    root = Path(root).resolve()
    value = _read(_manifest_path(root))
    entries = _validate_manifest(value)
    with review_read_lock(_directory(root, RUN_ID)):
        manifest, records, by_chunk = _load_records(root, entries)
        if (value['input_fingerprint'] != manifest['input_fingerprint']
                or value['corpus_sha256'] != manifest['inputs']['corpus_sha256']):
            raise ValueError('Demo manifest differs from its frozen benchmark')
        for entry in entries:
            _check_record(entry, records[entry['question_id'], entry['system']], manifest, by_chunk)
    return entries, records


def _card(entry, record):
    return dict({key: entry[key] for key in CARD_FIELDS}, question=record['run']['question'],
                benchmark_run_id=RUN_ID, replay=True, model_calls_made=0)


def list_demos(root):
    """Return verified replay cards; a checkout without a demo manifest has none."""
    root = Path(root).resolve()
    if not _manifest_path(root).exists():
        return []
    entries, records = _bundle(root)
    return [_card(entry, records[entry['question_id'], entry['system']]) for entry in entries]


def get_demo(root, identifier):
    """Return a display copy of a saved run, without inference or mutation."""
    if identifier not in {case['id'] for case in CASES}:
        raise ValueError('Unknown demonstration')
    entries, records = _bundle(root)
    entry = next(entry for entry in entries if entry['id'] == identifier)
    record = records[entry['question_id'], entry['system']]
    run = deepcopy(record['run'])
    run['notice'] = REPLAY_NOTICE
    run['replay'] = dict(saved=True, model_calls_made=0, benchmark_run_id=RUN_ID,
                         question_id=entry['question_id'], record_sha256=record['record_sha256'])
    return dict(demo=_card(entry, record), run=run, replay=True, notice=REPLAY_NOTICE)


def prepare_demos(root):
    """Pin the three existing saved records; no fabricated answer or new call."""
    root = Path(root).resolve()
    entries = [dict(case) for case in CASES]
    with review_write_lock(_directory(root, RUN_ID)):
        manifest, records, by_chunk = _load_records(root, entries)
        for entry in entries:
            entry['record_sha256'] = records[entry['question_id'], entry['system']]['record_sha256']
            _check_record(entry, records[entry['question_id'], entry['system']], manifest, by_chunk)
        value = dict(schema_version=SCHEMA, benchmark_run_id=RUN_ID,
                     input_fingerprint=manifest['input_fingerprint'],
                     corpus_sha256=manifest['inputs']['corpus_sha256'], demos=entries,
                     notice='Saved recorded behaviors, not independent scientific grades. No new model calls are made.')
        _write(_manifest_path(root), value)
    return value
