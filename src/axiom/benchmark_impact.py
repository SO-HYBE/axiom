"""Read-only observed critic effects; never convert model checks into grades.

The primary claim comparison uses what RAG actually released, not all raw draft
claims: a writer-abstained draft may contain assertions that neither workflow
released. All effect denominators exclude failed/pending or unpaired executions.
"""
from collections import Counter

from .benchmark_inspect import inspect_benchmark
from .benchmark_report import summarize_benchmark
from .benchmark_run import _directory, _hash, _read, _records
from .review import review_read_lock


SYSTEM_ORDER = ('baseline', 'rag_only', 'ignis')
REASONS = (
    ('citation', 'Citation or quotation check'),
    ('semantic', 'Support or source-scope unresolved'),
    ('applicability', 'Applicability not established'),
    ('conditions', 'Experimental conditions incomplete'),
    ('numeric', 'Numeric value or unit check'),
    ('review_process', 'Review limit or unavailable check'),
    ('answer_policy', 'Answer-level withholding'),
    ('other', 'Other recorded check'),
)


def _rate(numerator, denominator):
    return dict(numerator=numerator, denominator=denominator,
                value=numerator / denominator if denominator else None)


def _failed(record):
    return bool(record['prediction'].get('execution_error') or record['prediction'].get('error')
                or record['run'].get('error'))


def _reason_ids(issues):
    result = set()
    for issue in issues:
        if issue in ('missing_citation', 'invalid_citation_or_quote'):
            result.add('citation')
        elif issue.startswith('numeric_'):
            result.add('numeric')
        elif issue == 'target_conditions_incomplete' or issue.startswith('condition_unknown:'):
            result.add('conditions')
        elif (issue.startswith('condition_mismatch:') or issue in (
                'universal_safety_claim_unresolved', 'operational_inference_requires_expert_review')):
            result.add('applicability')
        elif issue in ('semantic_support_unresolved', 'semantic_support_rejected', 'counterevidence_found',
                       'conflicting_or_limiting_evidence', 'overview_scope_unresolved'):
            result.add('semantic')
        elif issue in ('review_budget_exhausted', 'review_unavailable', 'model_review_unavailable'):
            result.add('review_process')
        else:
            result.add('other')
    return sorted(result)


def _claim_accounting(rag, ignis):
    """Align by raw index and exact checked-claim multiset, including duplicates."""
    raw = rag['run'].get('raw_draft')
    if not isinstance(raw, dict) or not isinstance(raw.get('claims'), list):
        return None, 'raw_draft_unavailable'
    if (raw != ignis['run'].get('raw_draft')
            or rag['run'].get('evidence', []) != ignis['run'].get('evidence', [])
            or ignis.get('shared_draft_from_run_id') != rag['run'].get('run_id')
            or ignis['prediction'].get('shared_draft_from_run_id') != rag['run'].get('run_id')):
        raise ValueError('Critic effect requires the same saved draft and evidence')
    drafted = raw['claims']
    checks = ignis['run'].get('draft_checks')
    if (not isinstance(checks, list) or len(checks) != len(drafted)
            or any(not isinstance(claim, dict) or not isinstance(check, dict)
                   or claim.get('text') != check.get('text') for claim, check in zip(drafted, checks))):
        return None, 'claim_checks_unavailable'
    rag_claims = rag['prediction']['claims']
    ignis_claims = ignis['prediction']['claims']
    # RAG exposes the writer draft without a critic. Preserve writer abstention.
    expected_rag = [] if rag['prediction']['abstained'] else [dict(claim, verdict='unfiltered') for claim in drafted]
    if rag_claims != expected_rag:
        raise ValueError('RAG released claims do not match the shared writer draft')
    if len(ignis_claims) > len(rag_claims):
        raise ValueError('Critic output is not a subset of the released RAG draft')
    remaining = Counter(_hash(claim) for claim in ignis_claims)
    included, withheld = [], []
    for index, check in enumerate(checks):
        digest = _hash(check)
        if remaining[digest]:
            if check.get('verdict') not in ('quoted_evidence', 'model_supported_needs_review'):
                raise ValueError('A withheld check appears in the released critic output')
            remaining[digest] -= 1
            included.append(index)
        else:
            withheld.append(index)
    if any(remaining.values()):
        raise ValueError('Released critic claim cannot be aligned with its saved check')
    if raw.get('abstained') and ignis_claims:
        raise ValueError('Critic output overrides writer abstention')
    # Only claims actually released by RAG are eligible for incremental effects.
    incremental = withheld if rag_claims else []
    reasons = Counter()
    issues = Counter()
    for index in incremental:
        recorded = checks[index].get('issues', [])
        if not isinstance(recorded, list) or any(not isinstance(issue, str) for issue in recorded):
            raise ValueError('Invalid recorded critic issues')
        categories = _reason_ids(recorded)
        if not categories:
            categories = ['answer_policy']
        reasons.update(categories)
        issues.update(set(recorded))
    return dict(raw_draft_claims=len(drafted), writer_withheld_claims=len(drafted)-len(rag_claims),
                rag_output_claims=len(rag_claims), ignis_output_claims=len(ignis_claims),
                additional_withheld_claims=len(incremental), reasons=reasons, issues=issues), None


