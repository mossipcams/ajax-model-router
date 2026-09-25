"""Schema-constrained RouteDecision — typed values only.

The sensor evaluates eligible execution routes directly (route + probabilities
+ complexity/ambiguity) instead of generating TaskFeatures. Parsing is strict:
anything that is not a clean decision is rejected so policy can fall back to
deterministic routing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ContextBudget(str, Enum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    UNKNOWN = "unknown"


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
    """One sensor decision: which eligible route, with probabilities and scores.

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
    """Compact expected-output description for sensor responses."""
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
