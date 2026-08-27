#!/usr/bin/env python3
"""Deterministic facts collection."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libexec"))

from semantic.facts import collect_facts  # noqa: E402


class DeterministicFactsTests(unittest.TestCase):
    def test_collect_from_payload(self):
        facts = collect_facts(
            {
                "user_request": "add feature",
                "explicit_model": "composer-2.5",
                "changed_files": ["src/a.rs", "src/b.rs"],
                "retry_count": 1,
                "is_retry": True,
                "previous_model_key": "CURSOR",
                "working_directory": str(ROOT),
            }
        )
        self.assertEqual(facts.user_request, "add feature")
        self.assertEqual(facts.explicit_model, "composer-2.5")
        self.assertEqual(facts.changed_file_count, 2)
        self.assertIn("rs", facts.file_extensions)
        self.assertTrue(facts.is_retry)
        self.assertEqual(facts.previous_model_key, "CURSOR")

    def test_facts_to_dict_roundtrip(self):
        facts = collect_facts({"task": "docs tweak", "diff_line_count": 5})
        data = facts.to_dict()
        self.assertEqual(data["diff_line_count"], 5)
        self.assertEqual(data["user_request"], "docs tweak")


if __name__ == "__main__":
    unittest.main()