def _job_summary(record, job):
    if record is None:
        return dict(status='pending', answered=None, abstained=None, claims=None, raw_draft_claims=None,
                    error=None, block_reason=job.get('block_reason'))
    failed = _failed(record)
    raw = record['run'].get('raw_draft')
    return dict(status='failed' if failed else 'completed',
                answered=None if failed else not record['prediction']['abstained'],
                abstained=None if failed else record['prediction']['abstained'],
                claims=None if failed else len(record['prediction']['claims']),
                raw_draft_claims=len(raw['claims']) if isinstance(raw, dict) and isinstance(raw.get('claims'), list) else None,
                error=(record['prediction'].get('execution_error') or record['prediction'].get('error')
                       or record['run'].get('error')) if failed else None, block_reason=job.get('block_reason'))


def summarize_impact(root, run_id, *, allow_integrity_warnings=False):
    """Inspect authoritative snapshots and summarize observed behavior, offline.

    No annotation imports, independent grades, model calls, network requests or
    persisted summaries are created. A changed/inconsistent snapshot fails closed.
    """
    audit = inspect_benchmark(root, run_id)
    if not audit['audit_passed'] and not allow_integrity_warnings:
        raise ValueError('Evaluation visualization requires a verified benchmark')
    directory = _directory(root, run_id)
    with review_read_lock(directory):
        manifest = _read(directory / 'manifest.json')
        if (manifest.get('input_fingerprint') != audit['input_fingerprint']
                or _hash(manifest.get('inputs')) != audit.get('observed_input_hash')):
            raise ValueError('Benchmark changed during impact inspection; retry')
        records = _records(directory, manifest)
        report = summarize_benchmark(manifest, [record['prediction'] for record in records])
        if report['progress'] != audit['progress']:
            raise ValueError('Benchmark progress changed during impact inspection; retry')
        result = _summarize(manifest, records, audit)
        if not audit['audit_passed']:
            # Charts may help inspect saved observations, but must never present
            # them as verified when the frozen inputs or code snapshot disagree.
            result['integrity_verified'] = False
            result['integrity_warnings'] = audit['issues']
        return result


