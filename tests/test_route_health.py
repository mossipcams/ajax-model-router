#!/usr/bin/env python3
"""route-health cache: TTL, failure bookkeeping, probe verdicts."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libexec"))

import route_health  # noqa: E402


class RouteHealthTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch.dict(
            os.environ, {"AJAX_ROUTER_HEALTH_CACHE": str(Path(tmp.name) / "health.json")}
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_recent_failure_is_unavailable_until_ttl_or_success(self):
        route_health.record("pi/a", False, "429", now=1000)
        route_health.record("pi/b", True, "ok", now=1000)
        self.assertEqual(route_health.unavailable(now=1000 + 60), {"pi/a"})
        self.assertEqual(route_health.unavailable(now=1000 + route_health.TTL_SECONDS + 1), set())
        route_health.record("pi/a", True, "ok", now=1100)
        self.assertEqual(route_health.unavailable(now=1200), set())

    def test_missing_or_corrupt_cache_means_nothing_known_down(self):
        self.assertEqual(route_health.unavailable(), set())
        route_health.cache_path().write_text("not json")
        self.assertEqual(route_health.unavailable(), set())

    def _run(self, returncode, stdout, stderr=""):
        return subprocess.CompletedProcess([], returncode, stdout, stderr)

    def test_probe_requires_clean_exit_and_ok_reply(self):
        with mock.patch("route_health.subprocess.run", return_value=self._run(0, "ok\n")):
            self.assertEqual(route_health.probe("pi/local/q"), (True, "ok"))
        with mock.patch(
            "route_health.subprocess.run",
            return_value=self._run(1, "", "429 GoUsageLimitError"),
        ):
            ok, detail = route_health.probe("pi/opencode-go/deepseek")
            self.assertFalse(ok)
            self.assertIn("429", detail)
        with mock.patch("route_health.subprocess.run", side_effect=FileNotFoundError):
            self.assertEqual(route_health.probe("codex/x"), (False, "codex CLI not found"))

    def test_probe_uses_each_agents_cli(self):
        self.assertEqual(route_health.probe_command("pi", "local/q")[:4], ["pi", "-p", "--model", "local/q"])
        self.assertEqual(route_health.probe_command("codex", "m")[:2], ["codex", "exec"])
        self.assertEqual(route_health.probe_command("cursor", "m")[0], "cursor-agent")


if __name__ == "__main__":
    unittest.main()


import json  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402


class _FakeLlama(BaseHTTPRequestHandler):
    mode = "ok"

    def log_message(self, *args):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.mode == "loading":
            self.send_response(503)
            self.end_headers()
            return
        if self.mode == "slow":
            time.sleep(2)
        body = json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        except BrokenPipeError:
            pass  # the probe gave up first (slow-server case)


class LocalProbeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeLlama)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        url = f"http://127.0.0.1:{self.server.server_port}/v1"
        patcher = mock.patch.dict(os.environ, {
            "AJAX_ROUTER_HEALTH_CACHE": str(Path(tmp.name) / "health.json"),
            "AJAX_ROUTER_QWEN_URL": url,
        })
        patcher.start()
        self.addCleanup(patcher.stop)
        _FakeLlama.mode = "ok"

    def test_up_when_server_generates_a_token(self):
        ok, detail = route_health.probe_local(route_health.QWEN_ROUTE)
        self.assertTrue(ok, detail)

    def test_down_while_model_loading(self):
        _FakeLlama.mode = "loading"
        ok, detail = route_health.probe_local(route_health.QWEN_ROUTE)
        self.assertFalse(ok)
        self.assertIn("503", detail)

    def test_down_when_too_slow_to_generate(self):
        _FakeLlama.mode = "slow"
        ok, _ = route_health.probe_local(route_health.QWEN_ROUTE, timeout=0.5)
        self.assertFalse(ok)

    def test_down_when_nothing_listening(self):
        self.server.shutdown()
        self.server.server_close()
        ok, detail = route_health.probe_local(route_health.QWEN_ROUTE, timeout=1)
        self.assertFalse(ok)
        self.assertIn("unreachable", detail)

    def test_refresh_clears_stale_failure_and_records_new_one(self):
        route_health.record(route_health.QWEN_ROUTE, False, "TIMEOUT")
        self.assertEqual(route_health.refresh_local(), set())
        self.assertNotIn(route_health.QWEN_ROUTE, route_health.unavailable())
        _FakeLlama.mode = "loading"
        self.assertEqual(route_health.refresh_local(), {route_health.QWEN_ROUTE})
        self.assertIn(route_health.QWEN_ROUTE, route_health.unavailable())

    def test_generic_probe_uses_http_for_local_route(self):
        with mock.patch("route_health.subprocess.run") as run:
            ok, _ = route_health.probe(route_health.QWEN_ROUTE)
        self.assertTrue(ok)
        run.assert_not_called()

    def test_routing_skips_qwen_when_probe_fails(self):
        sys.path.insert(0, str(ROOT / "libexec"))
        import semantic

        _FakeLlama.mode = "loading"
        self.assertIn("QWEN", semantic._known_down_routes())
        _FakeLlama.mode = "ok"
        self.assertNotIn("QWEN", semantic._known_down_routes())
