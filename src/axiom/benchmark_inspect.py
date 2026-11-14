"""Inspect frozen benchmark engineering integrity without judging science.

Saved job digests and frozen snapshots are authoritative. Current source files,
current model configuration, model verdicts and draft benchmark labels never
become annotations. Inspection takes the shared read lock, so a read-only
deployment snapshot (a serverless bundle) can be inspected without a writable
lock file, and it never rewrites answers, manifests or reports. Hashes detect
corruption, not authorship.
"""
from collections import Counter
import hashlib
import math
import re

from .benchmark_report import summarize_benchmark
from .benchmark_run import MAX_BYTES, _directory, _hash, _read, _records
from .critic import normalized
from .review import review_read_lock


def _latency(prediction):
    value = prediction.get('latency_ms')
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def _failed(record):
    return bool(record['prediction'].get('execution_error') or record['prediction'].get('error'))


def _claims(run, field):
    value = run.get(field)
    if field == 'raw_draft':
        value = value.get('claims') if isinstance(value, dict) else None
    return value if isinstance(value, list) else []


def _code_digest(path):
    if path.is_symlink():
        raise ValueError('Redirected code snapshot')
    with path.open('rb') as handle:
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Code snapshot exceeds bounds')
    return hashlib.sha256(raw).hexdigest()


