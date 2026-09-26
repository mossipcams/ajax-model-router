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
            ok, detail = route_health.probe("pi/opencode-go/glm")
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
