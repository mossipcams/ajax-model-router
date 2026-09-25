#!/usr/bin/env python3
"""Context requirement strategy — deterministic from route decision + facts."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libexec"))

from semantic.context import derive_context_requirements  # noqa: E402
from semantic.facts import RoutingFacts  # noqa: E402
from semantic.schema import (  # noqa: E402
    ContextBudget,
    RouteDecision,
)


def _sensor(route: str = "CURSOR", complexity: int = 2, ambiguity: int = 1):
    other = "MINIMAX" if route != "MINIMAX" else "CURSOR"
    return RouteDecision(
        route=route,
        probabilities={route: 0.9, other: 0.1},
        complexity=complexity,
        ambiguity=ambiguity,
        confidence=0.9,
    )


class ContextStrategyTests(unittest.TestCase):
    def test_glm_route_requests_architecture_docs_and_history(self):
        context = derive_context_requirements(_sensor("GLM"), RoutingFacts())
        self.assertTrue(context.architecture_docs)
        self.assertTrue(context.git_history)

    def test_high_complexity_requests_git_history(self):
        context = derive_context_requirements(
            _sensor("CURSOR", complexity=4), RoutingFacts()
        )
        self.assertTrue(context.git_history)

    def test_high_ambiguity_requests_architecture_docs(self):
        context = derive_context_requirements(
            _sensor("CURSOR", ambiguity=4), RoutingFacts()
        )
        self.assertTrue(context.architecture_docs)

    def test_no_decision_no_architecture_docs(self):
        context = derive_context_requirements(None, RoutingFacts())
        self.assertFalse(context.architecture_docs)
        self.assertFalse(context.git_history)

    def test_budget_large_on_big_diff(self):
        context = derive_context_requirements(
            None, RoutingFacts(diff_line_count=500)
        )
        self.assertEqual(context.context_budget, ContextBudget.LARGE)

    def test_budget_medium_on_recent_diff(self):
        context = derive_context_requirements(
            None, RoutingFacts(diff_line_count=10)
        )
        self.assertEqual(context.context_budget, ContextBudget.MEDIUM)

    def test_budget_small_without_diff(self):
        context = derive_context_requirements(None, RoutingFacts())
        self.assertEqual(context.context_budget, ContextBudget.SMALL)

    def test_known_subsystem_in_likely_subsystems(self):
        context = derive_context_requirements(
            None, RoutingFacts(known_subsystem="billing")
        )
        self.assertEqual(context.likely_subsystems, ("billing",))

    def test_test_command_sets_related_tests(self):
        context = derive_context_requirements(
            None, RoutingFacts(test_command="pytest")
        )
        self.assertTrue(context.related_tests)

    def test_retry_sets_git_history(self):
        context = derive_context_requirements(
            None, RoutingFacts(is_retry=True, previous_model_key="MINIMAX")
        )
        self.assertTrue(context.git_history)


if __name__ == "__main__":
    unittest.main()
