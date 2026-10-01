#!/usr/bin/env python3
"""Delegate prompt assembly, FALLBACK chain, and analyze-task --execution."""

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libexec"))

import lifecycle_hooks as hooks  # noqa: E402
from semantic import analyze_task_main  # noqa: E402


class BuildPromptTests(unittest.TestCase):
    def test_empty_sections_omitted_and_items_deduped(self):
        prompt = hooks.build_prompt(
            {"user_request": "", "allowed_files": ["a.py"], "acceptance": ["x", "x", " "], "verify": []}
        )
        self.assertNotIn("Task:", prompt)
        self.assertNotIn("Verify with:", prompt)
        self.assertNotIn("(none)", prompt)
        self.assertEqual(prompt.count("- x"), 1)

    def test_task_and_verify_precede_report(self):
        prompt = hooks.build_prompt(
            {"user_request": "do it", "allowed_files": ["a.py"], "acceptance": ["ok"], "verify": ["pytest"]}
        )
        self.assertLess(prompt.index("Task:"), prompt.index("ROUTER_REPORT_BEGIN"))
        self.assertLess(prompt.index("- pytest"), prompt.index("ROUTER_REPORT_BEGIN"))


class ExecutionFlagTests(unittest.TestCase):
    def test_execution_flag_prints_only_block(self):
        with mock.patch("semantic._load_cli_payload", return_value={"task": "fix typo"}):
            out = io.StringIO()
            with redirect_stdout(out):
                analyze_task_main(["--execution"])
        data = json.loads(out.getvalue())
        self.assertIn("AGENT", data)
        self.assertNotIn("explanation", data)


if __name__ == "__main__":
    unittest.main()
