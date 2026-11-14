"""Run the actual dashboard JavaScript when Node is available."""
import shutil
import subprocess
import unittest
from pathlib import Path


class DashboardModelTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node required for dashboard JavaScript tests")
    def test_model_selector_and_submitted_payloads(self):
        script = Path(__file__).parent / "js/dashboard_models.cjs"
        result = subprocess.run(["node", "--test", str(script)], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

