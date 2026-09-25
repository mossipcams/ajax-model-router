"""Schema-constrained RouteDecision / FailureFeatures — typed values only.

Laya evaluates eligible execution routes directly (route + probabilities +
complexity/ambiguity) instead of generating TaskFeatures. Parsing is strict:
anything that is not a clean decision is rejected so policy can fall back to
deterministic routing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any


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


TASK_DOMAIN_VALUES: tuple[str, ...] = tuple(domain.value for domain in TaskDomain)
TASK_DOMAIN_UNION_ECHO = "|".join(TASK_DOMAIN_VALUES)
ALL_TASK_DOMAIN_VALUES = frozenset(TASK_DOMAIN_VALUES)


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


def _is_task_domain_union_echo(raw: str) -> bool:
    return raw == TASK_DOMAIN_UNION_ECHO


def _split_domain_tokens(raw_domains: list[Any]) -> list[str]:
    tokens: list[str] = []
    for item in raw_domains:
        if not isinstance(item, str):
            raise ValueError("domain must be a string")
        if _is_task_domain_union_echo(item):
            raise ValueError("domains appears to be schema echo, not classification")
        if "|" in item:
            tokens.extend(part for part in item.split("|") if part)
        else:
            tokens.append(item)
    return tokens


def _parse_task_domains(raw_domains: Any) -> tuple[TaskDomain, ...]:
    if not isinstance(raw_domains, list) or not raw_domains:
        raise ValueError("domains must be a non-empty list")

    tokens = _split_domain_tokens(raw_domains)
    if not tokens:
        raise ValueError("domains must contain at least one valid domain")

    parsed: list[TaskDomain] = []
    seen: set[TaskDomain] = set()
    for token in tokens:
        try:
            domain = TaskDomain(token)
        except ValueError as error:
            raise ValueError(f"unknown domain: {token!r}") from error
        if domain in seen:
            continue
        seen.add(domain)
        parsed.append(domain)

    if not parsed:
        raise ValueError("domains must contain at least one valid domain")
    if set(parsed) == ALL_TASK_DOMAIN_VALUES:
        raise ValueError("domains lists entire enum set, not a classification")
    return tuple(parsed)


def _parse_failure_domain(raw_domain: Any) -> TaskDomain:
    if not isinstance(raw_domain, str):
        raise ValueError("domain must be a string")
    if _is_task_domain_union_echo(raw_domain):
        raise ValueError("domain appears to be schema echo, not classification")
    if "|" in raw_domain:
        tokens = [part for part in raw_domain.split("|") if part]
        for token in tokens:
            try:
                return TaskDomain(token)
            except ValueError:
                continue
        raise ValueError(f"unknown domain: {raw_domain!r}")
    return TaskDomain(raw_domain)


def _bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _confidence(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("confidence must be a number")
    confidence = float(value)
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be between 0 and 1")
    return confidence


def _score(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    if not 1 <= value <= 5:
        raise ValueError(f"{field_name} must be between 1 and 5")
    return value


def _reject_extra(data: dict[str, Any], allowed: tuple[str, ...], what: str) -> None:
    extra = set(data) - set(allowed)
    if extra:
        raise ValueError(f"unexpected fields in {what}: {sorted(extra)}")


@dataclass(frozen=True)
class RouteDecision:
    """One Laya decision: which eligible route, with probabilities and scores.

    `route` is a registry key (MINIMAX/QWEN/CURSOR/GLM/CODEX/OPUS), never a provider
    model id. `confidence` is the probability of the selected route.
    """

    route: str
    probabilities: dict[str, float]
    complexity: int
    ambiguity: int
    confidence: float

    @classmethod
    def from_dict(cls, data: Any, allowed_routes: tuple[str, ...]) -> "RouteDecision":
        if not isinstance(data, dict):
            raise ValueError("route decision must be an object")
        _reject_extra(
            data,
            ("route", "probabilities", "complexity", "ambiguity", "confidence"),
            "route decision",
        )
        allowed = tuple(allowed_routes)
        if not allowed:
            raise ValueError("no eligible routes supplied for route decision")

        probabilities: dict[str, float] = {}
        raw_probs = data.get("probabilities")
        if not isinstance(raw_probs, dict) or not raw_probs:
            raise ValueError("probabilities must be a non-empty object")
        for key, value in raw_probs.items():
            if not isinstance(key, str) or key not in allowed:
                raise ValueError(f"unknown route in probabilities: {key!r}")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"probability for {key!r} must be a number")
            prob = float(value)
            if not 0.0 <= prob <= 1.0:
                raise ValueError(f"probability for {key!r} must be between 0 and 1")
            probabilities[key] = prob

        route = data.get("route")
        if not isinstance(route, str) or route not in allowed:
            raise ValueError(f"route must be one of {list(allowed)}")
        if route not in probabilities:
            raise ValueError("probabilities must include the selected route")

        complexity = _score(data.get("complexity"), "complexity")
        ambiguity = _score(data.get("ambiguity"), "ambiguity")
        confidence = probabilities[route]
        if "confidence" in data:
            declared = _confidence(data["confidence"])
            if abs(declared - confidence) > 0.01:
                raise ValueError(
                    "confidence must match the selected route probability"
                )
        return cls(
            route=route,
            probabilities=probabilities,
            complexity=complexity,
            ambiguity=ambiguity,
            confidence=confidence,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "route": self.route,
            "probabilities": dict(self.probabilities),
            "complexity": self.complexity,
            "ambiguity": self.ambiguity,
            "confidence": self.confidence,
        }


def route_decision_json_schema(allowed_routes: tuple[str, ...]) -> dict[str, Any]:
    """Compact expected-output description embedded in the Laya request."""
    return {
        "route": "one of the eligible route keys",
        "probabilities": {
            key: "number 0..1, probability this route is the right executor"
            for key in allowed_routes
        },
        "complexity": "integer 1-5 (1 trivial, 5 very complex)",
        "ambiguity": "integer 1-5 (1 none, 5 fundamental)",
        "allowed_routes": list(allowed_routes),
    }


def parse_route_decision_json(
    text: str, allowed_routes: tuple[str, ...]
) -> RouteDecision:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"malformed JSON: {error}") from error
    return RouteDecision.from_dict(data, allowed_routes)


@dataclass(frozen=True)
class FailureFeatures:
    failure_class: FailureClass
    domain: TaskDomain
    component: str
    likely_task_related: bool
    retry_same_model: bool
    confidence: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FailureFeatures":
        required = (
            "failure_class",
            "domain",
            "component",
            "likely_task_related",
            "retry_same_model",
            "confidence",
        )
        missing = [key for key in required if key not in data]
        if missing:
            raise ValueError(f"missing required fields: {sorted(missing)}")
        _reject_extra(data, required, "failure features")
        component = data["component"]
        if not isinstance(component, str):
            raise ValueError("component must be a string")
        return cls(
            failure_class=_enum(FailureClass, data["failure_class"], "failure_class"),
            domain=_parse_failure_domain(data["domain"]),
            component=component,
            likely_task_related=_bool(data["likely_task_related"], "likely_task_related"),
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


def failure_features_json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "failure_class": {"type": "string", "enum": [c.value for c in FailureClass]},
            "domain": {"type": "string", "enum": list(TASK_DOMAIN_VALUES)},
            "component": {"type": "string"},
            "likely_task_related": {"type": "boolean"},
            "retry_same_model": {"type": "boolean"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": [
            "failure_class",
            "domain",
            "component",
            "likely_task_related",
            "retry_same_model",
            "confidence",
        ],
        "additionalProperties": False,
    }


def parse_failure_features_json(text: str) -> FailureFeatures:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"malformed JSON: {error}") from error
    if not isinstance(data, dict):
        raise ValueError("FailureFeatures must be an object")
    return FailureFeatures.from_dict(data)


@dataclass(frozen=True)
class ContextRequirements:
    architecture_docs: bool = False
    recent_diff: bool = False
    related_tests: bool = False
    git_history: bool = False
    likely_subsystems: tuple[str, ...] = ()
    context_budget: ContextBudget = ContextBudget.UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        return {
            "architecture_docs": self.architecture_docs,
            "recent_diff": self.recent_diff,
            "related_tests": self.related_tests,
            "git_history": self.git_history,
            "likely_subsystems": list(self.likely_subsystems),
            "context_budget": self.context_budget.value,
        }
