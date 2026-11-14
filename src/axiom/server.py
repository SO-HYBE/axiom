"""Research dashboard HTTP service; browser output is text-rendered and host-checked.

The service binds to loopback by default. A container or reverse proxy can bind
elsewhere and must declare the public host names it answers for; undeclared
``Host`` headers are refused so that a public listener cannot be reached through
DNS rebinding. Cross-origin browser access is refused unless the calling origin
is declared explicitly, which supports a separately hosted static frontend.
``/healthz`` reports corpus readiness without exposing paths.
"""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from .research import load_chunks, load_condition_records, run
from .providers import make_model

LOOPBACK_HOSTS = ('127.0.0.1', 'localhost', '[::1]')
POST_PATHS = frozenset({'/api/ask', '/api/compare', '/api/scenario-assess',
                        '/api/scenario-plan', '/api/axiom/trace-demo'})
AXIOM_RESULT_FILES = {
    'evaluation': 'runs/axiom/evaluation/results.json',
    'trace-lab': 'runs/axiom/trace_lab/results.json',
    'extraction-validation': 'runs/axiom/extraction_validation/results.json',
}


def load_axiom_result(root, artifact):
    """Load one allowlisted result object, returning not_run when absent."""
    if artifact not in AXIOM_RESULT_FILES:
        raise KeyError('Unknown AXIOM result')
    path = Path(root) / AXIOM_RESULT_FILES[artifact]
    if not path.exists():
        return {'status': 'not_run', 'results': None}
    if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
        raise ValueError('AXIOM result path redirects')
    if path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError('AXIOM result exceeds the read limit')
    result = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(result, dict):
        raise ValueError('AXIOM result must be a JSON object')
    return {'status': 'available', 'results': result}


def _normalize_host(value):
    if not isinstance(value, str):
        return ''
    return value.strip().lower().rstrip('.')


def _loopback_hosts(port):
    return {f'{name}:{port}' for name in LOOPBACK_HOSTS} | set(LOOPBACK_HOSTS)


