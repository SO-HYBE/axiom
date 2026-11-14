"""Score top-five passage retrieval against frozen, nonexhaustive draft spans."""
import argparse
import hashlib
import json
from pathlib import Path


FROZEN_DEV_SHA256 = "c31836affa4d0e69913f4f29d3717dad9929b9b5964418085d11943b4b37cf1c"
LIMIT = 5


def cases_digest(cases):
    """Hash ordered JSON records independently of whitespace and newline convention."""
    canonical = "".join(json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"
                        for row in cases)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def rate(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "value": numerator / denominator if denominator else None}


def validate_cases(cases, chunks):
    corpus = {chunk["chunk_id"]: chunk for chunk in chunks}
    if len(corpus) != len(chunks):
        raise ValueError("Duplicate chunk_id in corpus")
    seen = set()
    for case in cases:
        query_id = case.get("query_id")
        if not isinstance(query_id, str) or not query_id.strip() or query_id in seen:
            raise ValueError(f"Invalid or duplicate query_id: {query_id}")
        seen.add(query_id)
        if not isinstance(case.get("query"), str) or not case["query"].strip():
            raise ValueError(f"{query_id}: missing query text")
        if case.get("annotation_status") != "ai_draft" or case.get("span_labels_exhaustive") is not False:
            raise ValueError(f"{query_id}: development labels must declare AI draft, nonexhaustive status")
        spans = case.get("reference_spans")
        if not isinstance(spans, list) or type(case.get("expected_match")) is not bool or bool(spans) != case["expected_match"]:
            raise ValueError(f"{query_id}: expected_match must agree with reference_spans")
        distinct = set()
        for span in spans:
            if not isinstance(span, dict) or any(not isinstance(span.get(key), str) or not span[key].strip()
                                                  for key in ("source_id", "chunk_id", "quote")):
                raise ValueError(f"{query_id}: malformed reference span")
            key = (span["source_id"], span["chunk_id"], span["quote"])
            chunk = corpus.get(span["chunk_id"])
            if not chunk or chunk["source_id"] != span["source_id"] or span["quote"] not in chunk["text"]:
                raise ValueError(f"{query_id}: reference span does not resolve in this corpus")
            if key in distinct:
                raise ValueError(f"{query_id}: duplicate reference span")
            distinct.add(key)
    return corpus


def evaluate_retrieval(cases, chunks, search_fn):
    """The retrieval function sees only the query, corpus and result limit.

    Hit@5 uses answerable queries. Known-span recall@5 pools individually mapped
    spans over answerable queries. A span is found when its containing source
    chunk appears in the first five results. Negative-query abstention is correct
    only when no passages are returned. No metric assesses scientific entailment.
    """
    corpus = validate_cases(cases, chunks)
    hit_queries = positive_queries = found_spans = known_spans = 0
    empty_negative_rankings = negative_queries = 0
    details = []
    for case in cases:
        ranked = list(search_fn(case["query"], chunks, LIMIT))[:LIMIT]
        rankings, rank_by_chunk = [], {}
        for rank, passage in enumerate(ranked, 1):
            cid, sid = passage.get("chunk_id"), passage.get("source_id")
            if cid not in corpus or corpus[cid]["source_id"] != sid or cid in rank_by_chunk:
                raise ValueError(f"{case['query_id']}: retrieved unknown, ambiguous or duplicate chunk: {cid}")
            rank_by_chunk[cid] = rank
            rankings.append({"rank": rank, "source_id": sid, "chunk_id": cid, "score": passage.get("score")})
        references = [{**span, "rank": rank_by_chunk.get(span["chunk_id"])} for span in case["reference_spans"]]
        found = sum(span["rank"] is not None for span in references)
        hit = None
        abstention_correct = None
        if case["expected_match"]:
            positive_queries += 1
            hit = found > 0
            hit_queries += int(hit)
            known_spans += len(references)
            found_spans += found
        else:
            negative_queries += 1
            abstention_correct = not rankings
            empty_negative_rankings += int(abstention_correct)
        details.append({"query_id": case["query_id"], "query": case["query"], "expected_match": case["expected_match"],
                        "rankings": rankings, "reference_spans": references, "hit_at_5": hit,
                        "known_span_recall_at_5": rate(found, len(references)),
                        "negative_abstention_correct": abstention_correct})
    digest = cases_digest(cases)
    return {"kind": "retrieval_development_evaluation", "cutoff": LIMIT,
            "dataset_sha256": digest, "matches_frozen_dev_cases": digest == FROZEN_DEV_SHA256,
            "corpus_chunks": len(chunks), "query_count": len(cases), "answerable_queries": positive_queries,
            "out_of_corpus_queries": negative_queries,
            "hit_at_5": rate(hit_queries, positive_queries),
            "known_span_recall_at_5": rate(found_spans, known_spans),
            "negative_abstention_accuracy": rate(empty_negative_rankings, negative_queries),
            "queries": details,
            "scope": "Engineering check of passage retrieval on nonexhaustive AI draft development labels. Other passages may also be relevant. These scores do not measure scientific answer accuracy or safety."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, help="Optional destination for the full ranked report")
    parser.add_argument("--include-overviews", action="store_true")
    args = parser.parse_args()
    from .research import load_chunks
    from .retrieval import search
    try:
        cases = [json.loads(line) for line in (args.root / "benchmarks/retrieval_dev.jsonl").read_text(
            encoding="utf-8-sig").splitlines() if line.strip()]
        if cases_digest(cases) != FROZEN_DEV_SHA256:
            raise ValueError("Development cases changed since the freeze; use a new version for new labels")
        report = evaluate_retrieval(cases, load_chunks(args.root),
                                    lambda query, chunks, limit: search(query, chunks, limit, include_overviews=args.include_overviews))
        import hashlib
        report['configuration'] = {'version':'lexical-v2', 'include_overviews':args.include_overviews, 'min_query_coverage':0.25}
        report['corpus_sha256'] = hashlib.sha256((args.root/'data/processed/chunks.jsonl').read_bytes()).hexdigest()
        report['retrieval_source_sha256'] = hashlib.sha256(Path(__file__).with_name('retrieval.py').read_bytes()).hexdigest()
        report['development_tuning_note'] = 'The 25% query-term coverage guard was selected using these development queries. Generalization is unverified.' 
        output = json.dumps(report, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output, encoding="utf-8")
        else:
            print(output, end="")
    except (KeyError, OSError, TypeError, ValueError) as exc:
        parser.exit(1, f"AXIOM retrieval evaluation: {exc}\n")


if __name__ == "__main__":
    main()
