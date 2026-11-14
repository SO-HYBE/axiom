"""Frozen, resumable generation jobs. Missing source scope and grades stay missing."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from time import perf_counter
from uuid import uuid4

from .benchmark_audit import audit_benchmark
from .benchmark_report import summarize_benchmark
from .benchmark_scope import load_scope_chunks
from .benchmark_named_sources import load_named_chunks
from .evaluate import SYSTEMS, _validate_prediction
from .providers import make_model
from .research import load_chunks, load_condition_records, run
from .review import review_write_lock

MAX_BYTES = 2 * 1024 * 1024
ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,99}\Z')


def _now():
    return datetime.now(timezone.utc).isoformat()


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _read(path):
    if path.is_symlink():
        raise ValueError('Redirected benchmark file is not allowed')
    with path.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Benchmark record exceeds the size limit')
    def invalid(_):
        raise ValueError('Nonfinite benchmark number')
    return json.loads(raw, parse_constant=invalid)


def _write(path, value):
    data = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode()
    if len(data) > MAX_BYTES or path.is_symlink():
        raise ValueError('Benchmark output exceeds bounds or redirects')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.checkpoint-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def _directory(root, identifier):
    if not isinstance(identifier, str) or not ID.fullmatch(identifier):
        raise ValueError('Invalid benchmark run ID')
    root = Path(root).resolve()
    directory = root / 'runs' / 'benchmarks' / identifier
    for path in (root / 'runs', root / 'runs/benchmarks', directory, directory / 'jobs', directory / 'code_snapshot'):
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('Benchmark directory redirects outside the project')
    return directory


def _questions(root, split, question_ids, limit):
    path = root / 'benchmarks/questions.jsonl'
    if path.stat().st_size > MAX_BYTES:
        raise ValueError('Question set exceeds bounds')
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('question_id'), str) or not ID.fullmatch(row['question_id']):
            raise ValueError('Invalid benchmark question ID')
        if row['question_id'] in seen:
            raise ValueError('Duplicate benchmark question ID')
        seen.add(row['question_id'])
        if not isinstance(row.get('question'), str) or not row['question'].strip() or len(row['question']) > 4000:
            raise ValueError('Invalid benchmark question')
        if row.get('split') not in ('dev', 'test'):
            raise ValueError('Invalid benchmark split')
    if question_ids is not None and (not isinstance(question_ids, list) or not question_ids or len(set(question_ids)) != len(question_ids) or set(question_ids) - seen):
        raise ValueError('Question selection has duplicates or unknown IDs')
    selected = [row for row in rows if (split == 'all' or row['split'] == split) and (question_ids is None or row['question_id'] in question_ids)]
    if limit is not None:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('Question limit must be from 1 to 100')
        selected = selected[:limit]
    if not selected:
        raise ValueError('No questions selected')
    return selected


def _source_scope(question, references):
    # Explicit generation allowlist. No rubric, expected action, grade or split.
    lines = [question.get('scope', '')]
    for ref in references:
        lines.append(str(ref.get('url', '')) + ' | ' + str(ref.get('effective_locator') or ref.get('requested_locator', '')))
    return '\n'.join(lines)[:3000]


def _code_hashes():
    package = Path(__file__).parent
    return {name: hashlib.sha256((package / name).read_bytes()).hexdigest() for name in (
        'benchmark_run.py', 'benchmark_audit.py', 'benchmark_scope.py', 'model.py', 'providers.py',
        'research.py', 'retrieval.py', 'critic.py', 'evidence_conflicts.py', 'conditions.py',
        'benchmark_report.py', 'evaluate.py', 'provider_limits.py', 'benchmark_named_sources.py', 'source_text.py', 'archived_source.py')}


def _git(root):
    try:
        commit = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], capture_output=True, timeout=5,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        status = subprocess.run(['git', '-C', str(root), 'status', '--porcelain'], capture_output=True, timeout=5,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return {'commit': commit.stdout.decode().strip() if commit.returncode == 0 else None,
                'working_tree_dirty': bool(status.stdout.strip()) if status.returncode == 0 else None}
    except (OSError, subprocess.TimeoutExpired):
        return {'commit': None, 'working_tree_dirty': None}


def _prediction(question, system, result, scope_status):
    row = {key: deepcopy(result[key]) for key in ('answer', 'abstained', 'claims', 'latency_ms', 'model_calls') if key in result}
    row.update(question_id=question['question_id'], system=system, split=question['split'],
               run_id=result.get('run_id'), scope_status=scope_status,
               policy_withholding=bool(result.get('applicability_requested') and result.get('abstained')))
    if result.get('error'):
        row['execution_error'] = result['error']
    terminal_calls = {}
    for index, call in enumerate(row.get('model_calls', [])):
        terminal_calls[call.get('request_hash') or str(index)] = call
    failed_calls = [call.get('status') for call in terminal_calls.values()
                    if call.get('status') not in (None, 'success', 'cache_hit') and not call.get('cache_hit')]
    if failed_calls and not row.get('execution_error'):
        row['execution_error'] = 'A model call did not complete: ' + ', '.join(str(s) for s in failed_calls)
    if any((check.get('semantic_review') or {}).get('review_failure') for check in result.get('draft_checks', [])):
        row.setdefault('execution_error', 'A claim review could not complete.')
    # Scientific support stays in separate annotations, never copied from verdicts.
    _validate_prediction(row)
    return row


def _records(directory, manifest):
    records = []
    if not isinstance(manifest, dict) or not isinstance(manifest.get('jobs'), list):
        raise ValueError('Malformed benchmark job list')
    for job in manifest['jobs']:
        if (not isinstance(job, dict) or not isinstance(job.get('question_id'), str) or
                not ID.fullmatch(job['question_id']) or job.get('system') not in SYSTEMS):
            raise ValueError('Invalid saved benchmark job identity')
        path = directory / 'jobs' / (job['question_id'] + '--' + job['system'] + '.json')
        if not path.exists():
            continue
        record = _read(path)
        if (not isinstance(record, dict) or not isinstance(record.get('prediction'), dict)
                or not isinstance(record.get('run'), dict)):
            raise ValueError('Malformed saved benchmark job')
        digest = record.pop('record_sha256', None)
        if (digest != _hash(record) or record.get('input_fingerprint') != manifest['input_fingerprint'] or
                record.get('question_id') != job['question_id'] or record.get('system') != job['system'] or
                record.get('prediction', {}).get('question_id') != job['question_id'] or
                record.get('prediction', {}).get('system') != job['system']):
            raise ValueError('Saved job does not match the frozen benchmark')
        _validate_prediction(record['prediction'])
        record['record_sha256'] = digest
        records.append(record)
    return records


def _checkpoint(directory, manifest):
    records = _records(directory, manifest)
    predictions = [record['prediction'] for record in records]
    report = summarize_benchmark(manifest, predictions)
    report['benchmark_run_id'] = manifest['run_id']
    manifest['progress'] = report['progress']['overall']
    manifest['updated_at'] = _now()
    _write(directory / 'manifest.json', manifest)
    _write(directory / 'report.json', report)
    # This is a derived, atomically replaced export. Per-job files are authoritative.
    text = ''.join(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n' for row in predictions)
    _write(directory / 'predictions.json', predictions)
    temporary = directory / 'predictions.jsonl.tmp'
    if temporary.is_symlink() or (directory / 'predictions.jsonl').is_symlink():
        raise ValueError('Prediction export redirects')
    temporary.write_text(text, encoding='utf-8')
    os.replace(temporary, directory / 'predictions.jsonl')
    return report


def run_benchmark(root, *, provider, model=None, systems=('baseline', 'ignis'), split='dev',
                  question_ids=None, limit=None, max_jobs=None, resume=None, fresh=False, progress=None, diagnostics=False):
    """Execute eligible jobs once, checkpoint each, and stop at provider failure.

    Resume never retries or replaces failed outputs. A new run is required for a
    rerun, so failures cannot silently disappear. Missing named scopes stay pending.
    """
    root = Path(root).resolve()
    if provider not in ('groq', 'openrouter', 'ollama', 'extractive') or split not in ('dev', 'test', 'all'):
        raise ValueError('Invalid provider or split')
    if not isinstance(systems, (tuple, list)) or not systems or len(set(systems)) != len(systems) or set(systems) - SYSTEMS:
        raise ValueError('Invalid or repeated benchmark systems')
    systems = tuple(system for system in ('baseline', 'rag_only', 'ignis') if system in systems)
    if provider == 'extractive' and tuple(systems) != ('ignis',):
        raise ValueError('Offline extractive preview supports IGNIS only, never a fake model baseline')
    if type(fresh) is not bool or type(diagnostics) is not bool or (max_jobs is not None and (type(max_jobs) is not int or max_jobs < 1)):
        raise ValueError('Invalid fresh flag or job budget')
    questions = _questions(root, split, question_ids, limit)
    named_manifest = root / 'data/benchmark_sources.json'
    named_manifest_hash = hashlib.sha256(named_manifest.read_bytes()).hexdigest() if named_manifest.is_file() else None
    chunks = load_chunks(root) + load_scope_chunks(root) + load_named_chunks(root)
    conditions = load_condition_records(root)
    audit = audit_benchmark(root, questions=questions)
    current_named_hash = hashlib.sha256(named_manifest.read_bytes()).hexdigest() if named_manifest.is_file() else None
    if current_named_hash != named_manifest_hash:
        raise ValueError('Named source manifest changed during benchmark preparation')
    if audit['corpus_fingerprint'] != hashlib.sha256(json.dumps(sorted((c['chunk_id'], c['sha256']) for c in chunks)).encode()).hexdigest():
        raise ValueError('Corpus changed during benchmark preparation')
    scopes = {row['question_id']: row for row in audit['questions']}
    model_options = {'use_cache':not fresh}
    if diagnostics and provider in ('groq','openrouter'):
        model_options['diagnostics_dir'] = root / 'runs/model_diagnostics'
    first_model = make_model(root, provider, model, **model_options)
    name = first_model.name if first_model else None
    inputs = {
        'provider': provider, 'model': name, 'systems': list(systems), 'split': split, 'fresh': fresh,
        'rejected_response_diagnostics': diagnostics,
        'questions': questions, 'scope_plan': audit['questions'], 'condition_sha256': _hash(conditions),
        'corpus_sha256': _hash(chunks), 'benchmark_sha256': hashlib.sha256((root / 'benchmarks/questions.jsonl').read_bytes()).hexdigest(),
        'source_definitions_sha256': hashlib.sha256((root / 'benchmarks/sources.json').read_bytes()).hexdigest(),
        'named_source_manifest_sha256': named_manifest_hash,
        'source_scope_policy': {'allowed_chunk_ids_only': True, 'include_source_descriptions': True,
                                'finite_named_context_on_lexical_miss': True,
                                'context_max_passages': 6, 'context_max_characters': 12000,
                                'context_relevance': 'not_established_by_source_scope',
                                'catalog_role': 'source_description',
                                'catalog_use': 'Describe the named catalog sections. Measurement claims require experimental evidence.'},
        'code_sha256': _code_hashes(), 'temperature': 0, 'max_output_tokens': 1500,
        'model_snapshot': None, 'prompt_version': 'research-v5-scoped-context',
        'provider_retry_policy': getattr(first_model, 'retry_policy', None),
    }
    fingerprint = _hash(inputs)
    jobs = [{'question_id': question['question_id'], 'system': system, 'split': question['split'],
             'block_reason': None if scopes[question['question_id']].get('all_reference_scopes_available') and scopes[question['question_id']].get('allowed_chunk_ids') else 'named_scope_unavailable'}
            for question in questions for system in systems]
    identifier = resume or uuid4().hex
    directory = _directory(root, identifier)
    directory.mkdir(parents=True, exist_ok=True)
    with review_write_lock(directory):
        if resume:
            manifest = _read(directory / 'manifest.json')
            if (manifest.get('run_id') != resume or manifest.get('input_fingerprint') != fingerprint or
                    _hash(manifest.get('inputs')) != fingerprint or manifest.get('jobs') != jobs):
                raise ValueError('Resume refused: questions, source scope, corpus, code or model settings changed')
            if (_hash(_read(directory / 'corpus_snapshot.json')) != inputs['corpus_sha256'] or
                    _hash(_read(directory / 'conditions_snapshot.json')) != inputs['condition_sha256']):
                raise ValueError('Saved benchmark snapshot integrity check failed')
        else:
            manifest = {'schema_version': '1.0', 'run_id': identifier, 'created_at': _now(), 'status': 'running',
                        'evaluation_kind': 'offline_extractive_engineering' if provider == 'extractive' else 'exploratory_model_generation',
                        'annotation_status': 'unreviewed_no_scientific_scores', 'is_scientific_validation': False,
                        'input_fingerprint': fingerprint, 'inputs': inputs, 'git': _git(root),
                        'source_readiness': audit['counts'], 'jobs': jobs,
                        'ablation': 'RAG and IGNIS share the saved RAG draft when both systems are selected.',
                        'limitations': ['All benchmark labels remain provisional.', 'The public test split was visible during development.',
                                        'Requested model ID is not an immutable provider snapshot.',
                                        'Unavailable named sources stay pending; no substitute paper is used.']}
            _write(directory / 'manifest.json', manifest)
            _write(directory / 'corpus_snapshot.json', chunks)
            _write(directory / 'conditions_snapshot.json', conditions)
            for filename in inputs['code_sha256']:
                code = Path(__file__).with_name(filename).read_bytes()
                if hashlib.sha256(code).hexdigest() != inputs['code_sha256'][filename]:
                    raise ValueError('Code changed during benchmark preparation')
                destination = directory / 'code_snapshot' / filename
                destination.parent.mkdir(exist_ok=True)
                if destination.is_symlink():
                    raise ValueError('Redirected code snapshot')
                destination.write_bytes(code)
        report = _checkpoint(directory, manifest)
        completed = {(record['question_id'], record['system']): record for record in _records(directory, manifest)}
        count = 0
        try:
            for question in questions:
                scope = scopes[question['question_id']]
                allowed = set(scope.get('allowed_chunk_ids', []))
                if not allowed or not scope.get('all_reference_scopes_available'):
                    continue
                selected = [chunk for chunk in chunks if chunk['chunk_id'] in allowed]
                scope_text = _source_scope(question, scope.get('references', []))
                for system in systems:
                    key = question['question_id'], system
                    if key in completed:
                        continue
                    if max_jobs is not None and count >= max_jobs:
                        manifest['status'] = 'budget_reached'
                        return _checkpoint(directory, manifest)
                    current_model = make_model(root, provider, name, **model_options) if first_model else None
                    if current_model and current_model.name != name:
                        raise ValueError('Provider resolved a different model ID')
                    draft = None
                    if system == 'ignis' and 'rag_only' in systems:
                        previous = completed.get((question['question_id'], 'rag_only'))
                        if not previous or previous['prediction'].get('execution_error'):
                            continue
                        draft = deepcopy(previous['run'].get('raw_draft'))
                        if draft is None:
                            raise ValueError('RAG draft is unavailable for the critic ablation')
                    started = perf_counter()
                    try:
                        result = run(question['question'], selected if system != 'baseline' else [],
                                     model=current_model, system=system, include_overviews=True, include_source_descriptions=True,
                                     condition_records=conditions if system != 'baseline' else [],
                                     source_scope=scope_text, draft=draft, explicit_context_ids=sorted(allowed))
                    except Exception as exc:
                        result = {'run_id': uuid4().hex, 'answer': '', 'abstained': True, 'claims': [],
                                  'model_calls': list(getattr(current_model, 'calls', [])),
                                  'latency_ms': round((perf_counter()-started)*1000, 2),
                                  'error': f'Execution failed ({type(exc).__name__}).'}
                    prediction = _prediction(question, system, result, scope.get('readiness'))
                    if system == 'ignis' and 'rag_only' in systems:
                        prediction['shared_draft_from_run_id'] = previous['run'].get('run_id')
                        prediction['measurement_scope'] = 'incremental_critic_with_shared_rag_draft'
                    else:
                        prediction['measurement_scope'] = 'whole_workflow'
                    record = {'input_fingerprint': fingerprint, 'question_id': key[0], 'system': key[1],
                              'generation_scope': scope_text, 'run': result, 'prediction': prediction,
                              'shared_draft_from_run_id': previous['run'].get('run_id') if system == 'ignis' and 'rag_only' in systems else None}
                    record['record_sha256'] = _hash(record)
                    _write(directory / 'jobs' / (key[0] + '--' + key[1] + '.json'), record)
                    completed[key] = record
                    count += 1
                    report = _checkpoint(directory, manifest)
                    if progress:
                        progress({'run_id': identifier, 'question_id': key[0], 'system': system,
                                  'error': prediction.get('execution_error'), 'progress': manifest['progress']})
                    if prediction.get('execution_error'):
                        manifest['status'] = 'stopped_after_execution_error'
                        return _checkpoint(directory, manifest)
            if report['progress']['overall']['failed']:
                manifest['status'] = 'completed_with_errors' if len(completed) == len(manifest['jobs']) else 'pending_after_execution_error'
            elif len(completed) == len(manifest['jobs']):
                manifest['status'] = 'complete'
            else:
                manifest['status'] = 'pending_source_scope' if report['progress']['overall']['blocked_scope'] else 'pending_dependency'
            return _checkpoint(directory, manifest)
        except (KeyboardInterrupt, Exception):
            manifest['status'] = 'interrupted'
            _checkpoint(directory, manifest)
            raise


def get_benchmark(root, run_id):
    directory = _directory(root, run_id)
    manifest = _read(directory / 'manifest.json')
    if not isinstance(manifest, dict) or manifest.get('run_id') != run_id:
        raise ValueError('Benchmark ID does not match its file')
    report = _read(directory / 'report.json')
    if not isinstance(report, dict):
        raise ValueError('Malformed benchmark report')
    return {'manifest': manifest, 'report': report}


def benchmark_answers(root, run_id):
    saved = get_benchmark(root, run_id)
    return [{'question_id': record['question_id'], 'system': record['system'],
             'prediction': record['prediction'], 'run': record['run']}
            for record in _records(_directory(root, run_id), saved['manifest'])]


def latest_benchmark(root):
    base = _directory(root, 'valid').parent
    rows = []
    for folder in base.iterdir() if base.exists() else []:
        if not folder.is_dir():
            continue
        try:
            value = get_benchmark(root, folder.name)
            rows.append(value)
        except (OSError, ValueError):
            continue
    return max(rows, key=lambda value: value['manifest'].get('updated_at', ''), default=None)


def prepare_review_packet(root, run_id):
    """Remove system/verdict labels; preserve a private key and answer digests."""
    import secrets
    directory = _directory(root, run_id)
    with review_write_lock(directory):
        manifest = _read(directory / 'manifest.json')
        records = _records(directory, manifest)
        questions = {row['question_id']: row for row in manifest['inputs']['questions']}
        items, keys = [], []
        for record in records:
            prediction = record['prediction']
            if prediction.get('execution_error'):
                continue
            item_id = uuid4().hex
            items.append({'item_id': item_id, 'question': questions[record['question_id']]['question'],
                          'source_scope': record['generation_scope'], 'answer': prediction['answer'],
                          'abstained': prediction['abstained'], 'claims': [
                              {'text': claim['text'], 'citations': [
                                  {key: cite[key] for key in ('source_id', 'chunk_id', 'quote', 'url', 'locator') if key in cite}
                                  for cite in claim['citations']]} for claim in prediction['claims']],
                          'grading': None})
            keys.append({'item_id': item_id, 'question_id': record['question_id'], 'system': record['system'],
                         'prediction_sha256': _hash(prediction)})
        secrets.SystemRandom().shuffle(items)
        packet = {'benchmark_run_id': run_id, 'items': items, 'status': 'awaiting_independent_review',
                  'instructions': 'Audit every substantive answer assertion and split compound claims before grading. '
                                  'Record reviewer qualifications and uncertainty; do not copy model verdicts. '
                                  'Missing grading is not a passing score. Text style and citation structure may reveal the system.'}
        _write(directory / 'review_packet.json', packet)
        _write(directory / 'review_key.private.json', {'benchmark_run_id': run_id, 'keys': keys})
        return {'benchmark_run_id': run_id, 'items': len(items), 'packet': str(directory / 'review_packet.json'),
                'private_key': str(directory / 'review_key.private.json'), 'grades_created': 0}
