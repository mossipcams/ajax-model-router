#!/usr/bin/env python3
"""Lightweight outcome logging (non-blocking, omit unknowns)."""

import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOGGER = ROOT / "scripts" / "router-log"
SUMMARY = ROOT / "scripts" / "router-log-summary"


def row_args(log, **overrides):
    args = [
        str(LOGGER),
        "--log",
        str(log),
        "--requested-agent",
        "cursor",
        "--actual-agent",
        "cursor",
        "--success",
        "true",
        "--revision-needed",
        "false",
        "--duration",
        "12.5",
    ]
    for key, value in overrides.items():
        flag = f"--{key.replace('_', '-')}"
        if flag in args:
            index = args.index(flag)
            args[index + 1] = str(value)
        else:
            args.extend([flag, str(value)])
    return args


class OutcomeLogTests(unittest.TestCase):
    def test_writer_requires_agents_and_omits_unknowns(self):
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
                    "pi",
                    "--success",
                    "false",
                    "--revision-needed",
                    "true",
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            fields = log.read_text().rstrip("\n").split("\t")
            self.assertEqual(fields[0], "v1")
            self.assertTrue(fields[1].endswith("Z"))
            self.assertEqual(fields[2:7], ["cursor", "pi", "false", "true", ""])
            self.assertEqual(fields[7], "")  # cost omitted
            self.assertEqual(fields[8], "")  # duration omitted

            incomplete = [
                LOGGER,
                "--log",
                log,
                "--requested-agent",
                "cursor",
            ]
            result = subprocess.run(incomplete, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("actual-agent", result.stderr)

    def test_rejects_invalid_agent(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "outcome.tsv"
            result = subprocess.run(
                row_args(log, requested_agent="opencode"),
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)

    def test_summary_aggregates_outcomes(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "outcome.tsv"
            for args in (
                row_args(log, success="true", revision_needed="false"),
                row_args(
                    log,
                    requested_agent="pi",
                    actual_agent="pi",
                    success="false",
                    revision_needed="true",
                ),
                row_args(
                    log,
                    success="false",
                    revision_needed="false",
                    escaped_defect="true",
                ),
            ):
                result = subprocess.run(args, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)

            summary = subprocess.run(
                [SUMMARY, log], text=True, capture_output=True
            )
            self.assertEqual(summary.returncode, 0, summary.stderr)
            self.assertIn("rows: 3", summary.stdout)
            self.assertIn("escaped_defect: 1", summary.stdout)
            self.assertIn("cursor", summary.stdout)
            self.assertIn("pi", summary.stdout)


if __name__ == "__main__":
    unittest.main()
