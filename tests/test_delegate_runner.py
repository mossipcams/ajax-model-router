import json
import os
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "scripts" / "check-report"
EXTRACT = ROOT / "scripts" / "extract-report"
RUNNER = ROOT / "scripts" / "run-delegate"

from libexec.acpx_events import normalize_record, parse_jsonl_line
from libexec.delegate_events import normalize_record as normalize_native_record


REPORT_COMPLETE = (
    "ROUTER_REPORT_BEGIN\n"
    "DELEGATE_REPORT:\n"
    "  STATUS: COMPLETE\n"
    "  CHANGED_FILES: []\n"
    "  VERIFICATION:\n"
    "    - TYPE: other\n"
    "      COMMAND: NONE\n"
    "      RESULT: pass\n"
    "      DETAILS: {detail}\n"
    "  CONCERNS: []\n"
    "ROUTER_REPORT_END"
)


def fake_acpx_script(*, body="", emit_report=True, detail="complete", track_invocations=False):
    report = REPORT_COMPLETE.format(detail=detail)
    tracking = ""
    if track_invocations:
        tracking = """
inv_file = os.environ.get("INVOCATIONS_FILE")
if inv_file:
    from pathlib import Path
    path = Path(inv_file)
    rows = json.loads(path.read_text()) if path.exists() else []
    rows.append(sys.argv[1:])
    path.write_text(json.dumps(rows))
"""
    return f"""#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

Path(os.environ["ARGS_FILE"]).write_text(json.dumps(sys.argv[1:]))
{tracking}
{body}
report = {json.dumps(report)}
if {str(emit_report)}:
    print(json.dumps({{
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {{
            "sessionUpdate": "agent_message_chunk",
            "content": {{"type": "text", "text": report}},
        }},
    }}), flush=True)
print(json.dumps({{"jsonrpc": "2.0", "id": "1", "result": {{"stopReason": "end_turn"}}}}), flush=True)
"""


def install_fake_acpx(tmp, script_body):
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    command = bin_dir / "acpx"
    command.write_text(script_body)
    command.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    args_file = tmp / "args.json"
    env["ARGS_FILE"] = str(args_file)
    return env, args_file


