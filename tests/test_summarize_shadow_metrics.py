import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "summarize_shadow_metrics.py"


def _build_passing_record(run_id: str) -> dict:
    return {
        "run_id": run_id,
        "timestamp_utc": "2026-06-02T00:00:00+00:00",
        "schema_valid": True,
        "confidence": "medium",
        "highlights_count": 5,
        "overlap_ratio": 1.0,
        "ordering_changes": 0,
        "empty_result": False,
        "timed_out": False,
        "error": "",
    }


class SummarizeShadowMetricsScriptTests(unittest.TestCase):
    def _write_log(self, path: Path, records: list[dict]) -> None:
        with path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=True))
                handle.write("\n")

    def test_output_json_writes_report_with_expected_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            log_path = temp_path / "shadow.jsonl"
            output_json = temp_path / "report.json"

            self._write_log(log_path, [_build_passing_record("run-1"), _build_passing_record("run-2")])

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--log-path",
                    str(log_path),
                    "--min-records",
                    "2",
                    "--output-json",
                    str(output_json),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0)
            self.assertTrue(output_json.exists())

            report = json.loads(output_json.read_text(encoding="utf-8"))
            self.assertEqual(report["stats"]["total"], 2)
            self.assertTrue(report["gates_passed"])
            self.assertEqual(report["gate_failures"], [])
            self.assertEqual(report["thresholds"]["min_records"], 2)

    def test_github_annotations_printed_on_gate_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            log_path = temp_path / "shadow.jsonl"

            self._write_log(log_path, [_build_passing_record("run-1"), _build_passing_record("run-2")])

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--log-path",
                    str(log_path),
                    "--min-records",
                    "5",
                    "--github-annotations",
                    "--enforce-gates",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("gates=FAIL", result.stdout)
            self.assertIn("gate_failure=records gate failed", result.stdout)
            self.assertIn("::error title=Shadow Metrics Gate::records gate failed", result.stdout)


if __name__ == "__main__":
    unittest.main()
