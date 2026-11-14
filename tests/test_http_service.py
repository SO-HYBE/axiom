"""HTTP service tests for the health probe, host checks and split-origin CORS."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from axiom.server import _normalize_host, _normalize_origin, make_handler
from test_research import corpus


class HealthAndHostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "data/processed").mkdir(parents=True)
        (self.root / "data/processed/chunks.jsonl").write_text(json.dumps(corpus()[0]), encoding="utf-8")
        (self.root / "data/sources.json").write_text('{"sources": []}', encoding="utf-8")
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            make_handler(self.root, ["public.example", "public.example:443"]))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def get(self, path, headers=None):
        request = urllib.request.Request(self.url + path, headers=headers or {})
        return self.opener.open(request, timeout=5)

    def test_health_reports_corpus_readiness_without_local_paths(self):
        with self.get("/healthz") as response:
            self.assertEqual(200, response.status)
            body = json.load(response)
        self.assertEqual("ok", body["status"])
        self.assertEqual("ignis", body["service"])
        self.assertEqual(1, body["chunks"])
        self.assertNotIn(str(self.root), json.dumps(body))

    def test_health_fails_closed_when_the_corpus_is_missing(self):
        empty = Path(self.temp.name) / "empty"
        (empty / "data").mkdir(parents=True)
        (empty / "data/sources.json").write_text('{"sources": []}', encoding="utf-8")
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(empty))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/healthz"
            with self.assertRaises(urllib.error.HTTPError) as raised:
                self.opener.open(url, timeout=5)
            self.assertEqual(503, raised.exception.code)
            self.assertEqual("error", json.load(raised.exception)["status"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_declared_public_host_is_accepted(self):
        for host in ("public.example", "PUBLIC.EXAMPLE", "public.example:443", "public.example."):
            with self.subTest(host=host):
                with self.get("/api/status", {"Host": host}) as response:
                    self.assertEqual(200, response.status)

    def test_undeclared_host_is_refused_before_work(self):
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.get("/api/status", {"Host": "attacker.example"})
        self.assertEqual(403, raised.exception.code)

    def test_responses_carry_restrictive_browser_headers(self):
        with self.get("/healthz") as response:
            self.assertEqual("nosniff", response.headers["X-Content-Type-Options"])
            self.assertEqual("DENY", response.headers["X-Frame-Options"])
            self.assertEqual("no-referrer", response.headers["Referrer-Policy"])
            self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])

    def test_host_normalization_is_case_and_dot_insensitive(self):
        self.assertEqual("example.org:443", _normalize_host(" Example.ORG:443. "))
        self.assertEqual("", _normalize_host(None))


class SplitOriginTests(unittest.TestCase):
    ORIGIN = "https://app.example"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "data/processed").mkdir(parents=True)
        (self.root / "data/processed/chunks.jsonl").write_text(json.dumps(corpus()[0]), encoding="utf-8")
        (self.root / "data/sources.json").write_text('{"sources": []}', encoding="utf-8")
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            make_handler(self.root, ["public.example"], [self.ORIGIN]))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def open(self, path, headers=None, method=None, body=None):
        request = urllib.request.Request(self.url + path, headers=headers or {},
                                         data=body, method=method)
        return self.opener.open(request, timeout=5)

    def test_allowed_origin_receives_cors_headers_and_a_matching_policy(self):
        with self.open("/api/status", {"Origin": self.ORIGIN}) as response:
            self.assertEqual(200, response.status)
            self.assertEqual(self.ORIGIN, response.headers["Access-Control-Allow-Origin"])
            self.assertEqual("Origin", response.headers["Vary"])
            policy = response.headers["Content-Security-Policy"]
            self.assertIn("connect-src 'self' " + self.ORIGIN, policy)
            self.assertIn("frame-ancestors 'none'", policy)

    def test_undeclared_origin_gets_no_cors_grant(self):
        with self.open("/api/status", {"Origin": "https://attacker.example"}) as response:
            self.assertEqual(200, response.status)
            self.assertIsNone(response.headers["Access-Control-Allow-Origin"])

    def test_preflight_is_accepted_only_for_declared_origins(self):
        headers = {"Origin": self.ORIGIN, "Access-Control-Request-Method": "POST",
                   "Access-Control-Request-Headers": "content-type"}
        with self.open("/api/scenario-assess", headers, method="OPTIONS") as response:
            self.assertEqual(204, response.status)
            self.assertEqual(self.ORIGIN, response.headers["Access-Control-Allow-Origin"])
            self.assertIn("POST", response.headers["Access-Control-Allow-Methods"])
            self.assertIn("Content-Type", response.headers["Access-Control-Allow-Headers"])
            self.assertEqual("0", response.headers["Content-Length"])
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.open("/api/scenario-assess", {"Origin": "https://attacker.example"}, method="OPTIONS")
        self.assertEqual(403, raised.exception.code)
        self.assertIsNone(raised.exception.headers["Access-Control-Allow-Origin"])

    def test_preflight_for_a_get_only_path_is_not_found(self):
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.open("/api/status", {"Origin": self.ORIGIN}, method="OPTIONS")
        self.assertEqual(404, raised.exception.code)

    def test_declared_origin_may_post_and_undeclared_origin_may_not(self):
        headers = {"Origin": self.ORIGIN, "Content-Type": "application/json"}
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.open("/api/axiom/trace-demo", headers, body=b'{"preset":"remove_validation"}')
        self.assertEqual(400, raised.exception.code)
        self.assertNotIn("Origin is not allowed", raised.exception.read().decode("utf-8"))
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.open("/api/axiom/trace-demo",
                      {"Origin": "https://attacker.example", "Content-Type": "application/json"},
                      body=b'{"preset":"remove_validation"}')
        self.assertEqual(403, raised.exception.code)
        self.assertIn("Origin is not allowed", raised.exception.read().decode("utf-8"))

    def test_config_javascript_is_served_for_same_origin_use(self):
        with self.open("/config.js") as response:
            self.assertEqual(200, response.status)
            self.assertIn("javascript", response.headers["Content-Type"])
            self.assertIn("window.AXIOM_API_BASE", response.read().decode("utf-8"))

    def test_origin_normalization_accepts_only_bare_http_origins(self):
        self.assertEqual("https://app.example", _normalize_origin(" HTTPS://App.Example/ "))
        self.assertEqual("https://app.example", _normalize_origin("https://app.example:443"))
        self.assertEqual("http://app.example", _normalize_origin("http://app.example:80"))
        self.assertEqual("http://app.example:8080", _normalize_origin("http://app.example:8080"))
        for value in (None, "", "null", "app.example", "ftp://app.example",
                      "https://app.example/path", "https://app.example?q=1",
                      "https://app.example#fragment", "https://user:pass@app.example",
                      "https://app.example:bad"):
            with self.subTest(value=value):
                self.assertEqual("", _normalize_origin(value))


if __name__ == "__main__":
    unittest.main()
