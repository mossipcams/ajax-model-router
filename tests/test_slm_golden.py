#!/usr/bin/env python3
"""Live SLM golden eval — skipped when Ollama is unreachable (no CI dependency)."""

from __future__ import annotations

import sys
import unittest
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libexec"))

from semantic.analyzer import (  # noqa: E402
    LocalSlmSemanticAnalyzer,
    TaskAnalysisInput,
    analyze_with_fallback,
)
from semantic.config import load_slm_config  # noqa: E402
from semantic.facts import RoutingFacts  # noqa: E402
from semantic.schema import ChangeScope  # noqa: E402


@dataclass(frozen=True)
class GoldenTask:
    name: str
    prompt: str
    category: str


GOLDEN_TASKS: tuple[GoldenTask, ...] = (
    GoldenTask(
        name="trivial_docs",
        category="trivial_docs",
        prompt="Fix a typo in the README installation section.",
    ),
    GoldenTask(
        name="localized_bug_fix",
        category="localized_bug_fix",
        prompt=(
            "Fix an off-by-one error in parse_int that rejects valid negative "
            "integers in lib/util/parse.py."
        ),
    ),
    GoldenTask(
        name="architecture_high_complexity",
        category="architecture",
        prompt=(
            "Design a migration plan from a monolithic Axum gateway to "
            "event-driven microservices with bounded contexts and async messaging."
        ),
    ),
    GoldenTask(
        name="ui_visual_validation",
        category="ui_visual",
        prompt=(
            "Redesign the login screen color palette, spacing, and button hover "
            "states so they match the new brand guidelines and look correct on mobile."
        ),
    ),
    GoldenTask(
        name="test_writing",
        category="testing",
        prompt="Add unit tests for the JWT refresh token rotation logic in auth service.",
    ),
    GoldenTask(
        name="ci_failure",
        category="ci",
        prompt="Fix the GitHub Actions workflow that fails on clippy::pedantic in CI.",
    ),
    GoldenTask(
        name="cross_module_refactor",
        category="cross_module",
        prompt=(
            "Extract duplicated input validation from three route handlers into "
            "a shared validation module used across the API layer."
        ),
    ),
    GoldenTask(
        name="investigation",
        category="investigation",
        prompt=(
            "Investigate intermittent WebSocket disconnects under load; reproduce "
            "and identify whether the root cause is client, gateway, or upstream."
        ),
    ),
    GoldenTask(
        name="localized_feature",
        category="localized_feature",
        prompt="Add a CSV export button to the existing settings page.",
    ),
    GoldenTask(
        name="repo_wide_migration",
        category="repo_wide",
        prompt=(
            "Migrate the entire Rust codebase from callback-style futures to "
            "async/await with consistent error handling across all crates."
        ),
    ),
)


def _ollama_reachable(endpoint: str, timeout_sec: float = 2.0) -> bool:
    """Probe Ollama base URL derived from the chat/completions endpoint."""
    base = endpoint.split("/v1/")[0].rstrip("/")
    probe = f"{base}/"
    request = urllib.request.Request(probe, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec):
            return True
    except (TimeoutError, urllib.error.URLError, urllib.error.HTTPError, OSError):
        return False


class SlmGoldenTests(unittest.TestCase):
    def test_golden_task_count(self):
        self.assertEqual(len(GOLDEN_TASKS), 10)
        categories = {task.category for task in GOLDEN_TASKS}
        self.assertIn("trivial_docs", categories)
        self.assertIn("localized_bug_fix", categories)
        self.assertIn("architecture", categories)
        self.assertIn("ui_visual", categories)

    def test_classify_diversity_not_collapsed(self):
        config = load_slm_config()
        if not _ollama_reachable(config.endpoint):
            self.skipTest("Ollama endpoint unreachable — skipping live golden eval")

        analyzer = LocalSlmSemanticAnalyzer(config)
        results: list[tuple[str, ChangeScope, float]] = []
        failures: list[str] = []

        for task in GOLDEN_TASKS:
            features, reason, source = analyze_with_fallback(
                analyzer,
                TaskAnalysisInput(user_request=task.prompt, facts=RoutingFacts()),
            )
            if features is None:
                failures.append(f"{task.name}: {source} — {reason}")
                continue
            results.append((task.name, features.scope, features.confidence))

        self.assertGreater(
            len(results),
            0,
            f"no successful classifications; failures: {failures}",
        )

        scopes = [scope for _, scope, _ in results]
        confidences = [confidence for _, _, confidence in results]

        if all(scope == ChangeScope.LOCALIZED for scope in scopes):
            detail = ", ".join(f"{name}={scope.value}" for name, scope, _ in results)
            self.fail(f"collapse: every successful classify has scope=localized ({detail})")

        if all(confidence == 0.95 for confidence in confidences):
            detail = ", ".join(f"{name}={confidence:.2f}" for name, _, confidence in results)
            self.fail(f"collapse: every confidence is 0.95 ({detail})")


if __name__ == "__main__":
    unittest.main()
