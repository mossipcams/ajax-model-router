import subprocess
import tempfile
import os
import signal
import time
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "scripts" / "check-report"
EXTRACT = ROOT / "scripts" / "extract-report"
RUNNER = ROOT / "scripts" / "run-delegate"

from libexec.delegate_events import normalize_record, parse_jsonl_line


class DelegateRunnerTests(unittest.TestCase):
    def test_native_event_lines_parse_and_normalize(self):
        cases = (
            ("pi", {"type": "agent_start"}, "started"),
            ("pi", {"type": "tool_execution_start", "toolName": "bash"}, "activity/tool started"),
            ("pi", {"type": "tool_execution_end", "toolName": "bash"}, "activity/tool finished"),
            ("pi", {"type": "message_update", "message": {"role": "assistant", "content": [{"type": "text", "text": "progress"}]}}, "message/progress"),
            ("pi", {"type": "agent_settled"}, "completed"),
            ("cursor", {"type": "system", "subtype": "init", "session_id": "chat"}, "started"),
            ("cursor", {"type": "tool_call", "subtype": "started", "tool_call_id": "t1"}, "activity/tool started"),
            ("cursor", {"type": "tool_call", "subtype": "completed", "tool_call_id": "t1"}, "activity/tool finished"),
            ("cursor", {"type": "assistant", "message": {"content": [{"type": "text", "text": "progress"}]}}, "message/progress"),
            ("cursor", {"type": "result", "is_error": False, "result": "done"}, "completed"),
            ("cursor", {"type": "result", "is_error": True, "error": "boom"}, "failed"),
        )
        for source, record, expected in cases:
            with self.subTest(source=source, record=record):
                event = normalize_record(source, record)
                self.assertIsNotNone(event)
                self.assertEqual(event.kind, expected)

    def test_native_event_parser_keeps_report_text_and_tolerates_bad_lines(self):
        report = "ROUTER_REPORT_BEGIN\nDELEGATE_REPORT:\nROUTER_REPORT_END"
        line = json.dumps({
            "type": "message_end",
            "message": {"role": "assistant", "content": [{"type": "text", "text": report}]},
        })
        event = normalize_record("pi", parse_jsonl_line(line))
        self.assertEqual(event.report_text, report)
        self.assertIsNone(parse_jsonl_line("not json"))
        self.assertIsNone(normalize_record("pi", {"type": "future_event", "value": 1}))

    def test_pi_rpc_keeps_one_process_for_follow_up_and_extracts_report(self):
        fake = """#!/usr/bin/env python3
import json
import os
import sys

Path = __import__("pathlib").Path
Path(os.environ["ARGS_FILE"]).write_text(json.dumps(sys.argv[1:]))
commands = []
for line in sys.stdin:
    command = json.loads(line)
    commands.append(command)
    print(json.dumps({"type": "agent_start"}), flush=True)
    print(json.dumps({"type": "response", "command": command["type"], "success": True}), flush=True)
    if command["type"] == "follow_up":
        report = "ROUTER_REPORT_BEGIN\\nDELEGATE_REPORT:\\n  STATUS: COMPLETE\\n  SUMMARY: follow-up complete\\n  FILES_CHANGED: []\\n  TEST_FIRST: NOT_APPLICABLE\\n  COMMAND_EVIDENCE: []\\n  STOP_CONDITIONS_HIT: []\\n  REMAINING_RISKS: []\\nROUTER_REPORT_END"
        print(json.dumps({"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": report}]}}), flush=True)
    print(json.dumps({"type": "agent_settled"}), flush=True)
Path(os.environ["COMMANDS_FILE"]).write_text(json.dumps(commands))
"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            bin_dir = tmp / "bin"
            bin_dir.mkdir()
            command = bin_dir / "pi"
            command.write_text(fake)
            command.chmod(0o755)
            prompt = tmp / "prompt.txt"
            prompt.write_text("initial packet")
            raw = tmp / "raw.log"
            report = tmp / "report.yaml"
            args_file = tmp / "args.json"
            commands_file = tmp / "commands.json"
            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
            env["ARGS_FILE"] = str(args_file)
            env["COMMANDS_FILE"] = str(commands_file)
            result = subprocess.run(
                [
                    RUNNER,
                    "--tool", "pi",
                    "--model", "test-model",
                    "--prompt", prompt,
                    "--raw-log", raw,
                    "--report", report,
                    "--follow-up", "correction",
                ],
                text=True,
                capture_output=True,
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            args = json.loads(args_file.read_text())
            self.assertEqual(args[:4], ["--mode", "rpc", "--model", "test-model"])
            self.assertNotIn("initial packet", args)
            commands = json.loads(commands_file.read_text())
            self.assertEqual([item["type"] for item in commands], ["prompt", "follow_up"])
            self.assertIn('"type": "agent_settled"', raw.read_text())
            self.assertIn("SUMMARY: follow-up complete", report.read_text())

    def test_cursor_stream_json_resume_and_structured_completion(self):
        fake = """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

