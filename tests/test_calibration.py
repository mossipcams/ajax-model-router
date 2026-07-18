import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOGGER = ROOT / "scripts" / "router-log"
SUMMARY = ROOT / "scripts" / "router-log-summary"


def row_args(log):
    return [
        LOGGER,
        "--log",
        log,
        "--repository-id",
        "github.com/mossipcams/ajax-model-router",
        "--task-id",
        "task-123",
        "--round",
        "1",
        "--route-rule-id",
        "R-DELEGATE",
        "--task-kind",
        "behavior",
        "--risk-class",
        "HIGH",
        "--action",
        "DELEGATE",
        "--lane",
        "pi-delegate",
        "--model",
        "opencode-go/glm-5.2",
        "--estimated-files",
        "2",
        "--estimated-lines",
        "40",
        "--critique-result",
        "NOT_RUN",
        "--gate-result",
        "ACCEPT",
        "--escalation-destination",
        "NONE",
        "--escalation-reason",
        "NONE",
        "--failure-classification",
        "NONE",
        "--verification-result",
        "PASS",
        "--ci-result",
        "UNKNOWN",
        "--duration-seconds",
        "12.5",
        "--token-usage",
        "UNKNOWN",
    ]


class CalibrationTests(unittest.TestCase):
    def test_v2_log_writer_requires_and_preserves_every_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "log.tsv"
            result = subprocess.run(row_args(log), text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            fields = log.read_text().rstrip("\n").split("\t")
            self.assertEqual(len(fields), 22)
            self.assertEqual(fields[0], "v2")
            self.assertTrue(fields[1].endswith("Z"))
            self.assertEqual(fields[2:5], ["github.com/mossipcams/ajax-model-router", "task-123", "1"])
            self.assertEqual(fields[-1], "UNKNOWN")

            incomplete = row_args(log)
            index = incomplete.index("--token-usage")
            del incomplete[index : index + 2]
            result = subprocess.run(incomplete, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("token-usage", result.stderr)

            malformed = row_args(log)
            reason = malformed.index("--escalation-reason") + 1
            malformed[reason] = "context:\ncorrupt-row"
            result = subprocess.run(malformed, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("tab or newline", result.stderr)

    def test_summary_uses_only_v2_rows_and_separates_quality_signals(self):
        def row(**changes):
            values = {
                "timestamp": "2026-07-17T12:00:00Z",
                "repository": "github.com/mossipcams/ajax-model-router",
                "task": "task",
                "round": "1",
                "rule": "R-DELEGATE",
                "kind": "behavior",
                "risk": "LOW",
                "action": "DELEGATE",
                "lane": "pi-delegate",
                "model": "opencode-go/minimax-m3",
                "files": "1",
                "lines": "10",
                "critique": "NOT_RUN",
                "gate": "NOT_RUN",
                "destination": "NONE",
                "reason": "NONE",
                "failure": "NONE",
                "verification": "PASS",
                "ci": "UNKNOWN",
                "duration": "1",
                "tokens": "UNKNOWN",
            }
            values.update(changes)
            return "\t".join(["v2", *values.values()])

        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "log.tsv"
            rows = ["2026-07-13\tlegacy\tmodel\tGATE\tlane\tmodel\tACCEPT\tNONE"]
            rows.extend(
                row(
                    task=f"cheap-{number}",
                    destination="pi-delegate",
                    reason="verification-failed",
                )
                for number in range(3)
            )
            rows.extend(
                row(
                    task=f"critique-{number}",
                    action="CRITIQUE_PACKET",
                    lane="codex-delegate",
                    model="gpt-5.5",
                    critique="PASS",
                )
                for number in range(20)
            )
            rows.extend(
                row(
                    task=f"glm-{number}",
                    risk="HIGH",
                    model="opencode-go/glm-5.2",
                )
                for number in range(15)
            )
            rows.extend(
                [
                    row(
                        task="gate-1",
                        action="REVIEW_GATE",
                        gate="REVISE",
                        verification="FAIL",
                        ci="FAIL",
                        failure="VERIFICATION_FAILED",
                    ),
                    row(
                        task="gate-2",
                        action="REVIEW_GATE",
                        gate="DISCARD",
                        verification="FAIL",
                        ci="UNKNOWN",
                        failure="ESCAPED_DEFECT",
                    ),
                ]
            )
            rows.extend(
                row(
                    task=f"observation-{number}",
                    rule="NONE",
                    action="OBSERVATION",
                    lane="NONE",
                    model="NONE",
                    verification="UNKNOWN",
                    ci="PASS",
                )
                for number in range(60)
            )
            log.write_text("\n".join(rows) + "\n")
            result = subprocess.run([SUMMARY, log], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("legacy rows excluded from v2 metrics: 1", result.stdout)
            self.assertIn("# procedural gate results", result.stdout)
            self.assertIn("# verification results", result.stdout)
            self.assertIn("# CI results", result.stdout)
            self.assertIn("# escaped defects", result.stdout)
            self.assertIn("TRIPWIRE cheap-escalation", result.stdout)
            self.assertIn("TRIPWIRE critique-saturation", result.stdout)
            self.assertIn("TRIPWIRE minimax-starvation", result.stdout)
            self.assertIn("TRIPWIRE gate-failure", result.stdout)
            self.assertNotIn("TRIPWIRE route-unused", result.stdout)

    def test_workflow_uses_routing_calibration_not_training_claims(self):
        self.assertTrue((ROOT / "CALIBRATION.md").is_file())
        self.assertFalse((ROOT / "TRAINING.md").exists())
        router = (ROOT / "skills" / "model-router" / "SKILL.md").read_text()
        self.assertIn("## Routing Calibration", router)
        self.assertNotIn("## Training", router)
        self.assertNotIn("training data", router)


if __name__ == "__main__":
    unittest.main()
