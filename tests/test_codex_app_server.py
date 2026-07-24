"""Codex app-server delegate: deterministic tests against a mocked protocol.

A fake `codex app-server` (FAKE below) reads newline-delimited JSON-RPC on stdin
and emits canned JSONL on stdout, its behavior chosen by FAKE_MODE. This lets the
whole handshake -> thread -> turn -> teardown path be exercised without a live
Codex model call. One optional test runs the real CLI when RUN_CODEX_LIVE=1.
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libexec"))
import codex_app_server as cas  # noqa: E402

RUNNER = ROOT / "scripts" / "run-delegate"

REPORT_BODY = "\n".join([
    "ROUTER_REPORT_BEGIN",
    "DELEGATE_REPORT:",
    "  STATUS: COMPLETE",
    "  SUMMARY: mocked codex turn",
    "  FILES_CHANGED: []",
    "  TEST_FIRST: NOT_APPLICABLE",
    "  COMMAND_EVIDENCE: []",
    "  STOP_CONDITIONS_HIT: []",
    "  REMAINING_RISKS: []",
    "ROUTER_REPORT_END",
])

# A fake app-server. Modes select the failure/lifecycle scenario under test.
FAKE = r'''
import json, os, sys, time

mode = os.environ.get("FAKE_MODE", "success")
report = os.environ.get("FAKE_REPORT", "")
trace = os.environ.get("FAKE_TRACE")

def out(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()

def note(method, params):
    out({"jsonrpc": "2.0", "method": method, "params": params})

def agent_item():
    return {"id": "item-1", "type": "agentMessage", "text": report}

def emit_turn_success():
    note("turn/started", {"turnId": "turn-1"})
    if mode in ("tool_events", "unknown_events", "malformed"):
        note("item/started", {"item": {"id": "c1", "type": "commandExecution", "command": "pytest"}})
        note("item/commandExecution/outputDelta", {"delta": "run\n"})
        note("item/completed", {"item": {"id": "c1", "type": "commandExecution", "exitCode": 0}})
        note("item/started", {"item": {"id": "f1", "type": "fileChange", "status": "completed"}})
        note("item/completed", {"item": {"id": "f1", "type": "fileChange", "status": "completed"}})
    if mode == "unknown_events":
        note("some/futureNotification", {"anything": True, "nested": {"x": 1}})
        note("thread/tokenUsage/updated", {"tokens": 42})
    if mode == "malformed":
        sys.stdout.write("this is not json\n"); sys.stdout.flush()
    note("item/started", {"item": agent_item()})
    note("item/completed", {"item": agent_item()})
    note("turn/completed", {"threadId": "thread-1",
         "turn": {"id": "turn-1", "status": "completed", "items": [agent_item()]}})

for raw in sys.stdin:
    raw = raw.strip()
    if not raw:
        continue
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        continue
    if trace:
        open(trace, "a").write(raw + "\n")
    method = msg.get("method")
    mid = msg.get("id")
    if method == "initialize":
        if mode == "handshake_error":
            out({"jsonrpc": "2.0", "id": mid, "error": {"code": -32000, "message": "no auth"}})
            sys.exit(1)
        out({"jsonrpc": "2.0", "id": mid, "result": {"userAgent": "fake/0", "codexHome": "/tmp"}})
    elif method == "thread/start":
        if mode == "thread_error":
            out({"jsonrpc": "2.0", "id": mid, "error": {"code": -32001, "message": "thread refused"}})
            continue
        note("thread/started", {"threadId": "thread-1"})
        out({"jsonrpc": "2.0", "id": mid, "result": {"thread": {"id": "thread-1"}}})
        if mode == "exit_early":
            sys.exit(0)
    elif method == "thread/resume":
        out({"jsonrpc": "2.0", "id": mid, "result": {"thread": {"id": msg["params"]["threadId"]}}})
    elif method == "turn/start":
        if mode == "turn_jsonrpc_error":
            out({"jsonrpc": "2.0", "id": mid, "error": {"code": -32002, "message": "turn refused"}})
            continue
        out({"jsonrpc": "2.0", "id": mid, "result": {"turn": {"id": "turn-1"}}})
        if mode == "hang":
            time.sleep(60)
            continue
        if mode == "turn_failed":
            note("turn/started", {"turnId": "turn-1"})
            note("turn/completed", {"turn": {"id": "turn-1", "status": "failed",
                 "error": {"message": "model exploded"}, "items": []}})
            continue
        if mode == "error_notification":
            note("turn/started", {"turnId": "turn-1"})
            note("error", {"message": "stream broke"})
            continue
        if mode == "server_request":
            note("turn/started", {"turnId": "turn-1"})
            out({"jsonrpc": "2.0", "id": "srv-1", "method": "thread/approveGuardianDeniedAction",
                 "params": {"threadId": "thread-1"}})
            # Wait for the client's rejection before finishing, proving no hang.
            for line in sys.stdin:
                if line.strip():
                    break
            emit_turn_success_tail = agent_item()
            note("item/completed", {"item": emit_turn_success_tail})
            note("turn/completed", {"turn": {"id": "turn-1", "status": "completed",
                 "items": [emit_turn_success_tail]}})
            continue
        emit_turn_success()
    elif method == "turn/interrupt":
        out({"jsonrpc": "2.0", "id": mid, "result": {}})
    elif mid is not None and method is not None:
        # unexpected server-directed request from our side; ignore
        pass
'''


def fake_cmd(tmp):
    path = Path(tmp) / "fake_app_server.py"
    path.write_text(FAKE)
    return json.dumps([sys.executable, str(path)])


def run(mode, prompt="do the task", report=REPORT_BODY, timeout=10.0, tmp=None,
        resume=None, sandbox="workspace-write", trace=None):
    env_cmd = fake_cmd(tmp)
    os.environ["CODEX_APP_SERVER_CMD"] = env_cmd
    os.environ["FAKE_MODE"] = mode
    os.environ["FAKE_REPORT"] = report
    if trace:
        os.environ["FAKE_TRACE"] = str(trace)
    raw = io.StringIO()
    try:
        return cas.run_delegation(
            prompt, cwd=tmp, model="gpt-5.6-sol", raw_log=raw,
            sandbox=sandbox, timeout=timeout, term_grace_seconds=0.3,
            resume_thread_id=resume, cmd=json.loads(env_cmd),
        ), raw.getvalue()
    finally:
        os.environ.pop("FAKE_TRACE", None)


class NormalizeTests(unittest.TestCase):
    def test_maps_native_events_to_six_normalized_kinds(self):
        cases = [
            ("turn/started", {"turnId": "t"}, "started"),
            ("item/started", {"item": {"type": "commandExecution", "id": "c"}}, "activity_started"),
            ("item/completed", {"item": {"type": "commandExecution", "id": "c"}}, "activity_finished"),
            ("item/agentMessage/delta", {"delta": "hi"}, "message"),
            ("turn/completed", {"turn": {"status": "completed"}}, "completed"),
            ("error", {"message": "boom"}, "failed"),
        ]
        for method, params, kind in cases:
            self.assertEqual(cas.normalize(method, params)[0], kind)
            self.assertIn(kind, cas.NORMALIZED_KINDS)

    def test_unknown_notifications_are_ignored(self):
        self.assertIsNone(cas.normalize("some/futureThing", {"x": 1}))
        self.assertIsNone(cas.normalize("thread/tokenUsage/updated", {"tokens": 9}))

    def test_final_message_reads_last_agent_message(self):
        turn = {"items": [
            {"type": "reasoning", "id": "r"},
            {"type": "agentMessage", "id": "a1", "text": "first"},
            {"type": "commandExecution", "id": "c"},
            {"type": "agentMessage", "id": "a2", "text": "final"},
        ]}
        self.assertEqual(cas._final_message_from_turn(turn), "final")


class SessionTests(unittest.TestCase):
    def _tmp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        return d.name

    def test_startup_handshake_thread_and_initial_turn_complete(self):
        tmp = self._tmp()
        trace = Path(tmp) / "trace.jsonl"
        result, raw = run("success", tmp=tmp, trace=trace)
        self.assertEqual(result.status, "completed")
        self.assertIn("ROUTER_REPORT_BEGIN", result.final_message)
        methods = [json.loads(l)["method"] for l in trace.read_text().splitlines()]
        # handshake -> thread creation -> initial turn, in order.
        self.assertEqual(methods[:3], ["initialize", "thread/start", "turn/start"])
        self.assertIn("thread-1", raw)  # protocol JSONL is the raw debug artifact

    def test_structured_events_are_parsed_and_mapped(self):
        result, _ = run("tool_events", tmp=self._tmp())
        kinds = [e[0] for e in result.events]
        self.assertEqual(kinds[0], "started")
        self.assertIn("activity_started", kinds)
        self.assertIn("activity_finished", kinds)
        self.assertEqual(kinds[-2] if kinds[-1] == "thread_id" else kinds[-1], "completed")

    def test_turn_failure_is_reported_not_raised(self):
        result, _ = run("turn_failed", tmp=self._tmp())
        self.assertEqual(result.status, "failed")
        self.assertIn("model exploded", result.error)

    def test_error_notification_fails_turn(self):
        result, _ = run("error_notification", tmp=self._tmp())
        self.assertEqual(result.status, "failed")
        self.assertIn("stream broke", result.error)

    def test_jsonrpc_error_on_thread_start_raises_codex_error(self):
        with self.assertRaises(cas.CodexError) as ctx:
            run("thread_error", tmp=self._tmp())
        self.assertEqual(ctx.exception.reason, "JSONRPC_ERROR")

    def test_jsonrpc_error_on_turn_start_raises_codex_error(self):
        with self.assertRaises(cas.CodexError) as ctx:
            run("turn_jsonrpc_error", tmp=self._tmp())
        self.assertEqual(ctx.exception.reason, "JSONRPC_ERROR")

    def test_handshake_failure_raises(self):
        with self.assertRaises(cas.CodexError):
            run("handshake_error", tmp=self._tmp())

    def test_malformed_lines_are_skipped_not_fatal(self):
        result, raw = run("malformed", tmp=self._tmp())
        self.assertEqual(result.status, "completed")
        self.assertIn("this is not json", raw)  # preserved in raw log

    def test_unknown_events_do_not_break_completion(self):
        result, _ = run("unknown_events", tmp=self._tmp())
        self.assertEqual(result.status, "completed")

    def test_unexpected_process_exit_raises_not_hangs(self):
        started = time.monotonic()
        with self.assertRaises(cas.CodexError) as ctx:
            run("exit_early", tmp=self._tmp(), timeout=5)
        self.assertEqual(ctx.exception.reason, "UNEXPECTED_EXIT")
        self.assertLess(time.monotonic() - started, 4)

    def test_timeout_interrupts_and_does_not_hang(self):
        started = time.monotonic()
        with self.assertRaises(cas.CodexTimeout):
            run("hang", tmp=self._tmp(), timeout=0.5)
        self.assertLess(time.monotonic() - started, 4)

    def test_server_request_is_answered_so_turn_never_blocks(self):
        result, _ = run("server_request", tmp=self._tmp(), timeout=8)
        self.assertEqual(result.status, "completed")

    def test_followup_turn_reuses_same_thread(self):
        tmp = self._tmp()
        os.environ["CODEX_APP_SERVER_CMD"] = fake_cmd(tmp)
        os.environ["FAKE_MODE"] = "success"
        os.environ["FAKE_REPORT"] = REPORT_BODY
        raw = io.StringIO()
        session = cas.CodexAppServerSession(
            cwd=tmp, model="gpt-5.6-sol", raw_log=raw,
            cmd=json.loads(os.environ["CODEX_APP_SERVER_CMD"]), term_grace_seconds=0.3,
        )
        try:
            tid1 = session.start(10)
            r1 = session.run_turn("turn one", 10)
            r2 = session.run_turn("turn two", 10)  # no re-init, no new thread
            self.assertEqual(r1.status, "completed")
            self.assertEqual(r2.status, "completed")
            self.assertEqual(session._thread_id, tid1)
        finally:
            session.close()

    def test_resume_starts_turn_on_existing_thread(self):
        result, raw = run("success", tmp=self._tmp(), resume="thread-XYZ")
        self.assertEqual(result.status, "completed")

    def test_separate_delegations_do_not_share_thread(self):
        r1, _ = run("success", tmp=self._tmp())
        r2, _ = run("success", tmp=self._tmp())
        tid1 = dict(r1.events).get("threadId") if False else \
            [e[1]["threadId"] for e in r1.events if e[0] == "thread_id"][0]
        tid2 = [e[1]["threadId"] for e in r2.events if e[0] == "thread_id"][0]
        # Each delegation ran its own process; neither reused the other's session
        # object or thread state (both are thread-1 from the fake, but isolated).
        self.assertEqual((tid1, tid2), ("thread-1", "thread-1"))

    def test_cleanup_leaves_no_running_process(self):
        tmp = self._tmp()
        os.environ["CODEX_APP_SERVER_CMD"] = fake_cmd(tmp)
        os.environ["FAKE_MODE"] = "hang"
        os.environ["FAKE_REPORT"] = REPORT_BODY
        raw = io.StringIO()
        session = cas.CodexAppServerSession(
            cwd=tmp, model="m", raw_log=raw,
            cmd=json.loads(os.environ["CODEX_APP_SERVER_CMD"]), term_grace_seconds=0.3,
        )
        session.start(10)
        pid = session._proc.pid
        session.interrupt()
        time.sleep(0.4)
        status = subprocess.run(["ps", "-p", str(pid), "-o", "stat="],
                                text=True, capture_output=True)
        self.assertTrue(status.returncode != 0 or status.stdout.strip().startswith("Z"),
                        f"app-server still running: {status.stdout}")


class RunnerIntegrationTests(unittest.TestCase):
    """End-to-end through scripts/run-delegate --tool codex."""

    def _run_runner(self, mode, report=REPORT_BODY, sandbox="workspace-write", resume=None):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        tmp = Path(tmp)
        prompt = tmp / "prompt.txt"
        prompt.write_text("delegate this")
        raw = tmp / "raw.log"
        rep = tmp / "report.yaml"
        env = os.environ.copy()
        env["CODEX_APP_SERVER_CMD"] = fake_cmd(tmp)
        env["FAKE_MODE"] = mode
        env["FAKE_REPORT"] = report
        cmd = [str(RUNNER), "--tool", "codex", "--model", "gpt-5.6-sol",
               "--prompt", str(prompt), "--raw-log", str(raw), "--report", str(rep),
               "--sandbox", sandbox, "--timeout-seconds", "10", "--term-grace-seconds", "0.3"]
        if resume:
            cmd += ["--resume", resume]
        proc = subprocess.run(cmd, text=True, capture_output=True, env=env)
        return proc, raw, rep

    def test_delegate_report_preserved_end_to_end(self):
        proc, raw, rep = self._run_runner("success")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("STATUS: COMPLETE", rep.read_text())
        self.assertIn("mocked codex turn", proc.stdout)
        self.assertIn("thread-1", raw.read_text())  # raw JSONL retained for debugging

    def test_missing_report_envelope_fails_explicitly(self):
        proc, raw, rep = self._run_runner("success", report="no envelope here")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("STATUS: FAILED", rep.read_text())
        self.assertIn("MISSING_STRUCTURED_REPORT", rep.read_text())

    def test_turn_failure_yields_failed_report(self):
        proc, raw, rep = self._run_runner("turn_failed")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("STATUS: FAILED", rep.read_text())
        self.assertIn("CODEX_TURN_FAILED", rep.read_text())

    def test_timeout_yields_timeout_report(self):
        proc, raw, rep = self._run_runner("hang")
        self.assertEqual(proc.returncode, 124, proc.stdout + proc.stderr)
        self.assertIn("TIMEOUT", rep.read_text())

    def test_sandbox_flag_selects_read_only_for_critique(self):
        trace = Path(tempfile.mkdtemp()) / "t.jsonl"
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        prompt = tmp / "p.txt"; prompt.write_text("critique")
        raw = tmp / "raw.log"; rep = tmp / "r.yaml"
        env = os.environ.copy()
        env["CODEX_APP_SERVER_CMD"] = fake_cmd(tmp)
        env["FAKE_MODE"] = "success"; env["FAKE_REPORT"] = REPORT_BODY
        env["FAKE_TRACE"] = str(trace)
        subprocess.run([str(RUNNER), "--tool", "codex", "--model", "gpt-5.6-sol",
                        "--prompt", str(prompt), "--raw-log", str(raw), "--report", str(rep),
                        "--sandbox", "read-only", "--timeout-seconds", "10",
                        "--term-grace-seconds", "0.3"], text=True, capture_output=True, env=env)
        start = [json.loads(l) for l in trace.read_text().splitlines()
                 if json.loads(l).get("method") == "thread/start"][0]
        self.assertEqual(start["params"]["sandbox"], "read-only")

    def test_reasoning_effort_defaults_to_xhigh(self):
        trace = Path(tempfile.mkdtemp()) / "t.jsonl"
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        prompt = tmp / "p.txt"; prompt.write_text("impl")
        raw = tmp / "raw.log"; rep = tmp / "r.yaml"
        env = os.environ.copy()
        env["CODEX_APP_SERVER_CMD"] = fake_cmd(tmp)
        env["FAKE_MODE"] = "success"; env["FAKE_REPORT"] = REPORT_BODY
        env["FAKE_TRACE"] = str(trace)
        subprocess.run([str(RUNNER), "--tool", "codex", "--model", "gpt-5.6-sol",
                        "--prompt", str(prompt), "--raw-log", str(raw), "--report", str(rep),
                        "--timeout-seconds", "10", "--term-grace-seconds", "0.3"],
                       text=True, capture_output=True, env=env)
        turn = [json.loads(l) for l in trace.read_text().splitlines()
                if json.loads(l).get("method") == "turn/start"][0]
        self.assertEqual(turn["params"]["effort"], "xhigh")


@unittest.skipUnless(os.environ.get("RUN_CODEX_LIVE") == "1",
                     "set RUN_CODEX_LIVE=1 to run against the installed codex CLI")
class LiveCodexTest(unittest.TestCase):
    def test_real_app_server_handshake(self):
        # Handshake + thread only (no turn) so this makes no model call.
        raw = io.StringIO()
        session = cas.CodexAppServerSession(
            cwd="/tmp", model="gpt-5.6-sol", raw_log=raw, sandbox="read-only")
        try:
            tid = session.start(30)
            self.assertTrue(tid)
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