def inspect_benchmark(root, run_id):
    """Return observed counts and explicit integrity issues; never make API calls.

    Missing source jobs, provider failures and incomplete pairs are accounted for
    separately. They do not make an internally consistent record corrupt. A
    malformed or digest-invalid per-job record raises ValueError through the
    runner's bounded reader. Snapshot/protocol mismatches return audit_passed=False.
    """
    directory = _directory(root, run_id)
    with review_read_lock(directory):
        manifest = _read(directory / 'manifest.json')
        report = _read(directory / 'report.json')
        if not isinstance(manifest, dict) or manifest.get('run_id') != run_id:
            raise ValueError('Benchmark inspection identity mismatch')
        if not isinstance(report, dict) or not isinstance(manifest.get('inputs'), dict):
            raise ValueError('Malformed benchmark inspection inputs')
        inputs = manifest['inputs']
        issues = []

        def issue(code, question_id=None, system=None, **details):
            issues.append(dict(code=code, question_id=question_id, system=system, **details))

        if _hash(inputs) != manifest.get('input_fingerprint'):
            issue('input_fingerprint_mismatch')
        snapshots = {}
        for label, filename, hash_key in (
                ('corpus', 'corpus_snapshot.json', 'corpus_sha256'),
                ('conditions', 'conditions_snapshot.json', 'condition_sha256')):
            try:
                value = _read(directory / filename)
                snapshots[label] = value
                if _hash(value) != inputs.get(hash_key):
                    issue(label + '_snapshot_mismatch')
            except (OSError, ValueError):
                issue(label + '_snapshot_mismatch')
        code_hashes = inputs.get('code_sha256')
        if not isinstance(code_hashes, dict) or not code_hashes:
            issue('code_snapshot_mismatch')
        else:
            for name, expected in sorted(code_hashes.items()):
                if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*\.py', name):
                    issue('code_snapshot_path_invalid')
                    continue
                try:
                    if _code_digest(directory / 'code_snapshot' / name) != expected:
                        issue('code_snapshot_mismatch', filename=name)
                except (OSError, ValueError):
                    issue('code_snapshot_mismatch', filename=name)

        records = _records(directory, manifest)
        predictions = [record['prediction'] for record in records]
        recomputed = summarize_benchmark(manifest, predictions)
        if report.get('progress') != recomputed['progress'] or manifest.get('progress') != recomputed['progress']['overall']:
            issue('progress_mismatch')
        scopes = {}
        for row in inputs.get('scope_plan', []):
            if not isinstance(row, dict) or not isinstance(row.get('question_id'), str):
                raise ValueError('Invalid frozen benchmark scope plan')
            if row['question_id'] in scopes:
                raise ValueError('Duplicate frozen benchmark scope')
            scopes[row['question_id']] = set(row.get('allowed_chunk_ids', []))
        corpus = snapshots.get('corpus')
        by_chunk = {}
        if isinstance(corpus, list):
            for chunk in corpus:
                if not isinstance(chunk, dict) or not isinstance(chunk.get('chunk_id'), str):
                    issue('corpus_chunk_invalid')
                    continue
                identifier = chunk['chunk_id']
                if identifier in by_chunk:
                    issue('duplicate_corpus_chunk_id', chunk_id=identifier)
                by_chunk[identifier] = chunk
                if not isinstance(chunk.get('text'), str) or hashlib.sha256(chunk['text'].encode('utf-8')).hexdigest() != chunk.get('sha256'):
                    issue('corpus_chunk_digest_mismatch', chunk_id=identifier)
        else:
            issue('corpus_snapshot_invalid')

        by_system = {}
        status_totals = Counter()
        record_map = {}
        scheduled = {(job['question_id'], job['system']): job for job in manifest['jobs']}
        for record in records:
            qid, system = record['question_id'], record['system']
            record_map[qid, system] = record
            observed = by_system.setdefault(system, dict(
                records=0, completed=0, failed=0, abstentions=0,
                evidence_empty_completed=0, evidence_empty_question_ids=[],
                draft_claims=0, released_claims=0, withheld_claims=0 if system == 'ignis' else None,
                policy_withholding=0 if system == 'ignis' else None, critic_issues={}, provider_statuses={}, cache_hits=0,
                model_call_audit_missing_records=0,
                literal_citation_spans=dict(checked=0, present=0, missing=0, baseline_not_checked=0)))
            observed['records'] += 1
            run, prediction = record['run'], record['prediction']
            if scheduled[qid, system].get('block_reason') == 'named_scope_unavailable':
                issue('executed_blocked_source', qid, system)
            evidence = run.get('evidence', [])
            if not isinstance(evidence, list) or any(not isinstance(item, dict) for item in evidence):
                issue('evidence_invalid', qid, system)
                evidence = []
            if system == 'baseline' and evidence:
                issue('baseline_evidence_leak', qid, system)
            if system != 'baseline':
                allowed = scopes.get(qid)
                if allowed is None:
                    issue('scope_plan_missing', qid, system)
                    allowed = set()
                for chunk in evidence:
                    identifier = chunk.get('chunk_id')
                    if identifier not in allowed:
                        issue('evidence_outside_scope', qid, system, chunk_id=identifier)
                    frozen = by_chunk.get(identifier)
                    if frozen is None or any(chunk.get(key) != frozen.get(key) for key in ('source_id', 'text', 'sha256')):
                        issue('evidence_snapshot_mismatch', qid, system, chunk_id=identifier)
            calls = run.get('model_calls')
            if calls is None:
                observed['model_call_audit_missing_records'] += 1
                calls = []
            elif not isinstance(calls, list) or any(not isinstance(call, dict) for call in calls):
                issue('model_call_audit_invalid', qid, system)
                calls = []
            statuses = Counter(call.get('status') if isinstance(call.get('status'), str) else 'unspecified'
                               for call in calls if isinstance(call, dict))
            status_totals.update(statuses)
            previous_statuses = Counter(observed['provider_statuses'])
            previous_statuses.update(statuses)
            observed['provider_statuses'] = dict(sorted(previous_statuses.items()))
            observed['cache_hits'] += sum(call.get('cache_hit') is True or call.get('status') == 'cache_hit'
                                          for call in calls if isinstance(call, dict))
            if _failed(record):
                observed['failed'] += 1
                continue
            if run.get('system') != system:
                issue('run_system_mismatch', qid, system)
            model_info = run.get('model_info')
            expected_model = {key: inputs.get(key) for key in ('model', 'provider')}
            if inputs.get('provider') == 'extractive' and inputs.get('model') is None:
                # The declared extractive preview intentionally has no LLM.
                expected_model = {'model': None, 'provider': None}
                if run.get('mode') != 'extractive_preview':
                    issue('model_identity_mismatch', qid, system)
            if (not isinstance(model_info, dict)
                    or any(model_info.get(key) != expected_model[key] for key in ('model', 'provider'))):
                issue('model_identity_mismatch', qid, system)
            if any(prediction.get(key) != run.get(key) for key in ('answer', 'claims', 'abstained')):
                issue('prediction_run_mismatch', qid, system)
            observed['completed'] += 1
            observed['abstentions'] += prediction['abstained']
            if system != 'baseline' and not evidence:
                observed['evidence_empty_completed'] += 1
                observed['evidence_empty_question_ids'].append(qid)
            drafted = len(_claims(run, 'raw_draft'))
            released = len(prediction['claims'])
            observed['draft_claims'] += drafted
            observed['released_claims'] += released
            if system == 'ignis':
                observed['withheld_claims'] += max(drafted - released, 0)
                if released > drafted:
                    issue('released_claims_exceed_draft', qid, system)
                critic_issues = Counter(observed['critic_issues'])
                for check in run.get('draft_checks', []):
                    if isinstance(check, dict):
                        critic_issues.update(check.get('issues', []))
                observed['critic_issues'] = dict(sorted(critic_issues.items()))
            if system == 'ignis':
                observed['policy_withholding'] += prediction.get('policy_withholding') is True
            selected = {chunk.get('chunk_id'): chunk for chunk in evidence}
            for claim in prediction['claims']:
                for citation in claim['citations']:
                    counts = observed['literal_citation_spans']
                    if system == 'baseline':
                        counts['baseline_not_checked'] += 1
                        continue
                    counts['checked'] += 1
                    chunk = selected.get(citation['chunk_id'])
                    present = (chunk is not None and chunk.get('source_id') == citation['source_id']
                               and normalized(citation['quote']) in normalized(chunk.get('text', '')))
                    counts['present' if present else 'missing'] += 1
                    # Unfiltered RAG may generate an invalid quote. This is an
                    # output diagnostic, rather than corrupt experiment design.
                    if not present and system == 'ignis':
                        issue('released_citation_not_in_evidence', qid, system, chunk_id=citation['chunk_id'])

        paired_questions = sorted({job['question_id'] for job in manifest['jobs']
                                   if job['system'] in ('rag_only', 'ignis')})
        shared_design = 'rag_only' in inputs.get('systems', []) and 'ignis' in inputs.get('systems', [])
        pairs = []
        for qid in paired_questions:
            rag, ignis = record_map.get((qid, 'rag_only')), record_map.get((qid, 'ignis'))
            complete = bool(rag and ignis and not _failed(rag) and not _failed(ignis))
            pair = dict(question_id=qid, status='complete' if complete else 'incomplete',
                        rag_latency_ms=None, incremental_critic_latency_ms=None, whole_workflow_latency_ms=None,
                        cache_confounded=True)
            if complete:
                rag_ms, critic_ms = _latency(rag['prediction']), _latency(ignis['prediction'])
                pair.update(rag_latency_ms=rag_ms, incremental_critic_latency_ms=critic_ms,
                            whole_workflow_latency_ms=rag_ms + critic_ms if rag_ms is not None and critic_ms is not None else None,
                            rag_abstained=rag['prediction']['abstained'], ignis_abstained=ignis['prediction']['abstained'])
                if shared_design:
                    if rag['run'].get('raw_draft') != ignis['run'].get('raw_draft'):
                        issue('shared_draft_mismatch', qid, 'ignis')
                    if rag['run'].get('evidence', []) != ignis['run'].get('evidence', []):
                        issue('shared_evidence_mismatch', qid, 'ignis')
                    rag_id = rag['run'].get('run_id')
                    if (not rag_id or ignis.get('shared_draft_from_run_id') != rag_id
                            or ignis['prediction'].get('shared_draft_from_run_id') != rag_id):
                        issue('shared_draft_link_mismatch', qid, 'ignis')
            pairs.append(pair)
        for observed in by_system.values():
            observed['evidence_empty_question_ids'].sort()
        return dict(
            schema_version='benchmark-inspection-v1', benchmark_run_id=run_id,
            audit_passed=not issues, issues=issues, manifest_status=manifest.get('status'),
            input_fingerprint=manifest.get('input_fingerprint'), observed_input_hash=_hash(inputs),
            frozen_hashes={key: inputs.get(key) for key in ('corpus_sha256', 'condition_sha256',
                'benchmark_sha256', 'source_definitions_sha256', 'named_source_manifest_sha256', 'code_sha256')},
            progress=recomputed['progress'], by_system=dict(sorted(by_system.items())),
            provider_statuses=dict(sorted(status_totals.items())), pairs=pairs,
            complete_pairs=sum(pair['status'] == 'complete' for pair in pairs),
            independent_grades=0, scientific_quality=dict(status='ungraded', claim_support=None,
                citation_precision=None, unsafe_extrapolation=None, abstention_accuracy=None),
            notices=[
                'Engineering integrity only; no model verdict, AI draft label or abstention becomes a scientific grade.',
                'No independent annotation file is loaded by this inspection.',
                'Literal quotation presence checks provenance/text matching, not whether the claim follows scientifically.',
                'Baseline receives no corpus; its citations are not checked against unavailable retrieval evidence.',
                'Policy-withholding counts apply to AXIOM only; other systems may abstain without the critic policy.',
                'Whole AXIOM workflow latency adds the matched RAG draft and incremental critic; cache/retry effects confound comparisons.',
                'Missing-source jobs and incomplete or failed pairs remain explicit and are not corrupt records by themselves.'])
