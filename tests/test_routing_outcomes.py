#!/usr/bin/env python3
"""Routing outcome persistence and router-log sidecar."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libexec"))

LOGGER = ROOT / "scripts" / "router-log"
from semantic.outcome import append_routing_event, default_events_path  # noqa: E402


class RoutingOutcomesTests(unittest.TestCase):
    def test_v1_tsv_columns_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "outcome.tsv"
            result = subprocess.run(
                [
                    LOGGER,
                    "--log",
                    log,
                    "--requested-agent",
                    "cursor",
                    "--actual-agent",
                    "cursor",
                    "--success",
                    "true",
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            fields = log.read_text().rstrip("\n").split("\t")
            self.assertEqual(len(fields), 9)
            self.assertEqual(fields[0], "v1")

    def test_routing_event_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "outcome.tsv"
            event = json.dumps({"matched_rule": "R-CURSOR", "model_key": "CURSOR"})
            result = subprocess.run(
                [
                    LOGGER,
                    "--log",
                    log,
                    "--requested-agent",
                    "cursor",
                    "--actual-agent",
                    "cursor",
                    "--routing-event",
                    event,
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            events = default_events_path(log)
            self.assertTrue(events.is_file())
            record = json.loads(events.read_text().strip())
            self.assertEqual(record["matched_rule"], "R-CURSOR")

    def test_append_routing_event_helper(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "outcome.tsv"
            path = append_routing_event(
                tsv_log=log,
                requested_agent="pi",
                actual_agent="pi",
                decision={"model_key": "GLM"},
            )
            self.assertTrue(path.is_file())


if __name__ == "__main__":
    unittest.main()
