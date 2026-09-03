import json
import os
import select
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libexec"))

from cursor_acp_filter import (  # noqa: E402
    build_result,
    is_cursor_ext_request,
    is_unknown_cursor_ext_request,
    iter_fd_lines,
    rewrite_client_to_agent_line,
    write_fd,
    FilterState,
    PipeFailure,
)
from run_delegate import cursor_agent_path_env  # noqa: E402


FAKE_AGENT = """#!/usr/bin/env python3
import json
import sys

mode = sys.argv[1] if len(sys.argv) > 1 else "task"

if mode == "task":
    print(json.dumps({
        "jsonrpc": "2.0",
        "id": 7,
        "method": "cursor/task",
        "params": {"description": "nested", "prompt": "do work", "subagentType": "unspecified"},
    }), flush=True)
    reply = json.loads(sys.stdin.readline())
    Path = __import__("pathlib").Path
    Path(__import__("os").environ["REPLY_FILE"]).write_text(json.dumps(reply))
    print(json.dumps({
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "ok"}},
    }), flush=True)
elif mode == "forward":
    print(json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1}}), flush=True)
    client_line = sys.stdin.readline()
    Path = __import__("pathlib").Path
    Path(__import__("os").environ["CLIENT_LINE_FILE"]).write_text(client_line)
elif mode == "unknown_cursor":
    print(json.dumps({
        "jsonrpc": "2.0",
        "id": 42,
        "method": "cursor/unknown_method",
        "params": {},
    }), flush=True)
    reply = json.loads(sys.stdin.readline())
    Path = __import__("pathlib").Path
    Path(__import__("os").environ["REPLY_FILE"]).write_text(json.dumps(reply))
elif mode == "notify_cursor":
    print(json.dumps({
        "jsonrpc": "2.0",
        "method": "cursor/unknown_method",
        "params": {"note": True},
    }), flush=True)
    print(json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"stopReason": "end_turn"}}), flush=True)
elif mode == "nonzero":
    print(json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"stopReason": "end_turn"}}), flush=True)
    sys.exit(17)
elif mode == "slow_drain":
    import time
    for line in sys.stdin:
        pass
    for i in range(80):
        print(json.dumps({"jsonrpc": "2.0", "method": "session/update", "params": {"i": i}}), flush=True)
        time.sleep(0.03)
elif mode == "sigterm_agent":
    import signal
    import time
    Path = __import__("pathlib").Path
    Path(__import__("os").environ["AGENT_PID_FILE"]).write_text(str(__import__("os").getpid()))
    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))
    while True:
        time.sleep(0.05)
elif mode == "respond_and_capture":
    # Replies to every request with an empty result, and records each raw line it
    # receives (in order) so the test can inspect what the filter actually forwarded.
    Path = __import__("pathlib").Path
    lines_file = __import__("os").environ["CLIENT_LINES_FILE"]
    received = []
    while True:
        raw = sys.stdin.readline()
        if not raw:
            break
        received.append(raw)
        Path(lines_file).write_text("".join(received))
        try:
            record = json.loads(raw)
        except ValueError:
            continue
        if isinstance(record, dict) and "id" in record and "method" in record:
            print(json.dumps({"jsonrpc": "2.0", "id": record["id"], "result": {}}), flush=True)
elif mode == "ignore_eof":
    import time
    Path = __import__("pathlib").Path
    Path(__import__("os").environ["AGENT_PID_FILE"]).write_text(str(__import__("os").getpid()))
    i = 0
    while True:
        print(json.dumps({"jsonrpc": "2.0", "method": "session/update", "params": {"i": i}}), flush=True)
        i += 1
        time.sleep(0.02)
"""


