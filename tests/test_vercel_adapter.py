import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("axiom_vercel_function", ROOT / "api/index.py")
vercel = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(vercel)


class VercelAdapterTests(unittest.TestCase):
    def test_rewrite_path_is_restored_and_original_query_survives(self):
        request = object.__new__(vercel.handler)
        request.path = "/api/index?__axiom_path=%2Fapi%2Fruns%2Fabc&limit=10&q=flame"
        request._restore_path()
        self.assertEqual("/api/runs/abc?limit=10&q=flame", request.path)

    def test_health_path_is_restored(self):
        request = object.__new__(vercel.handler)
        request.path = "/api/index?__axiom_path=%2Fhealthz"
        request._restore_path()
        self.assertEqual("/healthz", request.path)

    def test_rewrite_metadata_is_removed_from_saved_work_pagination(self):
        request = object.__new__(vercel.handler)
        request.path = "/api/runs?__axiom_path=%2Fapi%2Fruns&limit=10&offset=0&q=flame"
        self.assertEqual({"limit": 10, "offset": 0, "query": "flame"}, request.page_options())

    def test_only_configured_hosts_are_accepted(self):
        request = object.__new__(vercel.handler)
        request.headers = {"Host": "axiomcombustion.us"}
        self.assertTrue(request.valid_host())
        request.headers = {"Host": "untrusted.example"}
        self.assertFalse(request.valid_host())


if __name__ == "__main__":
    unittest.main()
