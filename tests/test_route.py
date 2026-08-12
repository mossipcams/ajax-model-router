#!/usr/bin/env python3
"""Harness-boundary routing decisions."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTE = ROOT / "scripts" / "route"

import sys

sys.path.insert(0, str(ROOT / "libexec"))
import route as route_mod


class RouteDecisionTests(unittest.TestCase):
    def test_cursor_to_cursor_is_use_native(self):
        decision = route_mod.decide(
            caller_harness="cursor",
            target_transport="cursor",
            model="composer-2.5",
            which=lambda _: "/fake/cursor-agent",
        )
        self.assertEqual(decision["ACTION"], "USE_NATIVE")
        self.assertEqual(decision["CALLER_HARNESS"], "cursor")
        self.assertEqual(decision["TARGET_TRANSPORT"], "cursor")

    def test_codex_to_codex_is_use_native(self):
        decision = route_mod.decide(
            caller_harness="codex",
            target_transport="codex",
            model="gpt-5.6-sol",
            which=lambda _: "/fake/codex",
        )
        self.assertEqual(decision["ACTION"], "USE_NATIVE")

    def test_same_transport_does_not_require_binary(self):
        decision = route_mod.decide(
            caller_harness="cursor",
            target_transport="cursor",
            model="composer-2.5",
            which=lambda _: None,
        )
        self.assertEqual(decision["ACTION"], "USE_NATIVE")

    def test_claude_to_composer_delegates(self):
        decision = route_mod.decide(
            caller_harness="claude",
            target_transport="cursor",
            model="composer-2.5",
            which=lambda cmd: "/fake/" + cmd,
        )
        self.assertEqual(decision["ACTION"], "DELEGATE")
        self.assertEqual(decision["CALLER_HARNESS"], "claude")
        self.assertEqual(decision["TARGET_TRANSPORT"], "cursor")
        self.assertEqual(decision["MODEL"], "composer-2.5")

    def test_claude_to_grok_high_delegates(self):
        decision = route_mod.decide(
            caller_harness="claude",
            target_transport="cursor",
            model="cursor-grok-4.6-high",
            which=lambda cmd: "/fake/" + cmd,
        )
        self.assertEqual(decision["ACTION"], "DELEGATE")
        self.assertEqual(decision["CALLER_HARNESS"], "claude")
        self.assertEqual(decision["TARGET_TRANSPORT"], "cursor")
        self.assertEqual(decision["MODEL"], "cursor-grok-4.6-high")

    def test_claude_never_use_native(self):
        # Even if someone passed a bogus matching name, claude is not a transport.
        decision = route_mod.decide(
            caller_harness="claude",
            target_transport="cursor",
            model="composer-2.5",
            which=lambda cmd: "/fake/" + cmd,
        )
        self.assertNotEqual(decision["ACTION"], "USE_NATIVE")

    def test_other_to_pi_delegates(self):
        decision = route_mod.decide(
            caller_harness="other",
            target_transport="pi",
            model="opencode-go/glm-5.2",
            which=lambda cmd: "/fake/" + cmd,
        )
        self.assertEqual(decision["ACTION"], "DELEGATE")

    def test_codex_to_composer_delegates_to_cursor(self):
        decision = route_mod.decide(
            caller_harness="codex",
            target_transport="cursor",
            model="composer-2.5",
            which=lambda cmd: "/fake/" + cmd,
        )
        self.assertEqual(decision["ACTION"], "DELEGATE")
        self.assertEqual(decision["TARGET_TRANSPORT"], "cursor")

    def test_cursor_to_codex_delegates(self):
        decision = route_mod.decide(
            caller_harness="cursor",
            target_transport="codex",
            model="gpt-5.6-sol",
            which=lambda cmd: "/fake/" + cmd,
        )
        self.assertEqual(decision["ACTION"], "DELEGATE")
        self.assertEqual(decision["TARGET_TRANSPORT"], "codex")

    def test_cursor_or_codex_to_pi_delegates(self):
        for current in ("cursor", "codex"):
            for model in ("opencode-go/minimax-m3", "opencode-go/glm-5.2"):
                decision = route_mod.decide(
                    caller_harness=current,
                    target_transport="pi",
                    model=model,
                    which=lambda cmd: "/fake/" + cmd,
                )
                self.assertEqual(decision["ACTION"], "DELEGATE", (current, model))

    def test_model_on_wrong_transport_is_stop(self):
        decision = route_mod.decide(
            caller_harness="cursor",
            target_transport="codex",
            model="composer-2.5",
            which=lambda cmd: "/fake/" + cmd,
        )
        self.assertEqual(decision["ACTION"], "STOP")
        self.assertIn("does not belong", decision["REASON"])

    def test_unavailable_transport_is_stop_without_substitution(self):
        decision = route_mod.decide(
            caller_harness="claude",
            target_transport="codex",
            model="gpt-5.6-sol",
            which=lambda _: None,
        )
        self.assertEqual(decision["ACTION"], "STOP")
        self.assertIn("unavailable", decision["REASON"])
        self.assertEqual(decision["MODEL"], "gpt-5.6-sol")

    def test_cli_accepts_caller_and_transport_flags(self):
        help_flags = subprocess.run(
            [ROUTE, "--help"], text=True, capture_output=True
        )
        self.assertEqual(help_flags.returncode, 0)
        self.assertIn("--caller-harness", help_flags.stdout)
        self.assertIn("--target-transport", help_flags.stdout)

    def test_legacy_flag_aliases_still_work(self):
        result = subprocess.run(
            [
                ROUTE,
                "--current-harness",
                "cursor",
                "--target-harness",
                "cursor",
                "--model",
                "composer-2.5",
                "--json",
            ],
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["ACTION"], "USE_NATIVE")
        self.assertEqual(payload["CALLER_HARNESS"], "cursor")
        self.assertEqual(payload["TARGET_TRANSPORT"], "cursor")

    def test_use_native_creates_no_snapshot_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            snap = Path(tmp) / "snap"
            snap.mkdir()
            decision = route_mod.decide(
                caller_harness="codex",
                target_transport="codex",
                model="gpt-5.6-sol",
                which=lambda _: None,
            )
            self.assertEqual(decision["ACTION"], "USE_NATIVE")
            self.assertFalse((snap / "pre.json").exists())
            self.assertFalse((snap / "context.json").exists())


if __name__ == "__main__":
    unittest.main()
