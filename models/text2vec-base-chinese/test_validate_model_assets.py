import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import validate_model_assets as validator


class ValidateModelAssetsTest(unittest.TestCase):
    def run_validator(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(ROOT / "validate_model_assets.py"), *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_vocab_count_uses_lf_only(self) -> None:
        self.assertEqual(validator.vocab_lines("a\nb\u2028c\n"), ["a", "b\u2028c"])

    def test_json_report_is_successful_with_license_warning(self) -> None:
        result = self.run_validator("--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["ok"])
        self.assertIn("missing LICENSE file for commercial usage review", report["warnings"])

    def test_strict_mode_promotes_warning_to_failure(self) -> None:
        result = self.run_validator("--strict")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("strict: missing LICENSE file for commercial usage review", result.stdout)


if __name__ == "__main__":
    unittest.main()
