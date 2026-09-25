#!/usr/bin/env python3
"""Live Laya golden eval — skipped when Laya is unreachable (no CI dependency)."""

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
    LayaAnalyzer,
    TaskAnalysisInput,
    analyze_with_fallback,
)
from semantic.config import load_laya_config  # noqa: E402
from semantic.facts import RoutingFacts  # noqa: E402


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


def _laya_reachable(endpoint: str, timeout_sec: float = 2.0) -> bool:
    """Probe the Laya endpoint base URL derived from the /v1/systemone URL."""
    base = endpoint.split("/v1/")[0].rstrip("/")
    probe = f"{base}/"
    request = urllib.request.Request(probe, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec):
            return True
    except (TimeoutError, urllib.error.URLError, urllib.error.HTTPError, OSError):
        return False


class LayaGoldenTests(unittest.TestCase):
    def test_golden_task_count(self):
        self.assertEqual(len(GOLDEN_TASKS), 10)
        categories = {task.category for task in GOLDEN_TASKS}
        self.assertIn("trivial_docs", categories)
        self.assertIn("localized_bug_fix", categories)
        self.assertIn("architecture", categories)
        self.assertIn("ui_visual", categories)

    def test_route_diversity_not_collapsed(self):
        config = load_laya_config()
        if not _laya_reachable(config.endpoint):
            self.skipTest("Laya endpoint unreachable — skipping live golden eval")

        analyzer = LayaAnalyzer(config)
        results: list[tuple[str, str, float]] = []
        failures: list[str] = []

        for task in GOLDEN_TASKS:
            decision, reason, source = analyze_with_fallback(
                analyzer,
                TaskAnalysisInput(
                    user_request=task.prompt,
                    facts=RoutingFacts(user_request=task.prompt),
                    eligible_routes=("MINIMAX", "QWEN", "CURSOR", "GLM", "CODEX", "OPUS"),
                ),
            )
            if decision is None:
                failures.append(f"{task.name}: {source} — {reason}")
                continue
            results.append((task.name, decision.route, decision.confidence))

        self.assertGreater(
            len(results),
            0,
            f"no successful route decisions; failures: {failures}",
        )

        routes = [route for _, route, _ in results]
        confidences = [confidence for _, _, confidence in results]

        if len(set(routes)) == 1:
            detail = ", ".join(f"{name}={route}" for name, route, _ in results)
            self.fail(f"collapse: every successful decision picked {routes[0]} ({detail})")

        if all(confidence == confidences[0] for confidence in confidences):
            detail = ", ".join(
                f"{name}={confidence:.2f}" for name, _, confidence in results
            )
            self.fail(f"collapse: every confidence is identical ({detail})")


if __name__ == "__main__":
    unittest.main()