def _summarize(manifest, records, audit):
    jobs = {(job['question_id'], job['system']): job for job in manifest['jobs']}
    saved = {(record['question_id'], record['system']): record for record in records}
    systems = []
    events = Counter()
    cache_hits = fresh_successes = unknown_calls = 0
    for system in SYSTEM_ORDER:
        scheduled = [key for key in jobs if key[1] == system]
        if not scheduled:
            continue
        complete = [saved[key] for key in scheduled if key in saved and not _failed(saved[key])]
        failures = sum(key in saved and _failed(saved[key]) for key in scheduled)
        answered = sum(not record['prediction']['abstained'] for record in complete)
        systems.append(dict(system=system, scheduled=len(scheduled), completed=len(complete), failed=failures,
                            pending=len(scheduled)-len(complete)-failures, answered=answered,
                            abstained=len(complete)-answered, released_claims=sum(len(record['prediction']['claims']) for record in complete),
                            answer_rate=_rate(answered,len(complete))))
    for record in records:
        calls = record['run'].get('model_calls')
        if calls is None:
            unknown_calls += 1
        for call in calls or []:
            events[call.get('status','unspecified')] += 1
            hit = call.get('cache_hit') is True or call.get('status') == 'cache_hit'
            cache_hits += hit
            fresh_successes += call.get('status') == 'success' and not hit
    totals = Counter()
    categories = {identifier:dict(id=identifier,label=label,claims=0,question_ids=[]) for identifier,label in REASONS}
    transitions = {(source,target):dict(source=source,target=target,count=0,question_ids=[])
                   for source in ('answered','abstained') for target in ('answered','abstained')}
    question_rows, matched, exclusions = [], [], []
    scopes = {row['question_id']:row for row in manifest['inputs'].get('scope_plan',[])}
    for question in manifest['inputs']['questions']:
        qid = question['question_id']
        selected = {system:_job_summary(saved.get((qid,system)),jobs[qid,system])
                    for system in SYSTEM_ORDER if (qid,system) in jobs}
        rag, ignis = saved.get((qid,'rag_only')), saved.get((qid,'ignis'))
        row = dict(question_id=qid,question=question['question'],split=question['split'],systems=selected,
                   scope_status='available' if scopes.get(qid,{}).get('all_reference_scopes_available') else 'unavailable',
                   evidence_selection=(ignis or rag or {}).get('run',{}).get('evidence_selection',{}).get('mode'),
                   pair_status='not_scheduled',pair_exclusion=None,critic_reasons=[],
                   rag_output_claims=None,ignis_output_claims=None,additional_withheld_claims=None)
        if (qid,'rag_only') in jobs and (qid,'ignis') in jobs:
            reason = None
            if rag is None or ignis is None:
                reason='pair_pending'
            elif _failed(rag) or _failed(ignis):
                reason='execution_failed'
            accounting = None
            if reason is None:
                accounting,reason=_claim_accounting(rag,ignis)
            if reason:
                row.update(pair_status='excluded',pair_exclusion=reason)
                exclusions.append(dict(question_id=qid,reason=reason))
            else:
                matched.append(qid)
                row['pair_status']='matched'
                for field in ('raw_draft_claims','writer_withheld_claims','rag_output_claims','ignis_output_claims','additional_withheld_claims'):
                    totals[field] += accounting[field]
                    row[field]=accounting[field]
                row['critic_reasons']=sorted(accounting['reasons'])
                for identifier,count in accounting['reasons'].items():
                    categories[identifier]['claims'] += count
                    categories[identifier]['question_ids'].append(qid)
                source='abstained' if rag['prediction']['abstained'] else 'answered'
                target='abstained' if ignis['prediction']['abstained'] else 'answered'
                transitions[source,target]['count'] += 1
                transitions[source,target]['question_ids'].append(qid)
        question_rows.append(row)
    critic=dict(available=bool(matched),matched_pairs=len(matched),scheduled_pairs=len(matched)+len(exclusions),
                excluded_pairs=len(exclusions),pair_question_ids=matched,exclusions=exclusions,
                **{key:totals[key] for key in ('raw_draft_claims','writer_withheld_claims','rag_output_claims','ignis_output_claims','additional_withheld_claims')},
                additional_withheld_rate=_rate(totals['additional_withheld_claims'],totals['rag_output_claims']),
                answer_transitions=list(transitions.values()), reasons=list(categories.values()),
                reason_counting='Each additional withheld structured claim counts once per applicable category. Categories overlap; do not sum them.',
                claim_denominator='Structured claims actually released by RAG within matched successful shared-draft pairs. Writer-abstained raw claims are excluded.')
    # Compatibility names retain the same incremental RAG-output meaning.
    critic.update(draft_claims=critic['rag_output_claims'],released_claims=critic['ignis_output_claims'],
                  withheld_claims=critic['additional_withheld_claims'],withheld_rate=critic['additional_withheld_rate'])
    return dict(schema_version='benchmark-impact-v1',run_id=manifest['run_id'],
                input_fingerprint=manifest['input_fingerprint'],integrity_verified=True,
                progress={key:audit['progress']['overall'][key] for key in ('scheduled','completed','failed','pending')},
                systems=systems,critic=critic,questions=question_rows,
                provider=dict(statuses=dict(sorted(events.items())),cache_hits=cache_hits,fresh_successes=fresh_successes,
                              records_without_call_audit=unknown_calls),
                scientific_quality=dict(status='ungraded',independent_grades=0,annotations_loaded=False,
                    accuracy=None,citation_precision=None,unsafe_extrapolation=None,abstention_accuracy=None),
                notices=['Observed release and withholding behavior, not scientific errors prevented or safety improvement.',
                    'Critic effect uses only matched successful RAG/AXIOM pairs with identical saved drafts, evidence and linkage.',
                    'Primary claim denominator is RAG released-output claims; claims in writer-abstained drafts do not count as critic removals.',
                    'Reasons are recorded rule/model flags, not independently verified scientific errors; categories overlap.',
                    'Per-system totals use all completed executions for that system; they are separate from the matched-pair critic denominator.',
                    'Failed and pending executions do not count as answers or correct abstentions.',
                    'Independent scientific grades are not loaded. Accuracy, citation precision, unsafe extrapolation and abstention correctness remain unknown.',
                    'Cache hits, retries and an unversioned model alias prevent an unconfounded latency or cost comparison.'])
