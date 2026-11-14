"""Question-only diagnostics over a verified, frozen benchmark source boundary.

Below-threshold passages are diagnostic leads, never approved generation context
or scientific support. No expected answer, rubric, category or model verdict is
used. The audit reads snapshots and does not change sources, runs or thresholds.
"""
import hashlib
import json
from pathlib import Path
import unicodedata

from . import retrieval
from .benchmark_run import _directory, _hash, _read


DEFAULT_RUN = '3c3cc0f1e4b949a8a33296e94417f13c'
MIN_QUERY_COVERAGE = 0.25
MAX_CONTEXT_CHARS = 12000
CONTEXT_FIELDS = ('source_id', 'chunk_id', 'text', 'conditions', 'locator',
                  'source_kind', 'experiment', 'evidence_tier', 'evidence_role')


def _span(chunk, query_terms):
    """Keep field matches distinguishable; current ranking ignores locators."""
    body = set(retrieval.tokens(chunk['text']))
    title = set(retrieval.tokens(' '.join(str(chunk.get(field, '')) for field in
                                        ('title', 'experiment', 'source_id'))))
    locator = set(retrieval.tokens(' '.join(str(chunk.get(field, '')) for field in
                                          ('locator', 'section', 'section_title'))))
    normalized_body = set(retrieval.tokens(unicodedata.normalize('NFKC', chunk['text'])))
    return dict(source_id=chunk['source_id'], chunk_id=chunk['chunk_id'],
                locator=chunk.get('locator'), section=chunk.get('section'),
                source_kind=chunk.get('source_kind'), evidence_role=chunk.get('evidence_role'),
                quote=chunk['text'], quote_sha256=chunk['sha256'],
                body_matched_terms=sorted(query_terms & body),
                title_identity_matched_terms=sorted(query_terms & title),
                locator_matched_terms=sorted(query_terms & locator),
                nfkc_body_matched_terms=sorted(query_terms & normalized_body),
                status='diagnostic_only', scientific_support=None)


