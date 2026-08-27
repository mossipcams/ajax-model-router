#!/usr/bin/env python3
"""Context requirement generation."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libexec"))

from semantic.context import derive_context_requirements  # noqa: E402
from semantic.facts import RoutingFacts  # noqa: E402
from semantic.schema import (  # noqa: E402
    ChangeScope,
    Complexity,
    ContextSize,
    ReasoningDepth,
    TaskDomain,
    TaskFeatures,
    TaskRisk,
    TaskType,
    Uncertainty,
)


class ContextStrategyTests(unittest.TestCase):
    def test_architecture_includes_docs_and_history(self):
        features = TaskFeatures(
            task_type=TaskType.ARCHITECTURE,
            domains=(TaskDomain.ARCHITECTURE,),
            complexity=Complexity.HIGH,
            scope=ChangeScope.REPO_WIDE,
            reasoning_depth=ReasoningDepth.DEEP,
            uncertainty=Uncertainty.MEDIUM,
            requires_repo_discovery=True,
            requires_visual_validation=False,
            requires_large_context=True,
            likely_context_size=ContextSize.LARGE,
            risk=TaskRisk.HIGH,
            confidence=0.8,
        )
        context = derive_context_requirements(features, RoutingFacts())
        self.assertTrue(context.architecture_docs)
        self.assertTrue(context.git_history)
        self.assertIn("architecture", context.likely_subsystems)

    def test_changed_files_enable_recent_diff(self):
        facts = RoutingFacts(changed_files=["src/a.py"])
        context = derive_context_requirements(None, facts)
        self.assertTrue(context.recent_diff)


if __name__ == "__main__":
    unittest.main()