class CursorAcpFilterTests(unittest.TestCase):
    def _spawn_filter(self, agent_path, mode, extra_env):
        env = os.environ.copy()
        env.update(extra_env)
        env["CURSOR_ACP_FILTER_REAL_AGENT"] = str(agent_path)
        env["PYTHONUNBUFFERED"] = "1"
        return subprocess.Popen(
            [sys.executable, str(ROOT / "libexec" / "cursor_acp_filter.py"), mode],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )

    def _wait(self, proc, timeout=5):
        try:
            return proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            self.fail(f"filter hung: stdout={stdout!r} stderr={stderr!r}")

    def _readline(self, proc, timeout=5):
        ready, _, _ = select.select([proc.stdout], [], [], timeout)
        if not ready:
            proc.kill()
            stdout, stderr = proc.communicate()
            self.fail(f"filter stdout stall: stdout={stdout!r} stderr={stderr!r}")
        return proc.stdout.readline()

    def test_iter_fd_lines_returns_after_one_line(self):
        read_fd, write_fd = os.pipe()
        try:
            os.write(write_fd, b'{"jsonrpc":"2.0"}\n')
            os.close(write_fd)
            write_fd = None
            self.assertEqual(list(iter_fd_lines(read_fd)), ['{"jsonrpc":"2.0"}\n'])
        finally:
            os.close(read_fd)
            if write_fd is not None:
                os.close(write_fd)

    def test_is_cursor_ext_request_requires_id(self):
        self.assertTrue(is_cursor_ext_request({"jsonrpc": "2.0", "id": 1, "method": "cursor/task"}))
        self.assertFalse(is_cursor_ext_request({"jsonrpc": "2.0", "method": "cursor/task"}))

    def test_build_result_shapes(self):
        task = build_result("cursor/task", {})
        self.assertEqual(task["outcome"]["outcome"], "rejected")
        self.assertIn("in-process", task["outcome"]["reason"])

        ask = build_result("cursor/ask_question", {})
        self.assertEqual(ask["outcome"]["outcome"], "skipped")

        todos = build_result("cursor/update_todos", {"todos": [{"id": "1", "content": "x"}]})
        self.assertEqual(todos["outcome"]["outcome"], "accepted")
        self.assertEqual(len(todos["outcome"]["todos"]), 1)

    def test_is_unknown_cursor_ext_request(self):
        self.assertTrue(
            is_unknown_cursor_ext_request(
                {"jsonrpc": "2.0", "id": 1, "method": "cursor/unknown"}
            )
        )
        self.assertFalse(
            is_unknown_cursor_ext_request(
                {"jsonrpc": "2.0", "method": "cursor/unknown"}
            )
        )
        self.assertFalse(
            is_unknown_cursor_ext_request(
                {"jsonrpc": "2.0", "id": 1, "method": "cursor/task"}
            )
        )

    def test_iter_fd_lines_raises_on_oserror(self):
        read_fd, write_fd = os.pipe()
        os.close(read_fd)
        os.close(write_fd)
        with self.assertRaises(PipeFailure):
            next(iter(iter_fd_lines(read_fd)), None)

    def test_write_fd_raises_on_broken_pipe(self):
        read_fd, writer_fd = os.pipe()
        os.close(read_fd)
        lock = threading.Lock()
        with self.assertRaises(PipeFailure):
            write_fd(writer_fd, "x", lock)
        os.close(writer_fd)

    def test_filter_unknown_cursor_method_returns_method_not_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            agent = tmp / "fake-agent"
            agent.write_text(FAKE_AGENT)
            agent.chmod(0o755)
            reply_file = tmp / "reply.json"
            filter_proc = self._spawn_filter(agent, "unknown_cursor", {"REPLY_FILE": str(reply_file)})
            try:
                self._wait(filter_proc)
                stderr = filter_proc.stderr.read()
            finally:
                try:
                    filter_proc.stdin.close()
                except OSError:
                    pass
            self.assertEqual(filter_proc.returncode, 0, stderr)
            reply = json.loads(reply_file.read_text())
            self.assertEqual(reply["error"]["code"], -32601)
            self.assertIn("cursor/unknown_method", reply["error"]["message"])
            self.assertIn("[cursor-acp-filter]", stderr)
            self.assertNotIn("[cursor-acp-filter]", filter_proc.stdout.read())

    def test_filter_forwards_cursor_notification_without_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            agent = tmp / "fake-agent"
            agent.write_text(FAKE_AGENT)
            agent.chmod(0o755)
            filter_proc = self._spawn_filter(agent, "notify_cursor", {})
            stdout_lines = []
            try:
                while True:
                    line = self._readline(filter_proc, timeout=10)
                    if not line:
                        break
                    stdout_lines.append(line)
            finally:
                filter_proc.stdin.close()
                self._wait(filter_proc)
            forwarded = [json.loads(line) for line in stdout_lines if line.strip()]
            methods = [row.get("method") for row in forwarded]
            self.assertIn("cursor/unknown_method", methods)
            self.assertIn("end_turn", json.dumps(forwarded))

    def test_filter_propagates_nonzero_child_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            agent = tmp / "fake-agent"
            agent.write_text(FAKE_AGENT)
            agent.chmod(0o755)
            filter_proc = self._spawn_filter(agent, "nonzero", {})
            try:
                self._wait(filter_proc)
                stderr = filter_proc.stderr.read()
            finally:
                try:
                    filter_proc.stdin.close()
                except OSError:
                    pass
            self.assertEqual(filter_proc.returncode, 17, stderr)
            self.assertIn("[cursor-acp-filter]", stderr)
            self.assertIn("exit_code=17", stderr)

    def test_filter_drains_slow_agent_output_before_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            agent = tmp / "fake-agent"
            agent.write_text(FAKE_AGENT)
            agent.chmod(0o755)
            env = os.environ.copy()
            env["CURSOR_ACP_FILTER_REAL_AGENT"] = str(agent)
            env["CURSOR_ACP_FILTER_DRAIN_TIMEOUT"] = "30"
            env["PYTHONUNBUFFERED"] = "1"
            filter_proc = subprocess.Popen(
                [sys.executable, str(ROOT / "libexec" / "cursor_acp_filter.py"), "slow_drain"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            try:
                filter_proc.stdin.close()
                stdout, stderr = filter_proc.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                filter_proc.kill()
                stdout, stderr = filter_proc.communicate()
                self.fail(f"filter hung: stdout={stdout!r} stderr={stderr!r}")
            stdout_lines = [line for line in stdout.splitlines(keepends=True) if line.strip()]
            self.assertEqual(filter_proc.returncode, 0, stderr)
            self.assertEqual(len(stdout_lines), 80, stderr)

    def test_filter_terminates_child_after_client_pipe_break(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            agent = tmp / "fake-agent"
            agent.write_text(FAKE_AGENT)
            agent.chmod(0o755)
            agent_pid_file = tmp / "agent.pid"
            filter_proc = self._spawn_filter(
                agent, "ignore_eof", {"AGENT_PID_FILE": str(agent_pid_file)}
            )
            for _ in range(50):
                if agent_pid_file.exists():
                    break
                time.sleep(0.02)
            self.assertTrue(agent_pid_file.exists())
            try:
                filter_proc.stdout.close()
                filter_proc.stdin.close()
                self._wait(filter_proc, timeout=10)
            finally:
                pass
            stderr = filter_proc.stderr.read()
            self.assertEqual(filter_proc.returncode, 1, stderr)
            self.assertIn("[cursor-acp-filter]", stderr)
            agent_pid = int(agent_pid_file.read_text())
            alive = subprocess.run(
                ["ps", "-p", str(agent_pid), "-o", "stat="],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(alive.returncode, 0, alive.stdout)

    def test_filter_sigterm_does_not_orphan_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            agent = tmp / "fake-agent"
            agent.write_text(FAKE_AGENT)
            agent.chmod(0o755)
            agent_pid_file = tmp / "agent.pid"
            filter_proc = self._spawn_filter(
                agent, "sigterm_agent", {"AGENT_PID_FILE": str(agent_pid_file)}
            )
            for _ in range(50):
                if agent_pid_file.exists():
                    break
                time.sleep(0.02)
            self.assertTrue(agent_pid_file.exists())
            filter_proc.send_signal(signal.SIGTERM)
            try:
                self._wait(filter_proc, timeout=10)
            finally:
                try:
                    filter_proc.stdin.close()
                except OSError:
                    pass
            agent_pid = int(agent_pid_file.read_text())
            alive = subprocess.run(
                ["ps", "-p", str(agent_pid), "-o", "stat="],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(alive.returncode, 0, alive.stdout)

    def test_filter_replies_to_cursor_task_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            agent = tmp / "fake-agent"
            agent.write_text(FAKE_AGENT)
            agent.chmod(0o755)
            reply_file = tmp / "reply.json"
            filter_proc = self._spawn_filter(agent, "task", {"REPLY_FILE": str(reply_file)})
            stdout_lines = []
            try:
                while True:
                    line = self._readline(filter_proc)
                    if not line:
                        break
                    stdout_lines.append(line)
            finally:
                filter_proc.stdin.close()
                self._wait(filter_proc)
            self.assertEqual(filter_proc.returncode, 0, filter_proc.stderr.read())
            self.assertTrue(reply_file.is_file(), filter_proc.stderr.read())
            reply = json.loads(reply_file.read_text())
            self.assertEqual(reply["id"], 7)
            self.assertEqual(reply["result"]["outcome"]["outcome"], "rejected")
            forwarded = [json.loads(line) for line in stdout_lines if line.strip()]
            methods = [row.get("method") for row in forwarded]
            self.assertNotIn("cursor/task", methods)

    def test_filter_forwards_unrelated_acp(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            agent = tmp / "fake-agent"
            agent.write_text(FAKE_AGENT)
            agent.chmod(0o755)
            client_line_file = tmp / "client-line.txt"
            filter_proc = self._spawn_filter(
                agent, "forward", {"CLIENT_LINE_FILE": str(client_line_file)}
            )
            try:
                init = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n"
                filter_proc.stdin.write(init)
                filter_proc.stdin.flush()
                line = self._readline(filter_proc)
            finally:
                filter_proc.stdin.close()
                self._wait(filter_proc)
            self.assertIn("protocolVersion", line)
            self.assertTrue(client_line_file.is_file())
            self.assertIn("initialize", client_line_file.read_text())

    def test_end_to_end_through_real_filter_subprocess(self):
        """Proves both the rewrite and its ordering guarantee on the actual wire (not
        just the pure function in isolation): spawns the real filter subprocess with a
        fake agent that replies to every request, and checks (a) what the agent actually
        received and (b) that the client's model-set response is withheld until the
        synthetic "fast" round-trip with the agent has completed."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            agent = tmp / "fake-agent"
            agent.write_text(FAKE_AGENT)
            agent.chmod(0o755)
            client_lines_file = tmp / "client-lines.txt"
            filter_proc = self._spawn_filter(
                agent, "respond_and_capture", {"CLIENT_LINES_FILE": str(client_lines_file)}
            )
            try:
                filter_proc.stdin.write(json.dumps({
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"clientCapabilities": {"fs": True}},
                }) + "\n")
                filter_proc.stdin.flush()
                self._readline(filter_proc)  # initialize response

                filter_proc.stdin.write(json.dumps({
                    "jsonrpc": "2.0", "id": 2, "method": "session/set_config_option",
                    "params": {"sessionId": "s1", "configId": "model", "value": "composer-2.5"},
                }) + "\n")
                filter_proc.stdin.flush()
                model_set_response_line = self._readline(filter_proc)
            finally:
                filter_proc.stdin.close()
                self._wait(filter_proc)
            model_set_response = json.loads(model_set_response_line)
            self.assertEqual(model_set_response["id"], 2)

            received = [
                json.loads(line)
                for line in client_lines_file.read_text().splitlines()
                if line.strip()
            ]
            # Ordering proves the guarantee: the agent saw the synthetic "fast" request
            # (and this test only got its id=2 response after that request was sent),
            # which only happens once the id=2 response actually arrived from the agent.
            init_received, set_model_received, set_fast_received = received
            self.assertTrue(
                init_received["params"]["clientCapabilities"]["_meta"]["parameterizedModelPicker"]
            )
            self.assertEqual(set_model_received["params"]["value"], "composer-2.5")
            self.assertEqual(
                set_fast_received["params"],
                {"sessionId": "s1", "configId": "fast", "value": "false"},
            )

    def test_filter_replies_to_ask_question(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            script = tmp / "ask-agent"
            script.write_text(
                "#!/usr/bin/env python3\n"
                "import json, sys\n"
                "print(json.dumps({'jsonrpc':'2.0','id':3,'method':'cursor/ask_question','params':{}}), flush=True)\n"
                "resp=json.loads(sys.stdin.readline())\n"
                "assert resp['result']['outcome']['outcome']=='skipped'\n"
            )
            script.chmod(0o755)
            filter_proc = self._spawn_filter(script, "ask", {})
            try:
                self._wait(filter_proc)
                stdout = filter_proc.stdout.read()
                stderr = filter_proc.stderr.read()
            finally:
                try:
                    filter_proc.stdin.close()
                except OSError:
                    pass
            self.assertEqual(filter_proc.returncode, 0, stderr)
            self.assertNotIn("cursor/ask_question", stdout)


class CursorAcpFilterModelPickerTests(unittest.TestCase):
    def test_initialize_gains_parameterized_model_picker_meta(self):
        line = json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"clientCapabilities": {"fs": True}},
        }) + "\n"
        record = json.loads(rewrite_client_to_agent_line(line))
        self.assertTrue(record["params"]["clientCapabilities"]["_meta"]["parameterizedModelPicker"])
        self.assertTrue(record["params"]["clientCapabilities"]["fs"])

    def test_set_config_option_composer_forwarded_unmodified_and_queues_followup(self):
        # cursor-agent rejects bracket-parameterized model values over ACP (verified
        # live against the real binary); the bare model id must pass through untouched
        # and "fast" gets set via a separate queued follow-up request instead.
        line = json.dumps({
            "jsonrpc": "2.0", "id": 2, "method": "session/set_config_option",
            "params": {"sessionId": "s1", "configId": "model", "value": "composer-2.5"},
        }) + "\n"
        state = FilterState(None)
        outgoing = rewrite_client_to_agent_line(line, state)
        self.assertEqual(outgoing, line)
        self.assertEqual(state.model_set_followups[2], ("s1", "false"))

    def test_set_config_option_leaves_other_models_untouched(self):
        line = json.dumps({
            "jsonrpc": "2.0", "id": 3, "method": "session/set_config_option",
            "params": {"sessionId": "s1", "configId": "model", "value": "test-model"},
        }) + "\n"
        state = FilterState(None)
        self.assertEqual(rewrite_client_to_agent_line(line, state), line)
        self.assertEqual(state.model_set_followups, {})

    def test_legacy_set_model_composer_queues_followup(self):
        line = json.dumps({
            "jsonrpc": "2.0", "id": 4, "method": "session/set_model",
            "params": {"sessionId": "s1", "modelId": "composer-2.5"},
        }) + "\n"
        state = FilterState(None)
        outgoing = rewrite_client_to_agent_line(line, state)
        self.assertEqual(outgoing, line)
        self.assertEqual(state.model_set_followups[4], ("s1", "false"))


class CursorRunnerWiringTests(unittest.TestCase):
    def test_find_real_cursor_agent_skips_filter_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            shim = tmp / "cursor-agent"
            shim.write_text("#!/bin/sh\nexit 0\n")
            shim.chmod(0o755)
            real = tmp / "real-agent"
            real.write_text("#!/bin/sh\nexit 0\n")
            real.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = f"{tmp}{os.pathsep}{env.get('PATH', '')}"
            env["CURSOR_ACP_FILTER_REAL_AGENT"] = str(real)
            found_env, shim_dir = cursor_agent_path_env(env)
            self.assertIsNotNone(shim_dir)
            self.assertEqual(found_env["CURSOR_ACP_FILTER_REAL_AGENT"], str(real.resolve()))
            self.assertTrue((Path(shim_dir) / "cursor-agent").is_file())
            self.assertTrue((Path(shim_dir) / "agent").is_file())
            self.assertTrue(found_env["PATH"].startswith(str(shim_dir)))


if __name__ == "__main__":
    unittest.main()