class DelegateRunnerTests(unittest.TestCase):
    def test_acpx_event_lines_parse_and_normalize(self):
        report = REPORT_COMPLETE.format(detail="parsed")
        line = json.dumps({
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": report},
            },
        })
        event = normalize_record(parse_jsonl_line(line))
        self.assertIsNotNone(event)
        self.assertEqual(event.kind, "message/progress")
        self.assertIn("ROUTER_REPORT_BEGIN", event.report_text)

        done = json.dumps({"jsonrpc": "2.0", "id": "1", "result": {"stopReason": "end_turn"}})
        event = normalize_record(parse_jsonl_line(done))
        self.assertEqual(event.kind, "completed")

        err = json.dumps({"jsonrpc": "2.0", "id": "1", "error": {"message": "boom"}})
        event = normalize_record(parse_jsonl_line(err))
        self.assertEqual(event.kind, "failed")

    def test_legacy_native_event_parser_still_available(self):
        line = json.dumps({
            "type": "message_end",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "x"}]},
        })
        self.assertIsNotNone(normalize_native_record("pi", parse_jsonl_line(line)))

    def test_acpx_passes_model_and_profile_for_all_tools(self):
        for tool, profile in (("cursor", "cursor"), ("pi", "pi"), ("codex", "codex")):
            with self.subTest(tool=tool), tempfile.TemporaryDirectory() as tmp:
                tmp = Path(tmp)
                env, args_file = install_fake_acpx(tmp, fake_acpx_script(detail=f"{tool} ok"))
                prompt = tmp / "prompt.txt"
                prompt.write_text("bounded task")
                raw = tmp / "raw.log"
                report = tmp / "report.yaml"
                result = subprocess.run(
                    [
                        RUNNER, "--tool", tool, "--model", "test-model",
                        "--prompt", prompt, "--raw-log", raw, "--report", report,
                    ],
                    text=True,
                    capture_output=True,
                    env=env,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                args = json.loads(args_file.read_text())
                self.assertIn("--model", args)
                self.assertEqual(args[args.index("--model") + 1], "test-model")
                self.assertIn(profile, args)
                self.assertIn("exec", args)
                self.assertIn("--file", args)
                self.assertEqual(args[args.index("--file") + 1], str(prompt))

    def test_pi_follow_up_uses_prompt_chain_and_extracts_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            invocations_file = tmp / "invocations.json"
            invocations_file.write_text("[]")
            env, args_file = install_fake_acpx(
                tmp,
                fake_acpx_script(detail="follow-up complete", track_invocations=True),
            )
            env["INVOCATIONS_FILE"] = str(invocations_file)
            prompt = tmp / "prompt.txt"
            prompt.write_text("initial packet")
            raw = tmp / "raw.log"
            report = tmp / "report.yaml"
            result = subprocess.run(
                [
                    RUNNER, "--tool", "pi", "--model", "test-model",
                    "--prompt", prompt, "--raw-log", raw, "--report", report,
                    "--follow-up", "correction",
                ],
                text=True,
                capture_output=True,
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            invocations = json.loads(invocations_file.read_text())
            self.assertGreaterEqual(len(invocations), 3)
            flat = [item for invocation in invocations for item in invocation]
            self.assertEqual(flat[flat.index("--model") + 1], "test-model")
            self.assertIn("sessions", flat)
            self.assertIn("ensure", flat)
            self.assertEqual(flat.count("prompt"), 2)
            self.assertIn("DETAILS: follow-up complete", report.read_text())

    def test_cursor_resume_uses_acpx_prompt_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            env, args_file = install_fake_acpx(tmp, fake_acpx_script(detail="cursor complete"))
            prompt = tmp / "prompt.txt"
            prompt.write_text("packet")
            raw = tmp / "raw.log"
            report = tmp / "report.yaml"
            result = subprocess.run(
                [
                    RUNNER, "--tool", "cursor", "--model", "test-model",
                    "--prompt", prompt, "--raw-log", raw, "--report", report,
                    "--resume", "chat-1",
                ],
                text=True,
                capture_output=True,
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            args = json.loads(args_file.read_text())
            self.assertEqual(args[args.index("--model") + 1], "test-model")
            self.assertIn("prompt", args)
            self.assertIn("-s", args)
            self.assertEqual(args[args.index("-s") + 1], "chat-1")
            self.assertIn("DETAILS: cursor complete", report.read_text())

    def test_acpx_failure_unknown_lines_and_unexpected_exit_are_explicit(self):
        cases = (
            (
                'print("malformed", flush=True)\n'
                'print(json.dumps({"jsonrpc":"2.0","id":"1","error":{"message":"boom"}}), flush=True)',
                "ACP_EVENT_FAILED",
            ),
            (
                "",
                "MISSING_TERMINAL_EVENT",
            ),
        )
        for body, expected_reason in cases:
            with self.subTest(expected_reason=expected_reason), tempfile.TemporaryDirectory() as tmp:
                tmp = Path(tmp)
                script = fake_acpx_script(body=body, emit_report=(expected_reason != "MISSING_TERMINAL_EVENT"))
                if expected_reason == "MISSING_TERMINAL_EVENT":
                    script = script.replace(
                        'print(json.dumps({"jsonrpc": "2.0", "id": "1", "result": {"stopReason": "end_turn"}}), flush=True)',
                        "",
                    )
                env, _ = install_fake_acpx(tmp, script)
                prompt = tmp / "prompt.txt"
                prompt.write_text("packet")
                raw = tmp / "raw.log"
                report = tmp / "report.yaml"
                result = subprocess.run(
                    [
                        RUNNER, "--tool", "cursor", "--model", "test-model",
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

    def test_cancellation_terminates_acpx_process_group(self):
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
            env, _ = install_fake_acpx(tmp, fake)
            prompt = tmp / "prompt.txt"
            prompt.write_text("packet")
            raw = tmp / "raw.log"
            report = tmp / "report.yaml"
            pid_file = tmp / "pid"
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

    def test_complete_report_is_not_truncated(self):
        report = """\
DELEGATE_REPORT:
  STATUS: COMPLETE
  CHANGED_FILES: [src/example.py]
  VERIFICATION:
    - TYPE: test
      COMMAND: test green
      RESULT: pass
      DETAILS: passed
  CONCERNS: []
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

    def test_obsolete_review_schemas_are_rejected(self):
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
            for body in (review, packet):
                path.write_text(body)
                result = subprocess.run([CHECK, path], text=True, capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("unknown report schema", result.stderr)

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
while True:
    time.sleep(1)
"""
        for tool in ("cursor", "pi", "codex"):
            with self.subTest(tool=tool), tempfile.TemporaryDirectory() as tmp:
                tmp = Path(tmp)
                env, _ = install_fake_acpx(tmp, fake)
                prompt = tmp / "prompt.txt"
                prompt.write_text("bounded task")
                raw = tmp / "raw.log"
                report = tmp / "report.yaml"
                child_pid = tmp / "child.pid"
                env["CHILD_PID_FILE"] = str(child_pid)

                started = time.monotonic()
                result = subprocess.run(
                    [
                        RUNNER, "--tool", tool, "--model", "test-model",
                        "--prompt", prompt, "--raw-log", raw, "--report", report,
                        "--timeout-seconds", "0.3",
                        "--term-grace-seconds", "0.2",
                    ],
                    text=True,
                    capture_output=True,
                    env=env,
                )
                self.assertEqual(result.returncode, 124, result.stdout + result.stderr)
                self.assertLess(time.monotonic() - started, 3)
                self.assertIn("TIMEOUT", report.read_text())

                pid = child_pid.read_text()
                status = subprocess.run(
                    ["ps", "-p", pid, "-o", "stat="], text=True, capture_output=True
                )
                self.assertTrue(
                    status.returncode != 0 or status.stdout.strip().startswith("Z"),
                    f"child process still running: {status.stdout}",
                )

    def test_missing_acpx_is_explicit_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            bin_dir = tmp / "bin"
            bin_dir.mkdir()
            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:/usr/bin:/bin"
            prompt = tmp / "prompt.txt"
            prompt.write_text("packet")
            raw = tmp / "raw.log"
            report = tmp / "report.yaml"
            result = subprocess.run(
                [
                    RUNNER, "--tool", "cursor", "--model", "test-model",
                    "--prompt", prompt, "--raw-log", raw, "--report", report,
                ],
                text=True,
                capture_output=True,
                env=env,
            )
            self.assertEqual(result.returncode, 127)
            self.assertIn("MISSING_TOOL", report.read_text())
            self.assertIn("acpx is unavailable", report.read_text())

    def test_adapter_contract_defines_initial_resume_and_cross_tool_payloads(self):
        cursor = (ROOT / "skills" / "cursor-delegate" / "SKILL.md").read_text()
        router = (ROOT / "skills" / "model-router" / "SKILL.md").read_text()
        for phrase in (
            "Initial dispatch",
            "outcome-based Dispatch prompt",
            "Same-session Cursor resume",
            "immutable constraints",
            "Cross-tool revision",
        ):
            self.assertIn(phrase, cursor + router)
        self.assertIn("Do not resend the\n  full prompt", cursor)


if __name__ == "__main__":
    unittest.main()
