import argparse
import json
import os
import sys
from pathlib import Path


def _allowed_values(values, environment):
    items = list(values or ())
    items.extend(part.strip() for part in environment.split(',') if part.strip())
    return list(dict.fromkeys(items))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="AXIOM microgravity combustion research workspace")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("ingest", help="Fetch allowlisted NASA documents and build the corpus")
    ask = commands.add_parser("ask")
    ask.add_argument("question")
    ask.add_argument("--model", help="Fixed model ID; provider default if omitted")
    ask.add_argument("--provider", choices=("groq", "openrouter", "ollama", "extractive"), default="groq")
    ask.add_argument("--system", choices=("ignis", "baseline", "rag_only"), default="ignis")
    ask.add_argument("--intent", choices=("research", "applicability"), default="research")
    ask.add_argument("--target", type=Path, help="JSON conditions in documented units")
    ask.add_argument("--draft", type=Path, help="Import saved model draft JSON")
    ask.add_argument("--output", type=Path)
    lookup = commands.add_parser("search", help="Inspect ranked evidence without a model call")
    lookup.add_argument("question")
    lookup.add_argument("--limit", type=int, default=6)
    for command in (ask, lookup):
        command.add_argument("--experiment", action="append")
        command.add_argument("--source-id", action="append")
        command.add_argument("--include-overviews", action="store_true")
        command.add_argument("--include-source-descriptions", action="store_true")
    lookup.add_argument("--target", type=Path)
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default=os.environ.get("AXIOM_HOST", "127.0.0.1"),
                       help="Bind address; keep 127.0.0.1 for local use")
    serve.add_argument("--port", type=int, default=int(os.environ.get("AXIOM_PORT", "8765")))
    serve.add_argument("--allowed-host", action="append", dest="allowed_hosts",
                       help="Public Host header to accept, e.g. axiom.example.org (repeatable)")
    serve.add_argument("--allowed-origin", action="append", dest="allowed_origins",
                       help="Browser origin allowed to call the API, e.g. https://app.example.org (repeatable)")
    serve.add_argument("--log-requests", action="store_true",
                       help="Write access log lines to stderr")
    evaluation = commands.add_parser("evaluate")
    evaluation.add_argument("predictions", type=Path)
    evaluation.add_argument("annotations", type=Path)
    audit = commands.add_parser('benchmark-audit', help='Check all question source scopes without model calls')
    audit.add_argument('--output', type=Path)
    commands.add_parser('benchmark-ingest', help='Acquire exact named NASA benchmark sections; preserve existing caches')
    commands.add_parser('resource-report', help='Write a timestamped snapshot of official resource acquisition and indexing status')
    resource_ingest = commands.add_parser('official-ingest', help='Acquire allowlisted NASA challenge pages and the R4 guide PDF')
    resource_ingest.add_argument('--resource-id', action='append', dest='resource_ids')
    batch = commands.add_parser('benchmark-run', help='Save resumable, ungraded benchmark answers')
    batch.add_argument('--provider', required=True, choices=('groq','openrouter','ollama','extractive'))
    batch.add_argument('--model')
    batch.add_argument('--systems', nargs='+', choices=('baseline','rag_only','ignis'), default=['baseline','ignis'])
    batch.add_argument('--split', choices=('dev','test','all'), default='dev')
    batch.add_argument('--question-id', action='append')
    batch.add_argument('--limit', type=int)
    batch.add_argument('--max-jobs', type=int)
    batch.add_argument('--resume', help='ID from a previous benchmark run with identical inputs')
    batch.add_argument('--fresh', action='store_true')
    batch.add_argument('--diagnostics', action='store_true', help='Capture bounded, credential-screened rejected model content locally')
    packet = commands.add_parser('benchmark-packet', help='Prepare answers for independent review, without grades')
    packet.add_argument('run_id')
    review_bundle = commands.add_parser('benchmark-review-bundle', help='Export a public, ungraded packet for later human review')
    review_bundle.add_argument('run_id')
    report = commands.add_parser('benchmark-report', help='Read progress or apply separately supplied annotations')
    report.add_argument('run_id')
    report.add_argument('--annotations', type=Path)
    inspect = commands.add_parser('benchmark-inspect', help='Verify saved run integrity and report engineering observations, without grading')
    inspect.add_argument('run_id')
    inspect.add_argument('--output', type=Path)
    retrieval_audit = commands.add_parser('retrieval-audit', help='Inspect frozen source-scope misses without models or grading labels')
    retrieval_audit.add_argument('--run-id', default='3c3cc0f1e4b949a8a33296e94417f13c')
    retrieval_audit.add_argument('--output', type=Path)
    reviewed = commands.add_parser('benchmark-review-import', help='Import a completed human review packet without changing original answers')
    reviewed.add_argument('run_id')
    reviewed.add_argument('review_path', type=Path)
    demo = commands.add_parser('demo', help='Inspect saved demonstrations without any model request')
    demo.add_argument('demo_id', nargs='?')
    release = commands.add_parser('release-build', help='Package code, frozen evidence and saved demonstrations')
    release.add_argument('--output', type=Path, default=Path('dist/phase7'))
    verify = commands.add_parser('release-verify', help='Verify release archive hashes and paths')
    verify.add_argument('path', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'retrieval-audit':
            from .retrieval_audit import audit_retrieval
            result = audit_retrieval(args.root, args.run_id)
            if args.output:
                from .benchmark_run import _write
                _write(args.output, result)
        elif args.command == 'benchmark-review-import':
            from .benchmark_review import import_review
            result = import_review(args.root, args.run_id, args.review_path)
        elif args.command == 'demo':
            from .demo import list_demos, get_demo
            result = get_demo(args.root, args.demo_id) if args.demo_id else {'demos':list_demos(args.root)}
        elif args.command == 'release-build':
            from .release import build_release
            result = build_release(args.root, args.output)
        elif args.command == 'release-verify':
            from .release import verify_release
            result = verify_release(args.path)
        elif args.command == 'benchmark-ingest':
            from .benchmark_named_sources import collect_named_sources
            result = collect_named_sources(args.root)
        elif args.command == 'resource-report':
            from .official_resources import write_report
            result = write_report(args.root)
        elif args.command == 'official-ingest':
            from .official_resources import acquire_official_resources
            result = acquire_official_resources(args.root, args.resource_ids)
        elif args.command == 'benchmark-audit':
            from .benchmark_audit import audit_benchmark
            result = audit_benchmark(args.root)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
        elif args.command == 'benchmark-run':
            from .benchmark_run import run_benchmark
            def show_progress(value):
                counts = value['progress']
                print(f"{value['run_id']} {value['question_id']} {value['system']}: "
                      f"{counts['completed']} completed, {counts['failed']} failed, {counts['pending']} pending", file=sys.stderr, flush=True)
            result = run_benchmark(args.root, provider=args.provider, model=args.model, systems=args.systems,
                                   split=args.split, question_ids=args.question_id, limit=args.limit,
                                   max_jobs=args.max_jobs, resume=args.resume, fresh=args.fresh, progress=show_progress, diagnostics=args.diagnostics)
        elif args.command == 'benchmark-review-bundle':
            from .review_bundle import prepare_review_bundle
            result = prepare_review_bundle(args.root, args.run_id)
        elif args.command == 'benchmark-packet':
            from .benchmark_run import prepare_review_packet
            result = prepare_review_packet(args.root, args.run_id)
        elif args.command == 'benchmark-inspect':
            from .benchmark_inspect import inspect_benchmark
            result = inspect_benchmark(args.root, args.run_id)
            if args.output:
                from .benchmark_run import _write
                _write(args.output, result)
        elif args.command == 'benchmark-report':
            from .benchmark_run import get_benchmark, _directory, _records, _write
            from .benchmark_report import summarize_benchmark
            from .evaluate import load_jsonl
            saved = get_benchmark(args.root, args.run_id)
            result = saved['report']
            if args.annotations:
                predictions = [record['prediction'] for record in _records(_directory(args.root,args.run_id),saved['manifest'])]
                result = summarize_benchmark(saved['manifest'], predictions, load_jsonl(args.annotations))
                _write(_directory(args.root,args.run_id)/'report.with_supplied_annotations.json',result)
        elif args.command == "ingest":
            from .ingest import ingest
            result = ingest(args.root)
        elif args.command == "search":
            from .research import load_chunks
            from .retrieval import search
            target = json.loads(args.target.read_text()) if args.target else None
            result = {"query":args.question, "evidence":search(args.question,
                      load_chunks(args.root, include_named_sources=args.include_source_descriptions), args.limit,
                      target=target, experiments=args.experiment, source_ids=args.source_id,
                      include_overviews=args.include_overviews,
                      include_source_descriptions=args.include_source_descriptions)}
        elif args.command == "serve":
            from .server import serve
            if args.log_requests:
                os.environ['AXIOM_LOG_REQUESTS'] = '1'
            serve(args.root, args.port, args.host,
                  _allowed_values(args.allowed_hosts, os.environ.get("AXIOM_ALLOWED_HOSTS", "")),
                  _allowed_values(args.allowed_origins, os.environ.get("AXIOM_ALLOWED_ORIGINS", "")))
            return
        elif args.command == "evaluate":
            from .evaluate import evaluate
            read = lambda p: [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
            result = evaluate(read(args.predictions), read(args.annotations))
        else:
            from .providers import make_model
            from .research import load_chunks, load_condition_records, run
            result = run(args.question, load_chunks(args.root, include_named_sources=args.include_source_descriptions), make_model(args.root, args.provider, args.model) if not args.draft else None,
                         args.system, json.loads(args.target.read_text()) if args.target else None,
                         args.intent, json.loads(args.draft.read_text(encoding="utf-8")) if args.draft else None,
                         experiments=args.experiment, source_ids=args.source_id, include_overviews=args.include_overviews,
                         condition_records=load_condition_records(args.root))
            from .run_records import save_run
            try:
                save_run(args.root, result)
                result['saved_locally'] = True
            except OSError:
                result['saved_locally'] = False
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f"AXIOM: {exc}\n")