def _normalize_origin(value):
    """Return a canonical ``scheme://host[:port]`` origin, or an empty string.

    Only absolute HTTP(S) origins without credentials, paths, queries or
    fragments are accepted. Default ports are dropped so that declarations and
    browser ``Origin`` headers compare consistently.
    """
    if not isinstance(value, str):
        return ''
    try:
        parsed = urlparse(value.strip())
        port = parsed.port
    except ValueError:
        return ''
    scheme = parsed.scheme.lower()
    if (scheme not in ('http', 'https') or not parsed.netloc or not parsed.hostname
            or parsed.username or parsed.password
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        return ''
    host = parsed.hostname.lower()
    if ':' in host:
        host = f'[{host}]'
    if port in (None, 80 if scheme == 'http' else 443):
        return f'{scheme}://{host}'
    return f'{scheme}://{host}:{port}'


def _content_security_policy(allowed_origins):
    connect = ' '.join(["'self'", *sorted(allowed_origins)])
    return ("default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; connect-src " + connect +
            "; frame-ancestors 'none'")


def make_handler(root, allowed_hosts=None, allowed_origins=None, record_root=None):
    """Create the HTTP handler. ``record_root`` may be ephemeral on serverless hosts."""
    record_root = Path(record_root) if record_root is not None else Path(root)
    extra_hosts = frozenset(_normalize_host(host) for host in (allowed_hosts or ()) if _normalize_host(host))
    origins = frozenset(origin for origin in (_normalize_origin(item) for item in (allowed_origins or ()))
                        if origin)
    policy = _content_security_policy(origins)

    class Handler(BaseHTTPRequestHandler):
        def send(self, status, body, content_type="application/json; charset=utf-8", extra_headers=None):
            raw = body.encode("utf-8")
            self.send_response(status)
            origin = _normalize_origin(self.headers.get('Origin', ''))
            if origin:
                self.send_header("Vary", "Origin")
                if origin in origins:
                    self.send_header("Access-Control-Allow-Origin", origin)
            if content_type:
                self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", policy)
            for name, value in (extra_headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            if raw:
                self.wfile.write(raw)

        def valid_host(self):
            host = _normalize_host(self.headers.get('Host', ''))
            return host in _loopback_hosts(self.server.server_port) or host in extra_hosts

        def do_OPTIONS(self):
            if not self.valid_host():
                return self.send(403, '{"error":"Invalid host"}')
            if urlparse(self.path).path not in POST_PATHS:
                return self.send(404, '{"error":"Not found"}')
            origin = _normalize_origin(self.headers.get('Origin', ''))
            if not origin or origin not in origins:
                return self.send(403, '{"error":"Origin is not allowed"}')
            return self.send(204, '', content_type=None, extra_headers={
                'Access-Control-Allow-Methods': 'POST, OPTIONS',
                'Access-Control-Allow-Headers': 'Content-Type',
                'Access-Control-Max-Age': '600',
            })

        def page_options(self):
            values = parse_qs(urlparse(self.path).query, keep_blank_values=True)
            if set(values) - {'limit', 'offset', 'q'} or any(len(v) != 1 for v in values.values()):
                raise ValueError('Invalid saved-work query')
            return {'limit':int(values.get('limit',['20'])[0]), 'offset':int(values.get('offset',['0'])[0]), 'query':values.get('q',[''])[0]}

        def do_GET(self):
            if not self.valid_host():
                return self.send(403, '{"error":"Invalid host"}')
            path = urlparse(self.path).path
            if path == "/healthz":
                try:
                    chunks = load_chunks(root)
                    inventory = json.loads((root / "data/sources.json").read_text(encoding="utf-8"))
                    sources = inventory.get("sources")
                    if not isinstance(sources, list) or not chunks:
                        raise ValueError("Scientific data is not ready")
                    return self.send(200, json.dumps({
                        "status": "ok", "service": "axiom", "chunks": len(chunks),
                        "ingested_sources": len({chunk["source_id"] for chunk in chunks}),
                        "sources": len(sources)}, ensure_ascii=False))
                except (OSError, ValueError, KeyError, TypeError):
                    return self.send(503, '{"status":"error","service":"axiom","error":"Scientific data is unavailable"}')
            if path == '/api/demos' or path.startswith('/api/demos/'):
                from .demo import list_demos, get_demo
                try:
                    result = {'demos': list_demos(root)} if path == '/api/demos' else get_demo(root, path.removeprefix('/api/demos/'))
                    return self.send(200, json.dumps(result, ensure_ascii=False))
                except FileNotFoundError:
                    return self.send(404, '{"error":"Saved demonstration was not found"}')
                except ValueError as exc:
                    return self.send(400, json.dumps({'error':str(exc)}))
                except OSError:
                    return self.send(503, '{"error":"Saved demonstrations are temporarily unavailable"}')
            if path == '/api/benchmark' or path.startswith('/api/benchmark/'):
                from .benchmark_audit import audit_benchmark
                from .benchmark_run import latest_benchmark, benchmark_answers
                try:
                    if path == '/api/benchmark':
                        latest = latest_benchmark(root)
                        if latest:
                            manifest = latest['manifest']
                            latest = {'run_id':manifest['run_id'], 'status':manifest['status'],
                                      'created_at':manifest['created_at'], 'provider':manifest['inputs']['provider'],
                                      'model':manifest['inputs']['model'], 'split':manifest['inputs']['split'],
                                      'report':latest['report']}
                        return self.send(200, json.dumps({'audit':audit_benchmark(root), 'latest':latest}, ensure_ascii=False))
                    if path.endswith('/impact'):
                        from .benchmark_impact import summarize_impact
                        identifier = path.removeprefix('/api/benchmark/').removesuffix('/impact')
                        return self.send(200, json.dumps(summarize_impact(root, identifier), ensure_ascii=False))
                    if path.endswith('/answers'):
                        identifier = path.removeprefix('/api/benchmark/').removesuffix('/answers')
                        return self.send(200, json.dumps({'answers':benchmark_answers(root,identifier)}, ensure_ascii=False))
                    return self.send(404, '{"error":"Not found"}')
                except FileNotFoundError:
                    return self.send(404, '{"error":"Benchmark work was not found"}')
                except ValueError as exc:
                    return self.send(400, json.dumps({'error':str(exc)}))
                except OSError:
                    return self.send(503, '{"error":"Benchmark work is temporarily unavailable"}')
            if path == '/api/scenario-metadata':
                from .scenario import catalog
                try:
                    return self.send(200, json.dumps(catalog(root), ensure_ascii=False))
                except (ValueError, OSError) as exc:
                    return self.send(503, json.dumps({'error':str(exc)}))
            if path.startswith('/api/axiom/'):
                artifact = path.removeprefix('/api/axiom/')
                if artifact not in AXIOM_RESULT_FILES:
                    return self.send(404, '{"error":"AXIOM result was not found"}')
                try:
                    return self.send(200, json.dumps(load_axiom_result(root, artifact),
                                                     ensure_ascii=False, allow_nan=False))
                except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                    return self.send(503, '{"error":"AXIOM result is unavailable or malformed"}')
            if path == '/api/scenarios' or path.startswith('/api/scenarios/'):
                from .run_records import list_scenarios, load_scenario
                try:
                    if path == '/api/scenarios':
                        result = list_scenarios(record_root, **self.page_options())
                    elif path.startswith('/api/scenarios/'):
                        result = load_scenario(record_root, path.removeprefix('/api/scenarios/'))
                    else:
                        return self.send(404, '{"error":"Not found"}')
                    return self.send(200, json.dumps(result, ensure_ascii=False))
                except FileNotFoundError:
                    return self.send(404, '{"error":"Saved scenario was not found"}')
                except ValueError as exc:
                    return self.send(400, json.dumps({'error':str(exc)}))
                except OSError:
                    return self.send(503, '{"error":"Saved scenarios are temporarily unavailable"}')
            if path.startswith('/api/runs') or path.startswith('/api/comparisons'):
                from .run_records import list_runs, load_run, list_comparisons, load_comparison
                try:
                    if path == '/api/runs':
                        result = list_runs(record_root, **self.page_options())
                    elif path == '/api/comparisons':
                        result = list_comparisons(record_root, **self.page_options())
                    elif path.startswith('/api/runs/'):
                        result = load_run(record_root, path.removeprefix('/api/runs/'))
                    elif path.startswith('/api/comparisons/'):
                        result = load_comparison(record_root, path.removeprefix('/api/comparisons/'))
                    else:
                        return self.send(404, '{"error":"Not found"}')
                    return self.send(200, json.dumps(result, ensure_ascii=False))
                except FileNotFoundError:
                    return self.send(404, '{"error":"Saved result was not found"}')
                except ValueError as exc:
                    return self.send(400, json.dumps({'error':str(exc)}))
                except OSError:
                    return self.send(503, '{"error":"Saved work is temporarily unavailable"}')
            if path == "/":
                self.send(200, (Path(__file__).parent / "web/index.html").read_text(encoding="utf-8"), "text/html; charset=utf-8")
            elif path == "/config.js":
                self.send(200, (Path(__file__).parent / "web/config.js").read_text(encoding="utf-8"), "application/javascript; charset=utf-8")
            elif path == "/api/conditions":
                try:
                    from .corpus_audit import audit
                    from .conditions import validate_records
                    path = root / "data/conditions.jsonl"
                    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []
                    from .review import review_state, rows
                    chunks = load_chunks(root)
                    validation = validate_records(records, chunks)
                    state = review_state(root, chunks, records, rows(root/'data/review_queue.jsonl'))
                    records = [dict(r, decision=state.get(('condition', r['record_id']))) for r in records]
                    self.send(200, json.dumps({"coverage": audit(root), "validation": validation, "records": records}))
                except (OSError, ValueError, KeyError) as exc:
                    self.send(503, json.dumps({"error": str(exc)}))
            elif path == "/api/status":
                try:
                    chunks = load_chunks(root)
                    sources = json.loads((root / "data/sources.json").read_text(encoding="utf-8"))
                    sources['scope'] = 'NASA microgravity combustion reports and catalog references'
                    self.send(200, json.dumps({"chunks": len(chunks), "sources": sources,
                                               "ingested_sources": len({c['source_id'] for c in chunks}),
                                               "mode": "research_workspace"}))
                except (OSError, ValueError, KeyError) as exc:
                    self.send(503, json.dumps({"error": str(exc)}))
            elif path == "/api/resources":
                try:
                    from .official_resources import build_report
                    self.send(200, json.dumps(build_report(root), ensure_ascii=False, allow_nan=False))
                except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
                    self.send(503, json.dumps({"error": str(exc)}))
            else:
                self.send(404, '{"error":"Not found"}')

        def do_POST(self):
            if urlparse(self.path).path not in POST_PATHS:
                return self.send(404, '{"error":"Not found"}')
            if not self.valid_host():
                return self.send(403, '{"error":"Invalid host"}')
            host = _normalize_host(self.headers.get("Host", ""))
            origin = _normalize_origin(self.headers.get("Origin", ""))
            if origin and urlparse(origin).netloc != host and origin not in origins:
                return self.send(403, '{"error":"Origin is not allowed"}')
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.send(415, '{"error":"Use JSON"}')
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 100_000:
                    raise ValueError("Request exceeds input limits")
                obj = json.loads(self.rfile.read(length))
                if not isinstance(obj, dict):
                    raise ValueError("Expected a JSON object")
                if self.path == '/api/scenario-assess':
                    from .scenario import assess
                    return self.send(200, json.dumps(assess(root, obj, save_root=record_root), ensure_ascii=False, allow_nan=False))
                if self.path == '/api/scenario-plan':
                    from .scenario import plan
                    return self.send(200, json.dumps(plan(root, obj, record_root=record_root), ensure_ascii=False, allow_nan=False))
                if self.path == '/api/axiom/trace-demo':
                    from .trace_demo import build_demo
                    return self.send(200, json.dumps(build_demo(root, obj.get('preset')),
                                                     ensure_ascii=False, allow_nan=False))
                from .comparison import compare, validate_request
                obj = validate_request(obj)
                if self.path == '/api/compare':
                    return self.send(200, json.dumps(compare(root, obj, record_root=record_root), ensure_ascii=False))
                result = run(obj['question'], load_chunks(root, include_named_sources=obj.get('include_source_descriptions') is True), make_model(root, obj['provider'], obj.get('model'), use_cache=not obj.get('fresh',False)),
                             obj.get("system", "ignis"), obj.get("target", {}), obj.get("intent", "research"),
                             experiments=obj.get("experiments"), source_ids=obj.get("source_ids"), include_overviews=obj.get("include_overviews", False),
                             condition_records=load_condition_records(root))
                from .run_records import save_run
                result['saved_locally'] = True
                try:
                    save_run(record_root, result)
                except (OSError, ValueError):
                    result['saved_locally'] = False
                    result['save_error'] = 'The answer is available but could not be saved locally.'
                self.send(200, json.dumps(result, ensure_ascii=False))
            except (ValueError, KeyError, TypeError, OSError) as exc:
                self.send(400, json.dumps({"error": str(exc)}))

        def log_message(self, format, *args):
            if getattr(self.server, 'log_requests', False):
                super().log_message(format, *args)
    return Handler


def serve(root, port=8765, host='127.0.0.1', allowed_hosts=None, allowed_origins=None):
    """Serve the dashboard. Loopback hosts are always accepted; additional
    public host names and cross-origin browser origins must be declared
    explicitly."""
    root = Path(root)
    if not (root / 'data/processed/chunks.jsonl').is_file():
        raise ValueError('Scientific corpus is missing; run python -m axiom ingest first')
    server = ThreadingHTTPServer((host, port), make_handler(root, allowed_hosts, allowed_origins))
    server.log_requests = os.environ.get('AXIOM_LOG_REQUESTS', '0') == '1'
    display = '127.0.0.1' if host in ('0.0.0.0', '::') else host
    print(f"AXIOM research workspace: http://{display}:{server.server_port}", flush=True)
    print("Health check: /healthz", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