Path(os.environ["ARGS_FILE"]).write_text(json.dumps(sys.argv[1:]))
report = "ROUTER_REPORT_BEGIN\\nDELEGATE_REPORT:\\n  STATUS: COMPLETE\\n  SUMMARY: cursor complete\\n  FILES_CHANGED: []\\n  TEST_FIRST: NOT_APPLICABLE\\n  COMMAND_EVIDENCE: []\\n  STOP_CONDITIONS_HIT: []\\n  REMAINING_RISKS: []\\nROUTER_REPORT_END"
print(json.dumps({"type": "system", "subtype": "init", "session_id": "chat-1"}), flush=True)
print(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "working"}]}},), flush=True)
print(json.dumps({"type": "result", "is_error": False, "result": report}), flush=True)
"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            bin_dir = tmp / "bin"
            bin_dir.mkdir()
            command = bin_dir / "cursor-agent"
            command.write_text(fake)
            command.chmod(0o755)
            prompt = tmp / "prompt.txt"
            prompt.write_text("packet")
            raw = tmp / "raw.log"
            report = tmp / "report.yaml"
            args_file = tmp / "args.json"
            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
            env["ARGS_FILE"] = str(args_file)
            result = subprocess.run(
                [
                    RUNNER,
                    "--tool", "cursor",
                    "--model", "test-model",
                    "--prompt", prompt,
                    "--raw-log", raw,
                    "--report", report,
                    "--resume", "chat-1",
                ],
                text=True,
                capture_output=True,
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            args = json.loads(args_file.read_text())
            self.assertEqual(
                args,
                [
                    "-p", "-f", "--trust", "--model", "test-model",
                    "--resume", "chat-1", "--output-format", "stream-json",
                    "--stream-partial-output", prompt.read_text(),
                ],
            )
            self.assertIn('"type": "result"', raw.read_text())
            self.assertIn("SUMMARY: cursor complete", report.read_text())

    def test_native_failure_unknown_lines_and_unexpected_exit_are_explicit(self):
        cases = (
            (
                "cursor-agent",
                "cursor",
                "import json,sys; print('malformed'); print(json.dumps({'type':'future_event'})); print(json.dumps({'type':'result','is_error':True,'error':'boom'})); print('stderr detail', file=sys.stderr)",
                "NATIVE_EVENT_FAILED",
            ),
            (
                "pi",
                "pi",
                "import json; print(json.dumps({'type':'agent_start'}), flush=True)",
                "MISSING_TERMINAL_EVENT",
            ),
        )
        for executable, tool, body, expected_reason in cases:
            with self.subTest(tool=tool), tempfile.TemporaryDirectory() as tmp:
                tmp = Path(tmp)
                bin_dir = tmp / "bin"
                bin_dir.mkdir()
                command = bin_dir / executable
                command.write_text(f"#!/usr/bin/env python3\n{body}\n")
                command.chmod(0o755)
                prompt = tmp / "prompt.txt"
                prompt.write_text("packet")
                raw = tmp / "raw.log"
                report = tmp / "report.yaml"
                env = os.environ.copy()
                env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
                result = subprocess.run(
                    [
                        RUNNER, "--tool", tool, "--model", "test-model",
                        "--prompt", prompt, "--raw-log", raw, "--report", report,
                    ],
                    text=True,
                    capture_output=True,
                    env=env,
                )
                self.assertNotEqual(result.returncode, 0)
                contents = report.read_text()
                self.assertIn("STATUS: FAILED", contents)
                self.assertIn(expected_reason, contents)
                if tool == "cursor":
                    self.assertIn("malformed", raw.read_text())
                    self.assertIn("stderr detail", raw.read_text())

    def test_cancellation_terminates_native_process_group(self):
        fake = """#!/usr/bin/env python3
import os
import signal
import time
from pathlib import Path

signal.signal(signal.SIGTERM, signal.SIG_IGN)
Path(os.environ["PID_FILE"]).write_text(str(os.getpid()))
while True:
    time.sleep(1)
"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            bin_dir = tmp / "bin"
            bin_dir.mkdir()
            command = bin_dir / "pi"
            command.write_text(fake)
            command.chmod(0o755)
            prompt = tmp / "prompt.txt"
            prompt.write_text("packet")
            raw = tmp / "raw.log"
            report = tmp / "report.yaml"
            pid_file = tmp / "pid"
            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
            env["PID_FILE"] = str(pid_file)
            process = subprocess.Popen(
                [
                    RUNNER, "--tool", "pi", "--model", "test-model",
                    "--prompt", prompt, "--raw-log", raw, "--report", report,
                    "--timeout-seconds", "10",
                    "--term-grace-seconds", "0.2",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
            for _ in range(50):
                if pid_file.exists():
                    break
                time.sleep(0.02)
            process.send_signal(signal.SIGINT)
            stdout, stderr = process.communicate(timeout=3)
            self.assertEqual(process.returncode, 130, stdout + stderr)
            self.assertIn("CANCELLED", report.read_text())
            child = subprocess.run(
                ["ps", "-p", pid_file.read_text(), "-o", "stat="],
                text=True,
                capture_output=True,
            )
            self.assertTrue(child.returncode != 0 or child.stdout.strip().startswith("Z"))

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
report = "ROUTER_REPORT_BEGIN\\nDELEGATE_REPORT:\\n  STATUS: COMPLETE\\n  SUMMARY: complete\\n  FILES_CHANGED: []\\n  TEST_FIRST: NOT_APPLICABLE\\n  COMMAND_EVIDENCE: []\\n  STOP_CONDITIONS_HIT: []\\n  REMAINING_RISKS: []\\nROUTER_REPORT_END"
if "--mode" in sys.argv:
    for line in sys.stdin:
        print(json.dumps({"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": report}]}}), flush=True)
        print(json.dumps({"type": "agent_settled"}), flush=True)
        break
else:
    print(json.dumps({"type": "system", "subtype": "init"}), flush=True)
    print(json.dumps({"type": "result", "is_error": False, "result": report}), flush=True)
"""
        for tool, executable, expected_prefix in (
            (
                "cursor",
                "cursor-agent",
                ["-p", "-f", "--trust", "--model", "test-model", "--output-format", "stream-json", "--stream-partial-output"],
            ),
            (
                "pi",
                "pi",
                [
                    "--mode",
                    "rpc",
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
                if tool == "cursor":
                    self.assertEqual(actual[-1], prompt.read_text())
                else:
                    self.assertNotIn(prompt.read_text(), actual)

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
