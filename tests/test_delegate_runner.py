import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CHECK = ROOT / "scripts" / "check-report"
EXTRACT = ROOT / "scripts" / "extract-report"
RUNNER = ROOT / "scripts" / "run-delegate"

from libexec.acpx_events import (
    classify_connection_closed,
    is_connection_closed_message,
    normalize_record,
    parse_jsonl_line,
)
from libexec.run_delegate import cursor_agent_path_env, find_real_cursor_agent


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
    def test_connection_closed_helpers(self):
        self.assertTrue(is_connection_closed_message("[acpx] error: ACP connection closed"))
        self.assertFalse(is_connection_closed_message("normal log"))
        self.assertEqual(classify_connection_closed(saw_activity=False), "ACP_CONNECTION_CLOSED_INIT")
        self.assertEqual(classify_connection_closed(saw_activity=True), "ACP_CONNECTION_CLOSED_ACTIVE")

    def test_records_acpx_pid_in_debug_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            env, _ = install_fake_acpx(tmp, fake_acpx_script(detail="pid ok"))
            prompt = tmp / "prompt.txt"
            prompt.write_text("bounded task")
            raw = tmp / "raw.log"
            debug = tmp / "debug.log"
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
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            debug_text = debug.read_text()
            self.assertIn("acpx pid=", debug_text)

    def test_connection_closed_during_init_is_classified(self):
        body = 'import sys\nprint("[acpx] error: ACP connection closed", file=sys.stderr, flush=True)\n'
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            script = fake_acpx_script(body=body, emit_report=False)
            script = script.replace(
                'print(json.dumps({"jsonrpc": "2.0", "id": "1", "result": {"stopReason": "end_turn"}}), flush=True)',
                "",
            )
            env, _ = install_fake_acpx(tmp, script)
            prompt = tmp / "prompt.txt"
            prompt.write_text("packet")
            raw = tmp / "raw.log"
            debug = tmp / "debug.log"
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
            self.assertIn("ACP_CONNECTION_CLOSED_INIT", contents)
            self.assertIn("acpx pid=", debug.read_text())

    def test_connection_closed_during_active_turn_is_classified(self):
        progress = json.dumps({
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": "partial"},
            },
        })
        body = (
            f"print({json.dumps(progress)}, flush=True)\n"
            "import time; time.sleep(0.3)\n"
            'import sys\nprint("[acpx] error: ACP connection closed", file=sys.stderr, flush=True)\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            env, _ = install_fake_acpx(tmp, fake_acpx_script(body=body, emit_report=False))
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
            self.assertIn("ACP_CONNECTION_CLOSED_ACTIVE", report.read_text())

    def test_json_stdout_connection_closed_init_is_classified(self):
        body = (
            'print(json.dumps({"jsonrpc":"2.0","id":"1","error":{"message":"ACP connection closed"}}), flush=True)\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            script = fake_acpx_script(body=body, emit_report=False)
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
            self.assertIn("ACP_CONNECTION_CLOSED_INIT", report.read_text())

    def test_json_stdout_connection_closed_active_is_classified(self):
        progress = json.dumps({
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": "partial"},
            },
        })
        err = json.dumps({
            "jsonrpc": "2.0",
            "id": "1",
            "error": {"message": "ACP connection closed"},
        })
        body = (
            f"print({json.dumps(progress)}, flush=True)\n"
            f"print({json.dumps(err)}, flush=True)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            env, _ = install_fake_acpx(tmp, fake_acpx_script(body=body, emit_report=False))
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
            self.assertIn("ACP_CONNECTION_CLOSED_ACTIVE", report.read_text())

    def test_nonzero_acpx_exit_without_terminal_event_is_agent_nonzero_exit(self):
        script = fake_acpx_script(emit_report=False).replace(
            'print(json.dumps({"jsonrpc": "2.0", "id": "1", "result": {"stopReason": "end_turn"}}), flush=True)',
            "import sys\nsys.exit(9)\n",
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
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
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("AGENT_NONZERO_EXIT", report.read_text())
            self.assertIn("status 9", report.read_text())

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

    def test_nested_acp_chunks_have_no_report_until_joined(self):
        report = REPORT_COMPLETE.format(detail="nested fragments")
        mid = report.index("DELEGATE_REPORT") + len("DELEGATE")
        first, second = report[:mid], report[mid:]
        self.assertNotIn("ROUTER_REPORT_END", first)
        self.assertNotIn("ROUTER_REPORT_BEGIN", second)
        events = []
        for chunk in (first, second):
            line = json.dumps({
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "sessionId": "s1",
                    "update": {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": chunk},
                    },
                },
            })
            event = normalize_record(parse_jsonl_line(line))
            self.assertIsNotNone(event)
            self.assertEqual(event.kind, "message/progress")
            self.assertEqual(event.report_text, "")
            events.append(event)
        combined = "".join(event.text for event in events)
        self.assertIn("ROUTER_REPORT_BEGIN", combined)
        self.assertIn("ROUTER_REPORT_END", combined)
        self.assertIn("DELEGATE_REPORT", combined)

    def test_thought_chunks_are_not_joined_into_report_text(self):
        thought = json.dumps({
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "update": {
                    "sessionUpdate": "agent_thought_chunk",
                    "content": {"type": "text", "text": "I will output the exact text."},
                },
            },
        })
        event = normalize_record(parse_jsonl_line(thought))
        self.assertIsNotNone(event)
        self.assertEqual(event.text, "")
        self.assertEqual(event.report_text, "")

    def test_nested_tool_call_string_status_does_not_crash(self):
        started = json.dumps({
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "s1",
                "update": {
                    "sessionUpdate": "tool_call",
                    "toolCallId": "call-1",
                    "status": "pending",
                    "title": "Edit file",
                },
            },
        })
        finished = json.dumps({
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "s1",
                "update": {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": "call-1",
                    "status": "completed",
                },
            },
        })
        event = normalize_record(parse_jsonl_line(started))
        self.assertIsNotNone(event)
        self.assertEqual(event.kind, "activity/tool started")
        event = normalize_record(parse_jsonl_line(finished))
        self.assertIsNotNone(event)
        self.assertEqual(event.kind, "activity/tool finished")

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

    def test_run_delegate_survives_string_status_tool_calls(self):
        records = (
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "sessionId": "s1",
                    "update": {
                        "sessionUpdate": "tool_call",
                        "toolCallId": "call-1",
                        "status": "pending",
                    },
                },
            },
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "sessionId": "s1",
                    "update": {
                        "sessionUpdate": "tool_call_update",
                        "toolCallId": "call-1",
                        "status": "completed",
                    },
                },
            },
        )
        body = "".join(
            f"print({json.dumps(json.dumps(record))}, flush=True)\n" for record in records
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            env, _ = install_fake_acpx(
                tmp, fake_acpx_script(body=body, detail="tool calls ok")
            )
            prompt = tmp / "prompt.txt"
            prompt.write_text("bounded task")
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
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("DETAILS: tool calls ok", report.read_text())

    def test_acpx_extracts_report_from_nested_fragmented_chunks(self):
        report = REPORT_COMPLETE.format(detail="fragmented")
        mid = report.index("DELEGATE_REPORT") + len("DELEGATE")
        first, second = report[:mid], report[mid:]
        self.assertNotIn("ROUTER_REPORT_END", first)
        self.assertNotIn("ROUTER_REPORT_BEGIN", second)
        records = [
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "sessionId": "s1",
                    "update": {
                        "sessionUpdate": "agent_thought_chunk",
                        "content": {"type": "text", "text": "I will output the exact text."},
                    },
                },
            },
        ]
        for chunk in (first, second):
            records.append({
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "sessionId": "s1",
                    "update": {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": chunk},
                    },
                },
            })
        body = "".join(
            f"print({json.dumps(json.dumps(record))}, flush=True)\n" for record in records
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            env, _ = install_fake_acpx(tmp, fake_acpx_script(body=body, emit_report=False))
            prompt = tmp / "prompt.txt"
            prompt.write_text("bounded task")
            raw = tmp / "raw.log"
            output = tmp / "report.yaml"
            result = subprocess.run(
                [
                    RUNNER, "--tool", "cursor", "--model", "test-model",
                    "--prompt", prompt, "--raw-log", raw, "--report", output,
                ],
                text=True,
                capture_output=True,
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("STATUS: COMPLETE", output.read_text())
            self.assertIn("DETAILS: fragmented", output.read_text())

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

    def test_cursor_retriable_error_text_is_acp_failure_not_missing_report(self):
        crash = "\n\nError: RetriableError: [internal] Failed to run step, exceeded max retries"
        body = (
            "print("
            + json.dumps(json.dumps({
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "sessionId": "s1",
                    "update": {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": crash},
                    },
                },
            }))
            + ", flush=True)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            env, _ = install_fake_acpx(tmp, fake_acpx_script(body=body, emit_report=False))
            prompt = tmp / "prompt.txt"
            prompt.write_text("packet")
            raw = tmp / "raw.log"
            report = tmp / "report.yaml"
            result = subprocess.run(
                [
                    RUNNER, "--tool", "cursor", "--model", "test-model",
                    "--prompt", prompt, "--raw-log", raw, "--report", report,
                    "--run-id", "run_fail", "--parent-task-id", "task_fail",
                ],
                text=True,
                capture_output=True,
                env=env,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            contents = report.read_text()
            self.assertIn("STATUS: FAILED", contents)
            self.assertIn("ACP_EVENT_FAILED", contents)
            self.assertNotIn("MISSING_STRUCTURED_REPORT", contents)
            status_lines = [
                json.loads(line)
                for line in result.stdout.splitlines()
                if line.strip().startswith("{") and '"subagent_status"' in line
            ]
            terminal = [row for row in status_lines if row.get("state") in {"completed", "failed"}]
            self.assertTrue(terminal)
            self.assertEqual(terminal[-1]["state"], "failed")

    def test_stop_reason_then_missing_report_emits_failed_not_completed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            env, _ = install_fake_acpx(tmp, fake_acpx_script(emit_report=False))
            prompt = tmp / "prompt.txt"
            prompt.write_text("packet")
            raw = tmp / "raw.log"
            report = tmp / "report.yaml"
            result = subprocess.run(
                [
                    RUNNER, "--tool", "cursor", "--model", "test-model",
                    "--prompt", prompt, "--raw-log", raw, "--report", report,
                    "--run-id", "run_missing", "--parent-task-id", "task_missing",
                ],
                text=True,
                capture_output=True,
                env=env,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("MISSING_STRUCTURED_REPORT", report.read_text())
            status_lines = [
                json.loads(line)
                for line in result.stdout.splitlines()
                if line.strip().startswith("{") and '"subagent_status"' in line
            ]
            terminal = [row for row in status_lines if row.get("state") in {"completed", "failed"}]
            self.assertTrue(terminal)
            self.assertEqual(terminal[-1]["state"], "failed")

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
            debug = tmp / "debug.log"
            self.assertTrue(debug.is_file(), "expected debug.log beside raw.log")
            debug_text = debug.read_text()
            self.assertIn("[ajax-router]", debug_text)
            self.assertIn("MISSING_TOOL", debug_text)
            self.assertIn("acpx is unavailable", debug_text)
            self.assertIn(str(raw), report.read_text())

    def test_acp_failure_writes_debug_log(self):
        body = (
            'print(json.dumps({"jsonrpc":"2.0","id":"1","error":{"message":"boom"}}), flush=True)'
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            env, _ = install_fake_acpx(tmp, fake_acpx_script(body=body, emit_report=False))
            prompt = tmp / "prompt.txt"
            prompt.write_text("packet")
            raw = tmp / "raw.log"
            debug = tmp / "debug.log"
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
            self.assertTrue(debug.is_file(), "expected debug.log beside raw.log")
            debug_text = debug.read_text()
            self.assertIn("[ajax-router]", debug_text)
            self.assertIn("failure reason=ACP_EVENT_FAILED", debug_text)
            self.assertIn("boom", debug_text)
            self.assertIn(f"raw_log={raw}", debug_text)
            self.assertIn("[ajax-router]", result.stderr)

    def test_run_delegate_emits_subagent_status_events(self):
        records = (
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "sessionId": "s1",
                    "update": {
                        "sessionUpdate": "tool_call",
                        "toolCallId": "call-1",
                        "status": "in_progress",
                        "title": "Reading src/chat/MessageList.tsx",
                    },
                },
            },
        )
        body = "".join(
            f"print({json.dumps(json.dumps(record))}, flush=True)\n" for record in records
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            env, _ = install_fake_acpx(
                tmp, fake_acpx_script(body=body, detail="status ok")
            )
            prompt = tmp / "prompt.txt"
            prompt.write_text("bounded task")
            raw = tmp / "raw.log"
            report = tmp / "report.yaml"
            result = subprocess.run(
                [
                    RUNNER, "--tool", "cursor", "--model", "composer-2.5",
                    "--prompt", prompt, "--raw-log", raw, "--report", report,
                    "--run-id", "run_123", "--parent-task-id", "task_456",
                    "--task", "Implement status streaming",
                    "--stall-seconds", "999",
                ],
                text=True,
                capture_output=True,
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            status_lines = [
                json.loads(line)
                for line in result.stdout.splitlines()
                if line.strip().startswith("{") and '"subagent_status"' in line
            ]
            self.assertTrue(status_lines, result.stdout)
            tool_events = [row for row in status_lines if row.get("state") == "tool_call"]
            self.assertTrue(tool_events)
            self.assertEqual(tool_events[0]["runId"], "run_123")
            self.assertEqual(tool_events[0]["parentTaskId"], "task_456")
            self.assertEqual(tool_events[0]["harness"], "cursor")
            self.assertEqual(tool_events[0]["model"], "composer-2.5")
            self.assertIn("MessageList.tsx", tool_events[0]["detail"])
            terminal = [row for row in status_lines if row.get("state") == "completed"]
            self.assertTrue(terminal)
            self.assertIn("DELEGATE_REPORT:", result.stdout)
            self.assertIn("DETAILS: status ok", report.read_text())

    def test_adapter_contract_defines_stateless_exec_payloads(self):
        cursor = (ROOT / "skills" / "cursor-delegate" / "SKILL.md").read_text()
        pi = (ROOT / "skills" / "pi-delegate" / "SKILL.md").read_text()
        codex = (ROOT / "skills" / "codex-delegate" / "SKILL.md").read_text()
        router = (ROOT / "skills" / "model-router" / "SKILL.md").read_text()
        for text in (cursor, pi, codex, router):
            self.assertIn("stateless", text.lower())
            self.assertIn("one-shot", text)
        self.assertIn("outcome-based Dispatch", cursor)
        self.assertIn("Dispatch prompt assembled", router)
        self.assertNotIn("--resume", cursor + pi + codex)
        self.assertNotIn("--follow-up", cursor + pi + codex)
        self.assertNotIn("sessions ensure", cursor + pi + codex)
        self.assertIn("Do not spawn native Task, best-of-n, or other Cursor subagents.", cursor)
        self.assertIn("Never spawn native Cursor Task, best-of-n, or any other subagent.", router)

    def test_cursor_delegate_wires_acp_filter_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            env, shim_dir = cursor_agent_path_env(os.environ.copy())
            if find_real_cursor_agent() is None:
                self.skipTest("cursor-agent not installed")
            self.assertIsNotNone(shim_dir)
            self.assertIn("CURSOR_ACP_FILTER_REAL_AGENT", env)
            self.assertTrue(env["PATH"].startswith(str(shim_dir)))
            script = fake_acpx_script(
                body=(
                    "from pathlib import Path\n"
                    "import json, os\n"
                    'Path(os.environ["ENV_FILE"]).write_text(json.dumps({'
                    'k: os.environ.get(k, "") for k in ("CURSOR_ACP_FILTER_REAL_AGENT",)}))\n'
                ),
                detail="filter env ok",
            )
            bin_dir = tmp / "bin"
            bin_dir.mkdir()
            command = bin_dir / "acpx"
            command.write_text(script)
            command.chmod(0o755)
            env_file = tmp / "child-env.json"
            env = os.environ.copy()
            env, shim_dir = cursor_agent_path_env(env)
            env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
            env["ENV_FILE"] = str(env_file)
            env["ARGS_FILE"] = str(tmp / "args.json")
            prompt = tmp / "prompt.txt"
            prompt.write_text("bounded task")
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
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            captured = json.loads(env_file.read_text())
            self.assertTrue(captured["CURSOR_ACP_FILTER_REAL_AGENT"])

    def test_cursor_ignores_methodnotfound_for_cursor_task_when_turn_completes(self):
        report = REPORT_COMPLETE.format(detail="ignored ext error")
        ext_error = json.dumps({
            "jsonrpc": "2.0",
            "id": "ext",
            "error": {"code": -32601, "message": "Method not found: cursor/task"},
        })
        report_event = json.dumps({
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": report},
            },
        })
        body = (
            f"print({json.dumps(ext_error)}, flush=True)\n"
            f"print({json.dumps(report_event)}, flush=True)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            env, _ = install_fake_acpx(tmp, fake_acpx_script(body=body, emit_report=False))
            prompt = tmp / "prompt.txt"
            prompt.write_text("bounded task")
            raw = tmp / "raw.log"
            report_path = tmp / "report.yaml"
            result = subprocess.run(
                [
                    RUNNER, "--tool", "cursor", "--model", "test-model",
                    "--prompt", prompt, "--raw-log", raw, "--report", report_path,
                ],
                text=True,
                capture_output=True,
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("DETAILS: ignored ext error", report_path.read_text())


if __name__ == "__main__":
    unittest.main()
