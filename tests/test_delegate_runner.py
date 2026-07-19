import subprocess
import tempfile
import os
import time
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "scripts" / "check-report"
EXTRACT = ROOT / "scripts" / "extract-report"
RUNNER = ROOT / "scripts" / "run-delegate"


class DelegateRunnerTests(unittest.TestCase):
    def test_complete_report_is_not_truncated(self):
        report = """\
DELEGATE_REPORT:
  STATUS: COMPLETE
  SUMMARY: completed
  FILES_CHANGED: [src/example.py]
  TEST_FIRST: PROVEN
  COMMAND_EVIDENCE:
    - PHASE: RED
      COMMAND: test red
      EXIT_CODE: 1
      OUTPUT_EXCERPT: intended assertion
    - PHASE: GREEN
      COMMAND: test green
      EXIT_CODE: 0
      OUTPUT_EXCERPT: passed
  STOP_CONDITIONS_HIT: []
  REMAINING_RISKS: []
""" + "".join(f"  # retained report line {line}\n" for line in range(100))
        raw_text = "tool prelude\nROUTER_REPORT_BEGIN\n" + report + "ROUTER_REPORT_END\n"
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "raw.log"
            output = Path(tmp) / "report.yaml"
            raw.write_text(raw_text)
            result = subprocess.run(
                [EXTRACT, raw, output], text=True, capture_output=True
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("retained report line 99", result.stdout)
            self.assertEqual(raw.read_text(), raw_text)

    def test_review_and_packet_review_items_require_complete_schemas(self):
        review = """\
REVIEW_REPORT:
  VERDICT: REVISE
  FINDINGS:
    - SEVERITY: HIGH
      FILE: src/example.py
      LINE: 10
      ISSUE: broken behavior
      REQUIRED_CHANGE: fix it
  VERIFICATION: [test:1]
  SCOPE_VIOLATIONS: []
  REMAINING_RISKS: []
"""
        packet = """\
PACKET_REVIEW:
  VERDICT: BLOCK
  REVIEWED_UNCERTAINTY: ARCHITECTURE
  PACKET_CHECK: PASS
  BLOCKERS:
    - TYPE: ARCHITECTURE
      ISSUE: unclear boundary
      REQUIRED_EVIDENCE: dependency anchor
  REMAINING_RISKS: []
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.yaml"
            for complete, missing, label in (
                (review, "      REQUIRED_CHANGE: fix it\n", "REQUIRED_CHANGE"),
                (packet, "      REQUIRED_EVIDENCE: dependency anchor\n", "REQUIRED_EVIDENCE"),
            ):
                path.write_text(complete)
                result = subprocess.run([CHECK, path], text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                path.write_text(complete.replace(missing, ""))
                result = subprocess.run([CHECK, path], text=True, capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(label, result.stderr)

    def test_incomplete_and_missing_reports_fail_explicitly(self):
        with tempfile.TemporaryDirectory() as tmp:
            incomplete = Path(tmp) / "incomplete.yaml"
            incomplete.write_text("DELEGATE_REPORT:\n  STATUS: COMPLETE\n")
            result = subprocess.run(
                [CHECK, incomplete], text=True, capture_output=True
            )
            self.assertNotEqual(result.returncode, 0)

            raw = Path(tmp) / "raw.log"
            output = Path(tmp) / "report.yaml"
            raw.write_text("tool exited without a report\n")
            result = subprocess.run(
                [EXTRACT, raw, output], text=True, capture_output=True
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("STATUS: FAILED", output.read_text())
            self.assertIn("MISSING_STRUCTURED_REPORT", output.read_text())

            raw.write_text(
                "ROUTER_REPORT_END\nROUTER_REPORT_BEGIN\n"
                "DELEGATE_REPORT:\n"
                "  STATUS: COMPLETE\n"
                "  SUMMARY: invalid marker order\n"
                "  FILES_CHANGED: []\n"
                "  TEST_FIRST: NOT_APPLICABLE\n"
                "  COMMAND_EVIDENCE: []\n"
                "  STOP_CONDITIONS_HIT: []\n"
                "  REMAINING_RISKS: []\n"
            )
            result = subprocess.run(
                [EXTRACT, raw, output], text=True, capture_output=True
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("INVALID_STRUCTURED_REPORT", output.read_text())

    def test_timeout_terminates_complete_process_group(self):
        fake = """#!/usr/bin/env python3
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

signal.signal(signal.SIGTERM, signal.SIG_IGN)
child = subprocess.Popen([
    sys.executable,
    "-c",
    "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)",
])
Path(os.environ["CHILD_PID_FILE"]).write_text(str(child.pid))
print("delegate started", flush=True)
while True:
    time.sleep(1)
"""
        for tool, executable in (("cursor", "cursor-agent"), ("pi", "pi")):
            with self.subTest(tool=tool), tempfile.TemporaryDirectory() as tmp:
                tmp = Path(tmp)
                bin_dir = tmp / "bin"
                bin_dir.mkdir()
                command = bin_dir / executable
                command.write_text(fake)
                command.chmod(0o755)
                prompt = tmp / "prompt.txt"
                prompt.write_text("bounded task")
                raw = tmp / "raw.log"
                report = tmp / "report.yaml"
                child_pid = tmp / "child.pid"
                env = os.environ.copy()
                env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
                env["CHILD_PID_FILE"] = str(child_pid)

                started = time.monotonic()
                result = subprocess.run(
                    [
                        RUNNER,
                        "--tool",
                        tool,
                        "--model",
                        "test-model",
                        "--prompt",
                        prompt,
                        "--raw-log",
                        raw,
                        "--report",
                        report,
                        "--timeout-seconds",
                        "0.3",
                        "--term-grace-seconds",
                        "0.2",
                    ],
                    text=True,
                    capture_output=True,
                    env=env,
                )
                self.assertEqual(result.returncode, 124, result.stdout + result.stderr)
                self.assertLess(time.monotonic() - started, 3)
                self.assertIn("TIMEOUT", report.read_text())
                self.assertIn("delegate started", raw.read_text())

                pid = child_pid.read_text()
                status = subprocess.run(
                    ["ps", "-p", pid, "-o", "stat="], text=True, capture_output=True
                )
                self.assertTrue(
                    status.returncode != 0 or status.stdout.strip().startswith("Z"),
                    f"child process still running: {status.stdout}",
                )

    def test_runner_uses_verified_cli_flags_and_complete_prompt(self):
        fake = """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

Path(os.environ["ARGS_FILE"]).write_text(json.dumps(sys.argv[1:]))
print("ROUTER_REPORT_BEGIN")
print("DELEGATE_REPORT:")
print("  STATUS: COMPLETE")
print("  SUMMARY: complete")
print("  FILES_CHANGED: []")
print("  TEST_FIRST: NOT_APPLICABLE")
print("  COMMAND_EVIDENCE: []")
print("  STOP_CONDITIONS_HIT: []")
print("  REMAINING_RISKS: []")
print("ROUTER_REPORT_END")
"""
        for tool, executable, expected_prefix in (
            ("cursor", "cursor-agent", ["-p", "-f", "--trust", "--model", "test-model"]),
            (
                "pi",
                "pi",
                [
                    "-p",
                    "--model",
                    "test-model",
                    "--no-session",
                    "--no-context-files",
                    "--no-skills",
                ],
            ),
        ):
            with self.subTest(tool=tool), tempfile.TemporaryDirectory() as tmp:
                tmp = Path(tmp)
                bin_dir = tmp / "bin"
                bin_dir.mkdir()
                command = bin_dir / executable
                command.write_text(fake)
                command.chmod(0o755)
                prompt = tmp / "prompt.txt"
                prompt.write_text("FULL PACKET\nAllowed files: src/example.py\n")
                raw = tmp / "raw.log"
                report = tmp / "report.yaml"
                args_file = tmp / "args.json"
                env = os.environ.copy()
                env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
                env["ARGS_FILE"] = str(args_file)
                result = subprocess.run(
                    [
                        RUNNER,
                        "--tool",
                        tool,
                        "--model",
                        "test-model",
                        "--prompt",
                        prompt,
                        "--raw-log",
                        raw,
                        "--report",
                        report,
                    ],
                    text=True,
                    capture_output=True,
                    env=env,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                actual = json.loads(args_file.read_text())
                self.assertEqual(actual[: len(expected_prefix)], expected_prefix)
                self.assertEqual(actual[-1], prompt.read_text())

    def test_adapter_contract_defines_initial_resume_and_cross_tool_payloads(self):
        cursor = (ROOT / "skills" / "cursor-delegate" / "SKILL.md").read_text()
        router = (ROOT / "skills" / "model-router" / "SKILL.md").read_text()
        for phrase in (
            "Initial dispatch",
            "full READY packet",
            "Same-session Cursor resume",
            "findings and immutable constraints",
            "Cross-tool revision",
        ):
            self.assertIn(phrase, cursor + router)
        self.assertIn("does not resend the full packet", cursor + router)


if __name__ == "__main__":
    unittest.main()
