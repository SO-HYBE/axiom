import hashlib
import json
import re
import time
from datetime import datetime, timezone
from uuid import uuid4

MAX_CONTEXT_CHARS = 12000
MAX_REVIEW_CALLS = 3
from .critic import check_claim, needs_applicability, validate_conditions
from .model import validate_draft
from .retrieval import search, explicit_scope_context


def load_chunks(root, *, include_named_sources=False):
    path = root / "data/processed/chunks.jsonl"
    if not path.exists():
        raise ValueError("No corpus yet. Run python -m axiom ingest first.")
    chunks = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    # Supplemental snapshots are loaded only for explicit source-description
    # requests. This keeps the core corpus and default research behavior stable.
    if include_named_sources:
        from .benchmark_named_sources import load_named_chunks
        chunks.extend(load_named_chunks(root))
        official_dir = root / "data/processed/official_resources"
        if official_dir.is_dir():
            for resource_path in sorted(official_dir.glob("*.json")):
                record = json.loads(resource_path.read_text(encoding="utf-8"))
                chunks.extend(record.get("chunks", []))
    ids = set()
    for c in chunks:
        if c["chunk_id"] in ids:
            raise ValueError("Duplicate chunk identifier")
        ids.add(c["chunk_id"])
        if hashlib.sha256(c["text"].encode()).hexdigest() != c["sha256"]:
            raise ValueError("Chunk integrity check failed: " + c["chunk_id"])
    inventory_path = root / "data/sources.json"
    if inventory_path.exists():
        inventory = json.loads(inventory_path.read_text(encoding="utf-8")).get("sources", [])
        if inventory:
            sources = {source["source_id"]:source for source in inventory}
            for chunk in chunks:
                source = sources.get(chunk["source_id"])
                if source:
                    chunk["permission_status"] = source.get("permission_status", "review_required")
                    chunk["status"] = source.get("status", "quarantined")
                    chunk["document_url"] = source.get("download_url")
    # Challenge resources are optional metadata layered on the existing shared
    # corpus. Only source IDs explicitly mapped in the supplied inventory are
    # tagged; unrelated evidence keeps its existing interpretation.
    from .official_resources import load_inventory
    try:
        resources = load_inventory(root)["resources"]
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        resources = []
    by_source = {source_id: row for row in resources for source_id in row.get("source_ids", [])}
    by_source.update({row["resource_id"].lower(): row for row in resources})
    by_source["r4-guide"] = next((row for row in resources if row["resource_id"] == "R4"), {})
    for chunk in chunks:
        resource = by_source.get(chunk.get("source_id"))
        if resource:
            chunk.setdefault("resource_id", resource["resource_id"])
            category = "repository_catalog" if chunk.get("source_kind") == "dataset_catalog" else resource["category"]
            chunk.setdefault("source_category", category)
            chunk.setdefault("resource_category", resource["category"])
            chunk.setdefault("source_title", resource["title"])
    return chunks


def load_condition_records(root):
    path = root / 'data/conditions.jsonl'
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8-sig').splitlines() if line.strip()]


def excerpt_draft(question, evidence):
    words = set(re.findall(r"[a-z]{3,}", question.lower()))
    claims = []
    for c in evidence[:3]:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n\s*\n", c["text"]) if len(s.strip()) >= 30]
        if not sentences:
            continue
        sentence = max(sentences, key=lambda s: len(words & set(re.findall(r"[a-z]{3,}", s.lower()))))
        if len(sentence) > 600:
            # Do not truncate into a potentially inverted scientific claim.
            continue
        claims.append({"text": sentence, "citations": [{"source_id": c["source_id"], "chunk_id": c["chunk_id"], "quote": sentence}]})
    return {"claims": claims, "abstained": not bool(claims), "reason": "Extractive preview only; excerpts are not a synthesized answer."}


def unavailable_review(model):
    calls = getattr(model, 'calls', [])
    status = calls[-1].get('status', 'unavailable') if calls else 'unavailable'
    reasons = {
        'rate_limited':'The provider rate limit prevented this review. Retry after the limit resets.',
        'cooldown_exceeded':'The provider cooldown or local queue exceeded the request time budget. Retry later.',
        'retryable_http_error':'The provider remained unavailable after bounded retries.',
        'timeout':'The review reached its time limit.',
        'invalid_response':'The review response failed its structure or source checks.'
    }
    return {'verdict':'uncertain', 'reason':reasons.get(status,'The model review could not finish.'),
            'uncertainty':'Support remains unresolved until a valid review completes.', 'review_failure':status}


