"""Context requirement strategy — category labels only, no file discovery."""

from __future__ import annotations

from semantic.facts import RoutingFacts
from semantic.schema import (
    ContextBudget,
    ContextRequirements,
    RouteDecision,
)

_FRONTEND_EXTENSIONS = {"html", "css", "js", "jsx", "ts", "tsx", "vue", "svelte"}


def derive_context_requirements(
    decision: RouteDecision | None,
    facts: RoutingFacts,
) -> ContextRequirements:
    """Deterministic context categories from the route decision + facts."""
    budget = ContextBudget.UNKNOWN
    architecture_docs = False
    recent_diff = bool(facts.changed_files or facts.diff_line_count)
    related_tests = False
    git_history = False
    subsystems: list[str] = []

    if decision is not None:
        if decision.route == "GLM":
            architecture_docs = True
            git_history = True
        if decision.complexity >= 4 or decision.ambiguity >= 4:
            git_history = True
        if decision.ambiguity >= 4:
            architecture_docs = True

    if facts.known_subsystem:
        subsystems.append(facts.known_subsystem)
    if facts.test_command:
        related_tests = True
    if facts.is_retry:
        git_history = True
    if facts.diff_line_count > 200 or facts.changed_file_count > 5:
        budget = ContextBudget.LARGE
    elif recent_diff:
        budget = ContextBudget.MEDIUM
    else:
        budget = ContextBudget.SMALL

    return ContextRequirements(
        architecture_docs=architecture_docs,
        recent_diff=recent_diff,
        related_tests=related_tests,
        git_history=git_history,
        likely_subsystems=tuple(sorted(set(subsystems))),
        context_budget=budget,
    )


def derive_execution_scope(
    context: ContextRequirements,
    facts: RoutingFacts,
) -> list[str]:
    """Copy-ready SCOPE labels from validated context — no invented paths."""
    labels: list[str] = []
    seen: set[str] = set()
    for label in context.likely_subsystems:
        if label and label not in seen:
            labels.append(label)
            seen.add(label)
    if facts.known_subsystem and facts.known_subsystem not in seen:
        labels.append(facts.known_subsystem)
    return labels


def derive_execution_verify(
    context: ContextRequirements,
    facts: RoutingFacts,
) -> list[str]:
    """Copy-ready VERIFY expectations from context_strategy + facts."""
    verify: list[str] = []
    if facts.test_command:
        verify.append(facts.test_command)
    elif context.related_tests:
        verify.append("Run related unit or integration tests")
    if facts.file_extensions and set(facts.file_extensions) & _FRONTEND_EXTENSIONS:
        verify.append("Browser or visual validation of UI changes")
    return verify
