#!/usr/bin/env python3
"""Live sensor golden eval — skipped when the local sensor cannot run.

Runs the local GLiNER sensor over the golden task set and asserts route
diversity (no collapse). Skips cleanly when the venv or model is missing so
CI has no external dependency.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libexec"))

from semantic.analyzer import (  # noqa: E402
    TaskAnalysisInput,
    analyze_with_fallback,
    create_analyzer,
)
from semantic.config import load_semantic_config  # noqa: E402
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


def _gliner_available(config) -> bool:
    """Probe the gliner bridge with a trivial task; skip when it cannot run."""
    python = Path(config.python)
    if not python.is_absolute():
        python = ROOT / python
    if not python.is_file():
        return False
    bridge = ROOT / "libexec" / "semantic" / "gliner_bridge.py"
    if not bridge.is_file():
        return False
    payload = json.dumps({
        "task": "Fix a typo in the README.",
        "eligible_routes": ["MINIMAX", "QWEN", "CURSOR", "GLM", "CODEX", "OPUS"],
        "model": config.model,
    })
    try:
        proc = subprocess.run(
            [str(python), str(bridge)],
            input=payload,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(ROOT),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


class SensorGoldenTests(unittest.TestCase):
    def test_golden_task_count(self):
        self.assertEqual(len(GOLDEN_TASKS), 10)
        categories = {task.category for task in GOLDEN_TASKS}
        self.assertIn("trivial_docs", categories)
        self.assertIn("localized_bug_fix", categories)
        self.assertIn("architecture", categories)
        self.assertIn("ui_visual", categories)

    def test_route_diversity_not_collapsed(self):
        config = load_semantic_config()
        if not _gliner_available(config):
            self.skipTest(
                "gliner bridge unavailable (missing venv or model) — "
                "run scripts/setup-gliner, or skip live golden eval"
            )

        analyzer = create_analyzer(config)
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
