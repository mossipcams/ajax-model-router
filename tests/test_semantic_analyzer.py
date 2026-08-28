#!/usr/bin/env python3
"""SemanticAnalyzer disabled / fallback behavior."""

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libexec"))

from semantic.analyzer import (  # noqa: E402
    DisabledSemanticAnalyzer,
    LocalSlmSemanticAnalyzer,
    TaskAnalysisInput,
    analyze_with_fallback,
    create_analyzer,
)
from semantic.config import SlmConfig  # noqa: E402
from semantic.errors import SemanticDisabledError  # noqa: E402
from semantic.facts import RoutingFacts  # noqa: E402


class SemanticAnalyzerTests(unittest.TestCase):
    def test_disabled_analyzer_raises(self):
        analyzer = DisabledSemanticAnalyzer()
        inp = TaskAnalysisInput(user_request="fix bug", facts=RoutingFacts())
        with self.assertRaises(SemanticDisabledError):
            analyzer.analyze_task(inp)

    def test_create_analyzer_enabled_by_default(self):
        analyzer = create_analyzer()
        self.assertIsInstance(analyzer, LocalSlmSemanticAnalyzer)

    def test_analyze_with_fallback_on_disabled(self):
        features, reason, source = analyze_with_fallback(
            DisabledSemanticAnalyzer(),
            TaskAnalysisInput(user_request="task", facts=RoutingFacts()),
        )
        self.assertIsNone(features)
        self.assertIn("disabled", reason)
        self.assertEqual(source, "disabled")

    def test_timeout_fallback(self):
        cfg = SlmConfig(
            enabled=True,
            endpoint="http://127.0.0.1:9/v1/chat/completions",
            model="test",
            timeout_ms=100,
            max_retries=0,
            confidence_threshold=0.5,
            task_system="sys",
            failure_system="sys",
            max_tokens=64,
        )
        analyzer = LocalSlmSemanticAnalyzer(cfg)
        with mock.patch(
            "semantic.analyzer.chat_completion",
            side_effect=__import__(
                "semantic.errors", fromlist=["SemanticTimeoutError"]
            ).SemanticTimeoutError("timed out"),
        ):
            features, reason, source = analyze_with_fallback(
                analyzer,
                TaskAnalysisInput(user_request="task", facts=RoutingFacts()),
            )
        self.assertIsNone(features)
        self.assertIn("timed out", reason)
        self.assertEqual(source, "slm_failed")

    def test_low_confidence_fallback(self):
        cfg = SlmConfig(
            enabled=True,
            endpoint="http://127.0.0.1:9/v1/chat/completions",
            model="test",
            timeout_ms=1000,
            max_retries=0,
            confidence_threshold=0.9,
            task_system="sys",
            failure_system="sys",
            max_tokens=64,
        )
        low_conf = """{
          "task_type": "bug_fix",
          "domains": ["tooling"],
          "complexity": "low",
          "scope": "localized",
          "reasoning_depth": "shallow",
          "uncertainty": "low",
          "requires_repo_discovery": false,
          "requires_visual_validation": false,
          "requires_large_context": false,
          "likely_context_size": "small",
          "risk": "low",
          "confidence": 0.3
        }"""
        analyzer = LocalSlmSemanticAnalyzer(cfg)
        with mock.patch("semantic.analyzer.chat_completion", return_value=low_conf):
            features, reason, source = analyze_with_fallback(
                analyzer,
                TaskAnalysisInput(user_request="task", facts=RoutingFacts()),
            )
        self.assertIsNone(features)
        self.assertIn("confidence", reason)
        self.assertEqual(source, "slm_rejected")


if __name__ == "__main__":
    unittest.main()