def run(question, chunks, model=None, system="ignis", target=None, intent="research", draft=None, experiments=None, source_ids=None, include_overviews=False, condition_records=None, source_scope=None, include_source_descriptions=False, explicit_context_ids=None):
    start = time.perf_counter()
    call_start = len(model.calls) if model else 0
    if not isinstance(question, str) or not question.strip() or len(question) > 4000:
        raise ValueError("Question must be 1–4000 characters")
    if system not in ("ignis", "baseline", "rag_only") or intent not in ("research", "applicability"):
        raise ValueError("Invalid system or intent")
    if source_scope is not None and (not isinstance(source_scope, str) or len(source_scope) > 3000):
        raise ValueError('Source scope must be text of at most 3000 characters')
    if type(include_source_descriptions) is not bool:
        raise ValueError('include_source_descriptions must be boolean')
    if explicit_context_ids is not None and (not isinstance(explicit_context_ids, list)
            or any(not isinstance(value, str) or not value for value in explicit_context_ids)
            or len(set(explicit_context_ids)) != len(explicit_context_ids)):
        raise ValueError('Explicit source context requires unique passage IDs')
    target = target or {}
    validate_conditions(target)
    if system != "ignis" and model is None and draft is None:
        raise ValueError("Baseline/RAG comparisons require a real model or saved model draft")
    applicable = intent == "applicability" or bool(target) or needs_applicability(question)
    evidence = [] if system == "baseline" else search(question, chunks, limit=6, target=target if applicable else None,
                                                        experiments=experiments, source_ids=source_ids, include_overviews=include_overviews,
                                                        include_source_descriptions=include_source_descriptions)
    lexical_hit_count = len(evidence)
    scope_context_used = False

    def prompt_item(chunk):
        item = {key: chunk[key] for key in ("source_id", "chunk_id", "text", "conditions", "locator", "source_kind", "experiment", "evidence_tier")}
        for key in ('evidence_role', 'selection_role'):
            if key in chunk:
                item[key] = chunk[key]
        return item

    if system != 'baseline' and not evidence and source_scope and explicit_context_ids:
        candidate = explicit_scope_context(chunks, explicit_context_ids, experiments=experiments,
            source_ids=source_ids, include_overviews=include_overviews,
            include_source_descriptions=include_source_descriptions)
        if candidate and len(json.dumps([prompt_item(chunk) for chunk in candidate], ensure_ascii=False)) <= MAX_CONTEXT_CHARS:
            evidence = candidate
            scope_context_used = True
    bounded = []
    prompt_evidence = []
    for chunk in evidence:
        item = prompt_item(chunk)
        if len(json.dumps(prompt_evidence + [item], ensure_ascii=False)) <= MAX_CONTEXT_CHARS:
            bounded.append(chunk)
            prompt_evidence.append(item)
    omitted = len(evidence) - len(bounded)
    evidence = bounded
    error = None
    try:
        if draft is not None:
            raw = validate_draft(draft)
        elif system != "baseline" and not evidence:
            raw = {"claims": [], "abstained": True, "reason": "No sufficiently matching passage was found in the selected NASA documents."}
        elif model:
            input_question = question
            if target:
                input_question += '\nUser-proposed environment (unverified input): ' + json.dumps(target, sort_keys=True)
            if source_scope:
                input_question += '\nRequested source scope: ' + source_scope
            raw = model.draft(input_question, prompt_evidence, baseline=system == "baseline")
        else:
            raw = excerpt_draft(question, evidence)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raw = {"claims": [], "abstained": True, "reason": "Model output unavailable or invalid; no answer released."}
        error = str(exc)
    from .evidence_conflicts import conflict_hints
    retrieved_sources = {chunk['source_id'] for chunk in evidence}
    source_records = [record for record in (condition_records or []) if isinstance(record, dict) and record.get('source_id') in retrieved_sources]
    selected_chunk_ids = {chunk['chunk_id'] for chunk in evidence}
    source_cautions = [hint for hint in conflict_hints(source_records, chunks) if selected_chunk_ids.intersection(hint['chunk_ids'])]
    checked = []
    review_calls = 0
    by_id = {c["chunk_id"]: c for c in evidence}
    if system == "ignis":
        batch_reviews = None
        batch_method = getattr(model, 'review_many', None) if model else None
        if callable(batch_method):
            candidates = [index for index, claim in enumerate(raw['claims'])
                          if check_claim(claim, by_id, target, applicable)['verdict'] != 'blocked'][:MAX_REVIEW_CALLS]
            batch_reviews = {}
            if candidates:
                review_calls = 1
                try:
                    results = batch_method([raw['claims'][index]['text'] for index in candidates], prompt_evidence)
                    if len(results) != len(candidates):
                        raise ValueError('Incomplete batch review')
                    batch_reviews = dict(zip(candidates, results))
                except (ValueError, KeyError, TypeError, OSError):
                    batch_reviews = {index:unavailable_review(model) for index in candidates}
        for index, claim in enumerate(raw["claims"]):
            semantic = None
            initial = check_claim(claim, by_id, target, applicable)
            if batch_reviews is not None:
                semantic = batch_reviews.get(index)
            elif model and review_calls < MAX_REVIEW_CALLS and initial["verdict"] != "blocked":
                try:
                    review_calls += 1
                    semantic = model.review(claim["text"], prompt_evidence)
                except (ValueError, KeyError, TypeError, OSError):
                    semantic = unavailable_review(model)
            result = check_claim(claim, by_id, target, applicable, semantic)
            if model and semantic is None and initial['verdict'] != 'blocked':
                result['issues'] = sorted(set(result['issues'] + ['review_budget_exhausted']))
                result['verdict'] = 'needs_review'
                result['evidence_status'] = 'unassessable'
                result['next_evidence'].append('Run a separate bounded review for this additional claim.')
            result['evidence_checks'] = []
            for check in semantic.get('evidence_checks', []) if semantic else []:
                chunk = by_id.get(check['chunk_id'])
                if chunk:
                    result['evidence_checks'].append(dict(check, url=chunk['url'], locator=chunk['locator'], document_url=chunk.get('document_url')))
            result['claim_type'] = claim.get('claim_type','unspecified')
            result['limitations'] = claim.get('limitations','')
            checked.append(result)
        released = [c for c in checked if c["verdict"] in ("quoted_evidence", "model_supported_needs_review")]
        # A model-checked synthesis is provisional and carries that label to the UI.
        abstained = raw["abstained"] or not released or applicable
        if not abstained:
            answer = "\n\n".join(c["text"] for c in released)
        elif error:
            answer = "The model could not complete this answer. The retrieved sources remain available below."
        elif applicable:
            answer = "The retrieved evidence does not establish safety for the proposed environment. Check the missing conditions and source limitations below."
        elif raw["abstained"]:
            answer = raw["reason"]
        else:
            answer = "The draft answer did not pass the source checks. Review the flagged claims and passages below."
    else:
        checked = [{**c, "verdict": "unfiltered"} for c in raw["claims"]]
        abstained = raw["abstained"] or not checked
        answer = raw["reason"] if abstained else "\n\n".join(c["text"] for c in checked)
        released = checked
    final_claims = [] if abstained else released
    summary = any(c["verdict"] == "model_supported_needs_review" for c in final_claims)
    answer_status = "insufficient_evidence" if abstained else "model_checked_summary" if summary else "source_excerpts" if system == "ignis" else "unfiltered_answer"
    steps = [
        {"label":"Find NASA evidence", "detail":f"{len(evidence)} explicitly requested source passages supplied; lexical relevance is not established." if scope_context_used else f"{len(evidence)} passages selected; {omitted} omitted for the context limit." if system != "baseline" else "Baseline uses the model without retrieved documents."},
        {"label":"Draft an answer", "detail":f"{len(raw['claims'])} claims drafted. " + raw["reason"]},
        {"label":"Check claims", "detail":f"{len(final_claims)} claims included; {len(checked)-len(final_claims)} withheld." if system == "ignis" else "This comparison mode shows the unfiltered draft."},
        {"label":"Show the result", "detail":answer_status.replace('_',' ')}
    ]
    return {"run_id":uuid4().hex, "created_at":datetime.now(timezone.utc).isoformat(), "prompt_version":"research-v5-scoped-context", "source_scope":source_scope,
            "evidence_selection":{"mode":"explicit_source_scope" if scope_context_used else "lexical_search" if system != 'baseline' else "baseline_none", "lexical_hit_count":lexical_hit_count, "explicit_scope_complete":scope_context_used},
            "answer_status":answer_status, "provisional":summary, "steps":steps,
            "corpus_fingerprint":hashlib.sha256(json.dumps(sorted((c['chunk_id'],c['sha256']) for c in chunks)).encode()).hexdigest(),
            "model_info":{"model":getattr(model,'name',None), "provider":getattr(model,'provider','ollama' if model else None)},
            "budgets":{"max_evidence_chars":MAX_CONTEXT_CHARS,"max_review_calls":MAX_REVIEW_CALLS,"max_reviewed_claims":3,"review_calls_used":review_calls},
            "question": question, "system": system, "mode": "model" if model else "imported_draft" if draft else "extractive_preview",
            "answer": answer, "abstained": abstained, "claims": final_claims, "draft_checks": checked, "raw_draft": raw,
            "evidence": evidence, "source_cautions":source_cautions, "retrieval_config": {"version":"lexical-v2", "top_k":6, "min_query_coverage":0.25, "experiments":experiments, "source_ids":source_ids, "include_overviews":include_overviews, "include_source_descriptions":include_source_descriptions}, "target": target, "applicability_requested": applicable,
            "latency_ms": round((time.perf_counter() - start) * 1000, 2), "error": error,
            "model_calls": list(model.calls[call_start:]) if model else [],
            "notice": "Research workspace. Rule checks and model reviews are not scientific or operational certification."}
