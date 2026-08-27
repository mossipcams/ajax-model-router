"""Schema-constrained TaskFeatures / FailureFeatures — typed enums only."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskType(str, Enum):
    BUG_FIX = "bug_fix"
    FEATURE = "feature"
    REFACTOR = "refactor"
    ARCHITECTURE = "architecture"
    TEST = "test"
    DOCUMENTATION = "documentation"
    INVESTIGATION = "investigation"
    CODE_REVIEW = "code_review"
    CI_FAILURE = "ci_failure"
    UNKNOWN = "unknown"


class TaskDomain(str, Enum):
    FRONTEND = "frontend"
    RUST_BACKEND = "rust_backend"
    MOBILE_WEB = "mobile_web"
    GIT = "git"
    GITHUB = "github"
    TESTING = "testing"
    CI = "ci"
    ARCHITECTURE = "architecture"
    TOOLING = "tooling"
    UNKNOWN = "unknown"


class Complexity(str, Enum):
    TRIVIAL = "trivial"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ChangeScope(str, Enum):
    LOCALIZED = "localized"
    FEATURE = "feature"
    CROSS_MODULE = "cross_module"
    REPO_WIDE = "repo_wide"
    UNKNOWN = "unknown"


class ReasoningDepth(str, Enum):
    SHALLOW = "shallow"
    MEDIUM = "medium"
    DEEP = "deep"
    UNKNOWN = "unknown"


class Uncertainty(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class ContextSize(str, Enum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    UNKNOWN = "unknown"


class TaskRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FailureClass(str, Enum):
    TEST_REGRESSION = "test_regression"
    COMPILE_ERROR = "compile_error"
    CI_FAILURE = "ci_failure"
    TIMEOUT = "timeout"
    ACP_ERROR = "acp_error"
    GIT_CONFLICT = "git_conflict"
    REVIEW_REJECTION = "review_rejection"
    UNKNOWN = "unknown"


class ContextBudget(str, Enum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    UNKNOWN = "unknown"


def _enum(cls: type[Enum], value: Any, field_name: str) -> Enum:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    try:
        return cls(value)
    except ValueError as error:
        raise ValueError(f"unknown {field_name}: {value!r}") from error


def _bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _confidence(value: Any) -> float:
    if isinstance(value, int):
        value = float(value)
    if not isinstance(value, (int, float)):
        raise ValueError("confidence must be a number")
    if not 0.0 <= float(value) <= 1.0:
        raise ValueError("confidence must be in [0.0, 1.0]")
    return float(value)


def _reject_extra(data: dict[str, Any], allowed: set[str]) -> None:
    extra = set(data) - allowed
    if extra:
        raise ValueError(f"unexpected fields: {sorted(extra)}")


@dataclass(frozen=True)
class TaskFeatures:
    task_type: TaskType
    domains: tuple[TaskDomain, ...]
    complexity: Complexity
    scope: ChangeScope
    reasoning_depth: ReasoningDepth
    uncertainty: Uncertainty
    requires_repo_discovery: bool
    requires_visual_validation: bool
    requires_large_context: bool
    likely_context_size: ContextSize
    risk: TaskRisk
    confidence: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskFeatures:
        if not isinstance(data, dict):
            raise ValueError("TaskFeatures must be an object")
        required = {
            "task_type",
            "domains",
            "complexity",
            "scope",
            "reasoning_depth",
            "uncertainty",
            "requires_repo_discovery",
            "requires_visual_validation",
            "requires_large_context",
            "likely_context_size",
            "risk",
            "confidence",
        }
        missing = required - set(data)
        if missing:
            raise ValueError(f"missing required fields: {sorted(missing)}")
        _reject_extra(data, required)

        domains_raw = data["domains"]
        if not isinstance(domains_raw, list) or not domains_raw:
            raise ValueError("domains must be a non-empty list")
        domains = tuple(_enum(TaskDomain, d, "domain") for d in domains_raw)

        return cls(
            task_type=_enum(TaskType, data["task_type"], "task_type"),
            domains=domains,
            complexity=_enum(Complexity, data["complexity"], "complexity"),
            scope=_enum(ChangeScope, data["scope"], "scope"),
            reasoning_depth=_enum(
                ReasoningDepth, data["reasoning_depth"], "reasoning_depth"
            ),
            uncertainty=_enum(Uncertainty, data["uncertainty"], "uncertainty"),
            requires_repo_discovery=_bool(
                data["requires_repo_discovery"], "requires_repo_discovery"
            ),
            requires_visual_validation=_bool(
                data["requires_visual_validation"], "requires_visual_validation"
            ),
            requires_large_context=_bool(
                data["requires_large_context"], "requires_large_context"
            ),
            likely_context_size=_enum(
                ContextSize, data["likely_context_size"], "likely_context_size"
            ),
            risk=_enum(TaskRisk, data["risk"], "risk"),
            confidence=_confidence(data["confidence"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_type": self.task_type.value,
            "domains": [d.value for d in self.domains],
            "complexity": self.complexity.value,
            "scope": self.scope.value,
            "reasoning_depth": self.reasoning_depth.value,
            "uncertainty": self.uncertainty.value,
            "requires_repo_discovery": self.requires_repo_discovery,
            "requires_visual_validation": self.requires_visual_validation,
            "requires_large_context": self.requires_large_context,
            "likely_context_size": self.likely_context_size.value,
            "risk": self.risk.value,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class FailureFeatures:
    failure_class: FailureClass
    domain: TaskDomain
    component: str
    likely_task_related: bool
    retry_same_model: bool
    confidence: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FailureFeatures:
        if not isinstance(data, dict):
            raise ValueError("FailureFeatures must be an object")
        required = {
            "failure_class",
            "domain",
            "component",
            "likely_task_related",
            "retry_same_model",
            "confidence",
        }
        missing = required - set(data)
        if missing:
            raise ValueError(f"missing required fields: {sorted(missing)}")
        _reject_extra(data, required)
        component = data["component"]
        if not isinstance(component, str):
            raise ValueError("component must be a string")
        return cls(
            failure_class=_enum(
                FailureClass, data["failure_class"], "failure_class"
            ),
            domain=_enum(TaskDomain, data["domain"], "domain"),
            component=component,
            likely_task_related=_bool(
                data["likely_task_related"], "likely_task_related"
            ),
            retry_same_model=_bool(data["retry_same_model"], "retry_same_model"),
            confidence=_confidence(data["confidence"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "failure_class": self.failure_class.value,
            "domain": self.domain.value,
            "component": self.component,
            "likely_task_related": self.likely_task_related,
            "retry_same_model": self.retry_same_model,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class ContextRequirements:
    architecture_docs: bool
    recent_diff: bool
    related_tests: bool
    git_history: bool
    likely_subsystems: tuple[str, ...]
    context_budget: ContextBudget

    def to_dict(self) -> dict[str, Any]:
        return {
            "architecture_docs": self.architecture_docs,
            "recent_diff": self.recent_diff,
            "related_tests": self.related_tests,
            "git_history": self.git_history,
            "likely_subsystems": list(self.likely_subsystems),
            "context_budget": self.context_budget.value,
        }


def parse_task_features_json(text: str) -> TaskFeatures:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"malformed JSON: {error}") from error
    return TaskFeatures.from_dict(data)


def parse_failure_features_json(text: str) -> FailureFeatures:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"malformed JSON: {error}") from error
    return FailureFeatures.from_dict(data)