def audit_retrieval(root, run_id=DEFAULT_RUN, *, candidate_limit=3):
    """Diagnose lexical misses without reading draft grading fields into search.

    The source pool is exactly each frozen allowed_chunk_ids list. Missing or
    inconsistent source scope never falls back to the global corpus. A second
    search at zero coverage merely exposes positive lexical matches that the
    production threshold rejected. It is not a suggested threshold change.
    """
    if type(candidate_limit) is not int or not 1 <= candidate_limit <= 10:
        raise ValueError('Diagnostic candidate limit must be from one to ten')
    directory = _directory(root, run_id)
    manifest = _read(directory / 'manifest.json')
    if not isinstance(manifest, dict) or manifest.get('run_id') != run_id:
        raise ValueError('Retrieval audit benchmark identity mismatch')
    inputs = manifest.get('inputs')
    if not isinstance(inputs, dict) or _hash(inputs) != manifest.get('input_fingerprint'):
        raise ValueError('Retrieval audit frozen input fingerprint mismatch')
    corpus = _read(directory / 'corpus_snapshot.json')
    if not isinstance(corpus, list) or _hash(corpus) != inputs.get('corpus_sha256'):
        raise ValueError('Retrieval audit frozen corpus mismatch')
    by_id = {}
    for chunk in corpus:
        if (not isinstance(chunk, dict) or not isinstance(chunk.get('chunk_id'), str)
                or chunk['chunk_id'] in by_id or not isinstance(chunk.get('source_id'), str)
                or not isinstance(chunk.get('text'), str)
                or hashlib.sha256(chunk['text'].encode()).hexdigest() != chunk.get('sha256')):
            raise ValueError('Invalid or duplicate frozen audit passage')
        by_id[chunk['chunk_id']] = chunk
    questions, scopes = inputs.get('questions'), inputs.get('scope_plan')
    if not isinstance(questions, list) or not isinstance(scopes, list):
        raise ValueError('Frozen audit questions and source scopes must be lists')
    plans = {}
    for scope in scopes:
        if (not isinstance(scope, dict) or not isinstance(scope.get('question_id'), str)
                or scope['question_id'] in plans):
            raise ValueError('Invalid or duplicate frozen source scope')
        allowed = scope.get('allowed_chunk_ids')
        if (not isinstance(allowed, list) or any(not isinstance(value, str) for value in allowed)
                or len(set(allowed)) != len(allowed) or set(allowed) - by_id.keys()):
            raise ValueError('Invalid frozen source passage boundary')
        plans[scope['question_id']] = scope
    rows, seen = [], set()
    for question in questions:
        if (not isinstance(question, dict) or not isinstance(question.get('question_id'), str)
                or not isinstance(question.get('question'), str) or not question['question'].strip()
                or question['question_id'] in seen):
            raise ValueError('Invalid or duplicate frozen audit question')
        identifier, text = question['question_id'], question['question']
        seen.add(identifier)
        plan = plans.get(identifier)
        if plan is None:
            raise ValueError('Question has no frozen source boundary')
        complete = plan.get('all_reference_scopes_available') is True
        allowed_pool = [by_id[value] for value in plan['allowed_chunk_ids']] if complete else []
        pool = [chunk for chunk in allowed_pool if retrieval.eligible(
            chunk, None, None, True, include_source_descriptions=True)]
        excluded_ids = sorted(chunk['chunk_id'] for chunk in allowed_pool if chunk not in pool)
        terms = set(retrieval.tokens(text))
        options = dict(limit=candidate_limit, include_overviews=True,
                       include_source_descriptions=True)
        hits = retrieval.search(text, pool, min_query_coverage=MIN_QUERY_COVERAGE, **options)
        diagnostic = retrieval.search(text, pool, min_query_coverage=0, **options)
        hit_ids = {hit['chunk_id'] for hit in hits}
        below = []
        for hit in diagnostic:
            if hit['chunk_id'] not in hit_ids:
                below.append(dict(_span(hit, terms), score=hit['score'],
                                  query_term_coverage=hit['ranking']['query_term_coverage'],
                                  matched_terms=hit['ranking']['matched_terms']))
        descriptors = [_span(chunk, terms) for chunk in pool]
        matched = set().union(*(set(row['body_matched_terms']) | set(row['title_identity_matched_terms'])
                                for row in descriptors)) if descriptors else set()
        context = [dict({field: chunk[field] for field in CONTEXT_FIELDS if field in chunk},
                        selection_role='explicit_source_scope') for chunk in pool]
        serialized_chars = len(json.dumps(context, ensure_ascii=False))
        references = plan.get('references', [])
        named_boundary = bool(references) and all(isinstance(ref, dict) and ref.get('mapped_source_ids')
                                                   for ref in references)
        # This is a bounded-context feasibility observation, not an admission gate.
        context_fits = bool(complete and named_boundary and pool and not excluded_ids and len(pool) <= 6
                            and serialized_chars <= MAX_CONTEXT_CHARS)
        status = ('source_scope_unavailable' if not complete or not pool else
                  'has_default_candidates' if hits else
                  'below_lexical_threshold' if diagnostic else 'zero_lexical_overlap')
        warnings = list(plan.get('warnings', []))
        if excluded_ids:
            warnings.append('The frozen allowed scope contains excluded passages; do not substitute a partial or global context.')
        if pool and not hits:
            warnings.append('Retrieval miss is not proof of scientific insufficiency or lack of relevant context.')
        if context_fits:
            warnings.append('The full explicitly named scope fits the context budget; scope coverage is distinct from lexical relevance.')
        rows.append(dict(question_id=identifier, question=text, query_tokens=sorted(terms),
                         status=status, source_scope_available=complete,
                         allowed_passage_ids=list(plan['allowed_chunk_ids']),
                         allowed_passage_count=len(allowed_pool), eligible_passage_count=len(pool),
                         excluded_passage_ids=excluded_ids,
                         allowed_text_characters=sum(len(chunk['text']) for chunk in pool),
                         context_serialized_characters=serialized_chars,
                         finite_named_scope_fits_context=context_fits,
                         default_candidate_ids=[hit['chunk_id'] for hit in hits],
                         diagnostic_below_threshold=below, scoped_passage_diagnostics=descriptors,
                         unmatched_query_terms=sorted(terms - matched), warnings=warnings,
                         scientific_support=None, generation_policy_changed=False))
    if _hash(_read(directory / 'manifest.json')) != _hash(manifest):
        raise ValueError('Benchmark manifest changed during retrieval audit')
    current_hash = hashlib.sha256(Path(retrieval.__file__).read_bytes()).hexdigest()
    frozen_hash = inputs.get('code_sha256', {}).get('retrieval.py')
    return dict(schema_version='retrieval-diagnostics-v1', benchmark_run_id=run_id,
                corpus_sha256=inputs['corpus_sha256'], input_fingerprint=manifest['input_fingerprint'],
                current_retrieval_code_sha256=current_hash, frozen_retrieval_code_sha256=frozen_hash,
                retrieval_code_matches_frozen=current_hash == frozen_hash,
                minimum_query_coverage=MIN_QUERY_COVERAGE, candidate_limit=candidate_limit,
                question_count=len(rows), default_candidate_cases=sum(bool(row['default_candidate_ids']) for row in rows),
                source_unavailable_cases=sum(row['status'] == 'source_scope_unavailable' for row in rows),
                retrieval_miss_cases=sum(row['source_scope_available'] and not row['default_candidate_ids'] for row in rows),
                missed_cases_with_finite_named_context=[row['question_id'] for row in rows
                                                      if not row['default_candidate_ids'] and row['finite_named_scope_fits_context']],
                questions=rows, scientific_grades_created=0,
                notices=['Read-only diagnostic: no answers, grades, source changes or threshold changes.',
                         'Search inputs are question text and the frozen allowed passages only; draft labels and rubrics are not used.',
                         'Below-threshold passages and full-scope feasibility are diagnostic leads, not approved generation context.',
                         'Catalog objectives, licenses and file names do not establish experimental measurements.'])
