"""Read-only benchmark provenance audit, never scientific grading or approval."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit, urlunsplit

from .research import load_chunks
from .benchmark_scope import load_scope_chunks
from .benchmark_named_sources import load_named_chunks, load_named_inventory
from .retrieval import EXCLUDED_KINDS, eligible, search

CANDIDATES_PER_QUESTION = 3


def _url(value):
    if not isinstance(value, str):
        return ''
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip('/'), parsed.query, ''))


def _count(rows, key):
    return dict(sorted(Counter(str(row.get(key, 'unspecified')) for row in rows).items()))


def _scope(reference, question):
    locator = reference.get('locator', '')
    locator = locator if isinstance(locator, str) else ''
    abstract_only = ('abstract' in question.lower() or 'abstract' in str(reference.get('kind', '')).lower()
                     or locator.strip().lower() == 'abstract')
    if abstract_only:
        return True, True, ['abstract']
    if not locator or re.fullmatch(r'(?:full (?:document|text)|entire document|article(?:,.*)?)', locator, re.I):
        return False, False, []
    selectors = [part.strip().casefold() for part in locator.split(';') if part.strip()]
    if 'objectives' in selectors and re.search(r'\bobjectives alone\b|\busing only the [\w-]+ catalog objectives\b', question, re.I):
        selectors = ['objectives']
    return True, False, selectors


def _in_scope(chunk, restricted, abstract_only, selectors):
    if not restricted:
        return True
    if chunk.get('named_scope_verified') is True:
        labels = {str(chunk.get(key, '')).strip().casefold() for key in ('section', 'section_title', 'locator')}
        return bool(labels.intersection(selectors))
    labels = ' '.join(str(chunk.get(key, '')) for key in ('locator', 'section', 'section_title')).lower()
    if abstract_only:
        return bool(re.search(r'\babstract\b', labels) or chunk.get('source_kind') == 'abstract')
    return any(selector in labels for selector in selectors)


def _reference(ref_id, reference, question, inventory, chunks, named_chunk_ids):
    url = _url(reference.get('url'))
    explicit = reference.get('source_ids', [])
    if isinstance(explicit, str):
        explicit = [explicit]
    if not isinstance(explicit, list):
        explicit = []
    if isinstance(reference.get('source_id'), str):
        explicit = explicit + [reference['source_id']]
    mapped = [source for source in inventory if source['source_id'] in explicit or
              (url and url in {_url(source.get(key)) for key in ('url', 'download_url', 'metadata_url')})]
    mapped_ids = sorted({source['source_id'] for source in mapped})
    present = [chunk for chunk in chunks if chunk['source_id'] in mapped_ids]
    catalog = ('catalog' in str(reference.get('kind', '')).lower()
               or any(source.get('source_kind') in EXCLUDED_KINDS for source in mapped))
    usable = [chunk for chunk in present if eligible(chunk, None, mapped_ids, True, include_source_descriptions=True)]
    warnings = []
    warnings.extend(source['reason'] for source in mapped
                    if source.get('status') == 'unavailable' and isinstance(source.get('reason'), str))
    if catalog:
        usable = [chunk for chunk in usable if chunk['chunk_id'] in named_chunk_ids
                  and chunk.get('evidence_role') == 'source_description'
                  and chunk.get('named_scope_verified') is True]
        warnings.append('Catalog sections describe the investigation and its files. Numerical measurements require experimental evidence.')
    restricted, abstract_only, selectors = _scope(reference, question)
    scoped = [chunk for chunk in usable if _in_scope(chunk, restricted, abstract_only, selectors)]
    missing_selectors = [selector for selector in selectors if not any(
        _in_scope(chunk, True, selector == 'abstract', [selector]) for chunk in usable)]
    if missing_selectors:
        scoped = []
    if catalog and not usable:
        status = 'catalog_not_measurement_corpus'
    elif not mapped:
        status = 'reference_not_in_inventory'
    elif not present:
        status = 'source_not_ingested'
    elif not usable:
        status = 'source_not_eligible'
    elif not scoped:
        status = 'reference_scope_not_ingested'
        warnings.append('The named source is present, but the requested section has no explicitly located chunks. Full-document passages do not satisfy this scope.')
    else:
        status = 'scope_available'
    if abstract_only and usable and not scoped:
        warnings.append('Abstract-only scope: PDF page chunks must not substitute for an absent abstract snapshot.')
    return {
        'reference_id': ref_id, 'url': reference.get('url'), 'requested_locator': reference.get('locator'),
        'effective_locator': '; '.join(selectors) if restricted else reference.get('locator'),
        'kind': reference.get('kind'), 'mapped_source_ids': mapped_ids,
        'inventory_statuses': {source['source_id']: source.get('status') for source in mapped},
        'ingested_source_ids': sorted({chunk['source_id'] for chunk in present}),
        'available': bool(scoped), 'scope_available': bool(scoped), 'scope_status': status,
        'restricted_scope': restricted, 'abstract_only': abstract_only,
        'missing_scope_locators': missing_selectors,
        'eligible_chunk_ids': sorted(chunk['chunk_id'] for chunk in scoped),
        'candidate_source_ids': sorted({chunk['source_id'] for chunk in usable}), 'warnings': warnings,
    }


def _review(question):
    qualified = question.get('qualified_review')
    documented = (isinstance(qualified, dict) and qualified.get('status') == 'completed'
                  and all(isinstance(qualified.get(key), str) and qualified[key].strip()
                          for key in ('reviewer', 'qualification', 'reviewed_at')))
    return {'annotation_status': question.get('annotation_status', 'unspecified'),
            'ai_draft': str(question.get('annotation_status', '')).startswith('ai_'),
            'human_reviewer_recorded': bool(question.get('human_reviewer')),
            'qualified_review_documented': bool(documented),
            'qualification_independently_verified': False,
            'notice': 'A reviewer name or AI draft label is not evidence of qualified scientific validation.'}


def audit_benchmark(root, questions=None):
    """Audit existing references; search uses question text only and changes no files.

    allowed_chunk_ids is the generation boundary. allowed_source_ids alone must
    not be used for section-restricted sources. Candidates outside that boundary
    are clearly marked related-document leads and cannot establish readiness.
    """
    root = Path(root)
    if questions is None:
        questions = [json.loads(line) for line in (root / 'benchmarks/questions.jsonl').read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    else:
        questions = list(questions)
    references = json.loads((root / 'benchmarks/sources.json').read_text(encoding='utf-8-sig'))
    inventory = {source['source_id']: source for source in
                 json.loads((root / 'data/sources.json').read_text(encoding='utf-8-sig')).get('sources', [])}
    inventory.update((source['source_id'], source) for source in load_named_inventory(root))
    named_chunks = load_named_chunks(root)
    named_chunk_ids = {chunk['chunk_id'] for chunk in named_chunks}
    chunks = load_chunks(root) + load_scope_chunks(root) + named_chunks
    if len({chunk['chunk_id'] for chunk in chunks}) != len(chunks):
        raise ValueError('Duplicate corpus/scope chunk identifier')
    rows, seen = [], set()
    for question in questions:
        identifier = question.get('question_id')
        if not isinstance(identifier, str) or not identifier or identifier in seen or not isinstance(question.get('question'), str):
            raise ValueError('Benchmark requires unique question IDs and question text')
        seen.add(identifier)
        mapped, warnings = [], []
        ref_ids = question.get('reference_ids', [])
        urls = question.get('reference_urls', [])
        if not isinstance(ref_ids, list) or not isinstance(urls, list):
            raise ValueError('Reference IDs and URLs must be lists')
        for ref_id in ref_ids:
            reference = references.get(ref_id)
            if not isinstance(reference, dict):
                warnings.append('Unknown benchmark reference: ' + str(ref_id))
                mapped.append({'reference_id': ref_id, 'scope_status': 'unknown_reference', 'available': False,
                               'scope_available': False, 'mapped_source_ids': [], 'ingested_source_ids': [],
                               'eligible_chunk_ids': [], 'candidate_source_ids': [], 'restricted_scope': True,
                               'abstract_only': False, 'warnings': []})
            else:
                mapped.append(_reference(ref_id, reference, question['question'], inventory.values(), chunks, named_chunk_ids))
        known_urls = {_url(references[ref_id].get('url')) for ref_id in ref_ids if isinstance(references.get(ref_id), dict)}
        for url in urls:
            if _url(url) not in known_urls:
                warnings.append('Question reference URL is not declared by its benchmark reference IDs: ' + str(url))
        consistent = all(_url(url) in known_urls for url in urls)
        allowed = sorted({identifier for ref in mapped for identifier in ref['eligible_chunk_ids']}) if consistent else []
        allowed_set = set(allowed)
        allowed_sources = sorted({chunk['source_id'] for chunk in chunks if chunk['chunk_id'] in allowed_set})
        candidate_sources = sorted({identifier for ref in mapped for identifier in ref['candidate_source_ids']})
        candidate_pool = [chunk for chunk in chunks if chunk['chunk_id'] in allowed_set] if allowed else chunks
        hits = search(question['question'], candidate_pool, limit=CANDIDATES_PER_QUESTION,
                      source_ids=candidate_sources, include_overviews=True, include_source_descriptions=True) if candidate_sources else []
        candidates = []
        for hit in hits:
            candidates.append({key: hit.get(key) for key in ('source_id', 'chunk_id', 'title', 'url', 'document_url', 'locator', 'sha256', 'source_kind', 'evidence_role')})
            candidates[-1].update(quote=hit['text'], quote_sha256=hashlib.sha256(hit['text'].encode()).hexdigest(),
                                  in_reference_scope=hit['chunk_id'] in allowed_set,
                                  status='unreviewed_candidate', score=hit['score'], ranking=hit['ranking'])
        all_available = bool(mapped) and all(ref['scope_available'] for ref in mapped) and consistent
        if not consistent or not mapped:
            readiness = 'reference_mapping_incomplete'
        elif not all_available:
            readiness = 'reference_scope_missing' if any(ref['scope_status'] == 'reference_scope_not_ingested' for ref in mapped) else 'reference_sources_missing'
        elif not any(candidate['in_reference_scope'] for candidate in candidates):
            readiness = 'no_matching_candidate'
        else:
            readiness = 'candidates_need_review'
        trap = (question.get('expected_abstained') is True or question.get('expected_action') == 'abstain'
                or question.get('category') in ('insufficient', 'trap', 'adversarial', 'uncertainty', 'applicability', 'extrapolation', 'citation_trap'))
        if trap:
            warnings.append('Abstention, applicability, uncertainty or trap cases cannot be scientifically scored from lexical matches.')
        rows.append({'question_id': identifier, 'question': question['question'], 'split': question.get('split'),
                     'category': question.get('category'), 'annotation_status': question.get('annotation_status', 'unspecified'),
                     'review': _review(question), 'readiness': readiness, 'references': mapped,
                     'allowed_source_ids': allowed_sources, 'allowed_chunk_ids': allowed,
                     'restricted_scope': any(ref['restricted_scope'] for ref in mapped),
                     'abstract_only': any(ref['abstract_only'] for ref in mapped),
                     'all_reference_scopes_available': all_available, 'candidates': candidates,
                     'abstention_or_trap': trap, 'requires_scientific_review': True, 'auto_scoring_ready': False,
                     'warnings': warnings + [warning for ref in mapped for warning in ref['warnings']]})
    counts = {key: _count(rows, key) for key in ('annotation_status', 'category', 'split', 'readiness')}
    counts.update(ai_draft_unreviewed=sum(row['annotation_status'] == 'ai_draft_unreviewed' for row in rows),
                  human_reviewer_recorded=sum(row['review']['human_reviewer_recorded'] for row in rows),
                  qualified_review_documented=sum(row['review']['qualified_review_documented'] for row in rows),
                  abstention_or_trap=sum(row['abstention_or_trap'] for row in rows),
                  source_scope_available=sum(row['all_reference_scopes_available'] for row in rows),
                  questions_with_candidates=sum(bool(row['candidates']) for row in rows),
                  auto_scoring_ready=0)
    return {'schema_version': 'benchmark-audit-v1', 'question_count': len(rows), 'counts': counts,
            'corpus_fingerprint': hashlib.sha256(json.dumps(sorted((chunk['chunk_id'], chunk['sha256']) for chunk in chunks)).encode()).hexdigest(),
            'candidate_limit_per_question': CANDIDATES_PER_QUESTION, 'questions': rows,
            'notices': ['Read-only source audit. No annotations, approvals or grades were created.',
                        'Candidates are exact retrieved passages, not validated answers. Search uses question text only.',
                        'Use allowed_chunk_ids to enforce source scope; do not replace missing references with related experiments.',
                        'Qualified review documentation is reported separately and not independently verified.']}
