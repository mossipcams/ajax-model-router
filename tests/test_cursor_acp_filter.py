import json
import os
import select
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libexec"))

from cursor_acp_filter import (  # noqa: E402
    build_result,
    is_cursor_ext_request,
    iter_fd_lines,
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
