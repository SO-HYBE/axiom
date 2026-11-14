"""Vercel Python Function adapting AXIOM's existing HTTP routes."""
from pathlib import Path
import os
import sys
import tempfile
from urllib.parse import parse_qsl, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from axiom.server import _normalize_host, make_handler  # noqa: E402

_allowed_hosts = {"axiomcombustion.us", "www.axiomcombustion.us"}
for _key in ("VERCEL_URL", "VERCEL_PROJECT_PRODUCTION_URL"):
    _value = os.environ.get(_key, "").strip()
    if _value:
        _allowed_hosts.add(_normalize_host(_value))

_base = make_handler(ROOT, allowed_hosts=_allowed_hosts,
                     record_root=Path(tempfile.gettempdir()) / "axiom-records")


class handler(_base):
    """Restore the API path carried by the Vercel rewrite query parameter."""
    def valid_host(self):
        return _normalize_host(self.headers.get("Host", "")) in _allowed_hosts

    def _restore_path(self):
        parsed = urlsplit(self.path)
        pairs = parse_qsl(parsed.query, keep_blank_values=True)
        route = next((value for key, value in pairs if key == "__axiom_path"), None)
        if route is not None:
            pairs = [(key, value) for key, value in pairs if key != "__axiom_path"]
            self.path = route + ("?" + urlencode(pairs, doseq=True) if pairs else "")

    def do_GET(self):
        self._restore_path()
        return super().do_GET()

    def do_POST(self):
        self._restore_path()
        return super().do_POST()

    def do_OPTIONS(self):
        self._restore_path()
        return super().do_OPTIONS()

    def log_message(self, format, *args):
        return None
