#!/usr/bin/env python3
"""TaskFeatures / FailureFeatures schema validation."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libexec"))

from semantic.schema import (  # noqa: E402
    Complexity,
    FailureFeatures,
    TaskDomain,
    TaskFeatures,
    TaskType,
    parse_failure_features_json,
    parse_task_features_json,
)


VALID_TASK = """{
  "task_type": "bug_fix",
  "domains": ["rust_backend"],
  "complexity": "medium",
  "scope": "localized",
  "reasoning_depth": "medium",
  "uncertainty": "low",
  "requires_repo_discovery": false,
  "requires_visual_validation": false,
  "requires_large_context": false,
  "likely_context_size": "small",
  "risk": "medium",
  "confidence": 0.85
}"""


class SemanticSchemaTests(unittest.TestCase):
    def test_valid_task_features_parse(self):
        features = parse_task_features_json(VALID_TASK)
        self.assertEqual(features.task_type, TaskType.BUG_FIX)
        self.assertEqual(features.domains[0], TaskDomain.RUST_BACKEND)
        self.assertEqual(features.complexity, Complexity.MEDIUM)
        self.assertAlmostEqual(features.confidence, 0.85)

    def test_invalid_json_rejected(self):
        with self.assertRaises(ValueError):
            parse_task_features_json("not json")

    def test_unknown_enum_rejected(self):
        bad = VALID_TASK.replace('"bug_fix"', '"mystery_task"')
        with self.assertRaises(ValueError):
            parse_task_features_json(bad)

    def test_missing_field_rejected(self):
        import json

        data = json.loads(VALID_TASK)
        del data["confidence"]
        with self.assertRaises(ValueError):
            TaskFeatures.from_dict(data)

    def test_unexpected_field_rejected(self):
        import json

        data = json.loads(VALID_TASK)
        data["chain_of_thought"] = "hidden reasoning"
        with self.assertRaises(ValueError):
            TaskFeatures.from_dict(data)

    def test_confidence_out_of_bounds_rejected(self):
        bad = VALID_TASK.replace("0.85", "1.5")
        with self.assertRaises(ValueError):
            parse_task_features_json(bad)

    def test_valid_failure_features_parse(self):
        raw = """{
          "failure_class": "test_regression",
          "domain": "testing",
          "component": "tests/test_foo.py",
          "likely_task_related": true,
          "retry_same_model": true,
          "confidence": 0.7
        }"""
        features = parse_failure_features_json(raw)
        self.assertEqual(features.component, "tests/test_foo.py")


if __name__ == "__main__":
    unittest.main()
