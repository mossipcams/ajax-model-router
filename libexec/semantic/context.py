"""Context requirement strategy — category labels only, no file discovery."""

from __future__ import annotations

from semantic.facts import RoutingFacts
from semantic.schema import (
    ContextBudget,
    ContextRequirements,
    TaskFeatures,
    TaskType,
)


def derive_context_requirements(
    features: TaskFeatures | None,
    facts: RoutingFacts,
) -> ContextRequirements:
    """Deterministic context categories from validated features + facts."""
    budget = ContextBudget.UNKNOWN
    architecture_docs = False
    recent_diff = bool(facts.changed_files or facts.diff_line_count)
    related_tests = False
    git_history = False
    subsystems: list[str] = []

    if features:
        budget = features.likely_context_size
        if features.task_type in {TaskType.ARCHITECTURE, TaskType.INVESTIGATION}:
            architecture_docs = True
            git_history = True
        if features.task_type in {TaskType.BUG_FIX, TaskType.TEST, TaskType.CI_FAILURE}:
            related_tests = True
        if features.requires_repo_discovery:
            git_history = True
        if features.scope.value in {"cross_module", "repo_wide"}:
            git_history = True
        for domain in features.domains:
            subsystems.append(domain.value)

    if facts.known_subsystem:
        subsystems.append(facts.known_subsystem)
    if facts.test_command:
        related_tests = True

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
    features: TaskFeatures | None,
) -> list[str]:
    """Copy-ready VERIFY expectations from context_strategy + facts."""
    verify: list[str] = []
    if facts.test_command:
        verify.append(facts.test_command)
    elif context.related_tests:
        verify.append("Run related unit or integration tests")
    if features and features.requires_visual_validation:
        verify.append("Browser or visual validation of UI changes")
    return verify
