"""Deterministic lexical retrieval with visible ranking and provenance policy."""
from collections import Counter
import math
import re

from .critic import CONDITIONS, normalized, validate_conditions

STOPWORDS = frozenset('a an and are as at be by can did do does for from had has have how i in is it its of on or our should that the their this to was were what when where which who why will with would you your'.split())
EXCLUDED_KINDS = frozenset({'dataset_catalog', 'metadata', 'catalog', 'overview_metadata'})


def tokens(text):
    return [term for term in re.findall(r'[a-z0-9]+', text.lower()) if term not in STOPWORDS and len(term) > 1]


def applicability(chunk, target):
    if target is None:
        return {'status': 'not_requested', 'unknown_fields': [], 'mismatched_fields': []}
    unknown, mismatched = [], []
    fields = tuple(target) if target else CONDITIONS
    for field in fields:
        requested = target.get(field)
        observed = chunk.get('conditions', {}).get(field)
        if requested is None or observed is None:
            unknown.append(field)
        elif isinstance(requested, str):
            if normalized(requested).casefold() != normalized(str(observed)).casefold():
                mismatched.append(field)
        elif requested != observed:
            mismatched.append(field)
    status = 'mismatch' if mismatched else 'unknown' if unknown else 'matching_fields'
    return {'status': status, 'unknown_fields': unknown, 'mismatched_fields': mismatched, 'unassessed_fields':[field for field in CONDITIONS if field not in fields],
            'notice': 'Comparison of recorded fields only. Scientific transfer requires additional evidence.'}


def eligible(chunk, experiments, source_ids, include_overviews, include_source_descriptions=False):
    if chunk.get('permission_status', 'allowed') != 'allowed':
        return False
    if chunk.get('status', 'active') not in ('active', 'ingested'):
        return False
    if chunk.get('source_kind') in EXCLUDED_KINDS:
        verified_description = (
            include_source_descriptions is True
            and chunk['source_kind'] in ('dataset_catalog', 'catalog')
            and chunk.get('permission_status') == 'allowed'
            and chunk.get('evidence_role') == 'source_description'
            and chunk.get('named_scope_verified') is True
        )
        if not verified_description:
            return False
    if chunk.get('source_kind') == 'experiment_overview' and not include_overviews:
        return False
    if experiments and chunk.get('experiment', '').casefold() not in {x.casefold() for x in experiments}:
        return False
    return not source_ids or chunk.get('source_id') in source_ids


def search(query, chunks, limit=6, *, target=None, experiments=None, source_ids=None, include_overviews=False, min_query_coverage=0.25, include_source_descriptions=False):
    """Rank lexical matches. Never infer synonyms, measurement values or confidence.

    Exact duplicate passages share attribution. Distinct passages from the same
    document remain available. Conditions affect ordering among lexical matches
    only when the caller explicitly supplies a target.
    """
    if not isinstance(min_query_coverage, (int, float)) or isinstance(min_query_coverage, bool) or not 0 <= min_query_coverage <= 1:
        raise ValueError('Query coverage threshold must be between zero and one')
    if target is not None:
        validate_conditions(target)
    if limit <= 0:
        return []
    terms = sorted(set(tokens(query)))
    if not terms:
        return []
    corpus = [c for c in chunks if eligible(c, experiments, source_ids, include_overviews, include_source_descriptions)]
    if not corpus:
        return []
    documents = [tokens(' '.join([c.get('title',''), c.get('experiment',''), c.get('source_id',''), c['text']])) for c in corpus]
    frequencies = Counter(term for doc in documents for term in set(doc))
    average_length = sum(map(len,documents)) / len(documents) or 1
    ranked = []
    for chunk, doc in zip(corpus, documents):
        counts = Counter(doc)
        score = 0.0
        matched = []
        for term in terms:
            frequency = counts.get(term,0)
            if not frequency:
                continue
            inverse = math.log(1 + (len(documents)-frequencies[term]+0.5)/(frequencies[term]+0.5))
            score += inverse * (frequency*2.2)/(frequency+1.2*(0.25+0.75*len(doc)/average_length))
            matched.append(term)
        if score <= 0 or len(matched)/len(terms) < min_query_coverage:
            continue
        explanation = {'lexical_score':round(score,6), 'matched_terms':matched,
                       'evidence_tier':chunk.get('evidence_tier',99), 'applicability':applicability(chunk,target),
                       'duplicate_source_ids':[], 'duplicate_citations':[],
                       'query_term_coverage':len(matched)/len(terms), 'minimum_query_coverage':min_query_coverage, 'independence':'not_assessed',
                       'body_matched_terms':sorted(set(tokens(chunk['text'])) & set(terms))}
        ranked.append(dict(chunk, score=round(score,6), ranking=explanation))
    # Mismatch demotion is explicit. Unknown fields never establish a match.
    def order(chunk):
        mismatch = chunk['ranking']['applicability']['status'] == 'mismatch'
        return (mismatch, -chunk['score'], chunk.get('evidence_tier',99), chunk['chunk_id'])
    ranked.sort(key=order)
    deduplicated = []
    seen = {}
    for chunk in ranked:
        source = chunk.get('source_id')
        key = (' '.join(chunk['text'].split()), repr(sorted(chunk.get('conditions', {}).items())), chunk.get('experiment'), chunk.get('source_kind')) if source else None
        if key is None or key not in seen:
            deduplicated.append(chunk)
            if key is not None:
                seen[key] = chunk
            continue
        selected = seen[key]['ranking']
        if source != seen[key].get('source_id') and source not in selected['duplicate_source_ids']:
            selected['duplicate_source_ids'].append(source)
        selected['duplicate_citations'].append({k:chunk.get(k) for k in ('source_id','chunk_id','url','locator')})
    return deduplicated[:limit]


def explicit_scope_context(chunks, chunk_ids, *, experiments=None, source_ids=None,
                           include_overviews=False, include_source_descriptions=False):
    """Return an entire small, explicitly named scope without claiming relevance.

    This is an opt-in context route, never a lower search threshold. A missing,
    held, duplicate or oversized selection returns nothing rather than silently
    supplying only part of the requested scope. Serialization budgets are checked
    by the research caller before any of these passages enter a model prompt.
    """
    if (not isinstance(chunk_ids, list) or not chunk_ids or len(chunk_ids) > 6
            or any(not isinstance(value, str) or not value for value in chunk_ids)
            or len(set(chunk_ids)) != len(chunk_ids)):
        return []
    wanted = set(chunk_ids)
    selected = [chunk for chunk in chunks if chunk.get('chunk_id') in wanted]
    if (len(selected) != len(wanted) or {chunk['chunk_id'] for chunk in selected} != wanted
            or not all(eligible(chunk, experiments, source_ids, include_overviews,
                                include_source_descriptions) for chunk in selected)):
        return []
    return [dict(chunk, score=None, selection_role='explicit_source_scope', ranking={
        'selection': 'explicit_source_scope', 'lexical_relevance': 'not_established',
        'evidence_tier': chunk.get('evidence_tier'),
        'notice': 'Provided because the exact source scope was requested; no relevance or scientific support is implied.'})
        for chunk in sorted(selected, key=lambda row: (row['source_id'], row.get('locator', ''), row['chunk_id']))]
