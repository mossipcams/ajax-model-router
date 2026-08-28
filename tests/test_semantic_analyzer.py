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
    TASK_SCHEMA_HINT,
    TaskAnalysisInput,
    analyze_with_fallback,
    create_analyzer,
)
from semantic.config import SlmConfig  # noqa: E402
from semantic.errors import SemanticDisabledError  # noqa: E402
from semantic.facts import RoutingFacts  # noqa: E402
from semantic.schema import TaskDomain, parse_task_features_json, task_features_response_format  # noqa: E402


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

    def test_schema_echo_domains_rejected(self):
        schema_echo = """{
          "task_type": "bug_fix",
          "domains": ["frontend|rust_backend|mobile_web|git|github|testing|ci|architecture|tooling|unknown"],
          "complexity": "low",
          "scope": "localized",
          "reasoning_depth": "shallow",
          "uncertainty": "low",
          "requires_repo_discovery": false,
          "requires_visual_validation": false,
          "requires_large_context": false,
          "likely_context_size": "small",
          "risk": "low",
          "confidence": 0.9
        }"""
        with self.assertRaises(ValueError) as ctx:
            parse_task_features_json(schema_echo)
        self.assertIn("schema echo", str(ctx.exception))

        cfg = SlmConfig(
            enabled=True,
            endpoint="http://127.0.0.1:9/v1/chat/completions",
            model="test",
            timeout_ms=1000,
            max_retries=0,
            confidence_threshold=0.5,
            task_system="sys",
            failure_system="sys",
            max_tokens=64,
        )
        analyzer = LocalSlmSemanticAnalyzer(cfg)
        with mock.patch("semantic.analyzer.chat_completion", return_value=schema_echo):
            features, reason, source = analyze_with_fallback(
                analyzer,
                TaskAnalysisInput(user_request="task", facts=RoutingFacts()),
            )
        self.assertIsNone(features)
        self.assertIn("schema echo", reason)
        self.assertEqual(source, "slm_failed")

    def test_pipe_joined_domain_subset_parses(self):
        payload = """{
          "task_type": "test",
          "domains": ["frontend|testing"],
          "complexity": "low",
          "scope": "localized",
          "reasoning_depth": "shallow",
          "uncertainty": "low",
          "requires_repo_discovery": false,
          "requires_visual_validation": false,
          "requires_large_context": false,
          "likely_context_size": "small",
          "risk": "low",
          "confidence": 0.9
        }"""
        features = parse_task_features_json(payload)
        self.assertEqual(
            features.domains,
            (TaskDomain.FRONTEND, TaskDomain.TESTING),
        )

    def test_analyzer_passes_strict_json_schema_to_client(self):
        cfg = SlmConfig(
            enabled=True,
            endpoint="http://127.0.0.1:9/v1/chat/completions",
            model="qwen3.5:4b",
            timeout_ms=1000,
            max_retries=0,
            confidence_threshold=0.5,
            task_system="sys",
            failure_system="sys",
            max_tokens=256,
        )
        good = """{
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
          "confidence": 0.9
        }"""
        analyzer = LocalSlmSemanticAnalyzer(cfg)
        with mock.patch("semantic.analyzer.chat_completion", return_value=good) as mocked:
            analyzer.analyze_task(
                TaskAnalysisInput(user_request="task", facts=RoutingFacts())
            )
        _, kwargs = mocked.call_args
        self.assertEqual(kwargs["model"], "qwen3.5:4b")
        self.assertLessEqual(kwargs["max_tokens"], 256)
        self.assertEqual(kwargs["response_format"], task_features_response_format())

    def test_task_schema_hint_lists_discrete_domains(self):
        self.assertNotIn(
            "frontend|rust_backend|mobile_web|git|github|testing|ci|architecture|tooling|unknown",
            TASK_SCHEMA_HINT,
        )
        self.assertIn('"domains": [', TASK_SCHEMA_HINT)
        self.assertIn('"allowed_values"', TASK_SCHEMA_HINT)


if __name__ == "__main__":
    unittest.main()
