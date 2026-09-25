"""Deterministic routing policy — the sensor is advisory; it never picks the final model.

Pipeline: facts → hard constraints (eligibility) → optional sensor decision over
eligible routes → deterministic fallback when the sensor is absent/invalid/low
confidence → hard overrides and escalation always win.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from semantic.facts import RoutingFacts
from semantic.schema import RouteDecision

# Registry keys — model IDs live only in the SKILL.md registry table.
REGISTRY: dict[str, tuple[str, str]] = {
    "CODEX": ("codex", "gpt-6-astra"),
    "CURSOR": ("cursor", "composer-2.5"),
    "MINIMAX": ("pi", "minimax-m3"),
    "QWEN": ("pi", "qwen3.8-27b"),
    "GLM": ("pi", "glm-5.2"),
    "OPUS": ("cursor", "claude-opus-5-5"),
}

# Canonical route order (cheap → strongest), used for tie-breaking and logs.
ROUTE_ORDER: tuple[str, ...] = ("MINIMAX", "QWEN", "CURSOR", "GLM", "CODEX", "OPUS")

MODEL_KEY_BY_ID: dict[str, str] = {
    model_id: key for key, (_, model_id) in REGISTRY.items()
}

@dataclass(frozen=True)
class RoutingDecision:
    agent: str
    model_key: str
    model_id: str
    risk: str
    rule_id: str
    reason: str
    fallback: str
    # Sensor metadata (None when deterministic routing was used).
    sensor_used: bool = False
    sensor_confidence: float | None = None
    eligible_routes: tuple[str, ...] = field(default_factory=tuple)
    route_probabilities: dict[str, float] | None = None
    complexity: int | None = None
    ambiguity: int | None = None
    fallback_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "model_key": self.model_key,
            "model_id": self.model_id,
            "risk": self.risk,
            "rule_id": self.rule_id,
            "reason": self.reason,
            "fallback": self.fallback,
            "sensor_used": self.sensor_used,
            "sensor_confidence": self.sensor_confidence,
            "eligible_routes": list(self.eligible_routes),
            "route_probabilities": (
                dict(self.route_probabilities) if self.route_probabilities else None
            ),
            "complexity": self.complexity,
            "ambiguity": self.ambiguity,
            "fallback_reason": self.fallback_reason,
        }


def has_hard_override(facts: RoutingFacts) -> bool:
    """True when a deterministic rule decides the route before any inference."""
    return bool(
        facts.explicit_model
        or facts.user_asked_codex
        or facts.recorded_spec_uncertainty
        or (facts.is_retry and facts.previous_model_key in {"MINIMAX", "CURSOR", "QWEN"})
    )


def _risk_level(facts: RoutingFacts) -> str:
    if facts.is_high_risk():
        return "high"
    if facts.diff_line_count > 200 or facts.changed_file_count > 5:
        return "medium"
    return "low"


def eligible_routes(facts: RoutingFacts) -> tuple[str, ...]:
    """Apply hard constraints: availability, then high-risk lane removal.

    Explicit overrides and retry escalation are applied in `select_route`
    before any sensor inference, so they never reach the fuzzy step.
    """
    routes = [
        key
        for key in ROUTE_ORDER
        if key not in facts.unavailable_routes
    ]
    if facts.is_high_risk():
        routes = [key for key in routes if key != "MINIMAX"]
    return tuple(routes)


def _bounded_trivial(facts: RoutingFacts) -> bool:
    """Existing deterministic cheap-lane test (no semantic input needed)."""
    if facts.changed_file_count == 0 and facts.diff_line_count == 0:
        return False
    if facts.changed_file_count > 2:
        return False
    if facts.diff_line_count > 60:
        return False
    return True


def deterministic_default(
    facts: RoutingFacts, eligible: tuple[str, ...]
) -> tuple[str, str]:
    """Deterministic default: bounded trivial → MINIMAX, else QWEN → CURSOR."""
    if "MINIMAX" in eligible and _bounded_trivial(facts):
        return "MINIMAX", "bounded trivial change within file/line limits"
    if "QWEN" in eligible:
        return "QWEN", "no exception matched; default implementation"
    if "CURSOR" in eligible:
        return "CURSOR", "QWEN unavailable; fallback implementation"
    if eligible:
        return eligible[0], "only remaining eligible route"
    return "CURSOR", "no eligible routes; safe default"


def _decision(
    key: str,
    rule_id: str,
    reason: str,
    facts: RoutingFacts,
    *,
    eligible: tuple[str, ...] | None = None,
    sensor: RouteDecision | None = None,
    fallback_reason: str | None = None,
) -> RoutingDecision:
    agent, model_id = REGISTRY[key]
    return RoutingDecision(
        agent=agent,
        model_key=key,
        model_id=model_id,
        risk=_risk_level(facts),
        rule_id=rule_id,
        reason=reason,
        fallback=key,
        sensor_used=sensor is not None,
        sensor_confidence=sensor.confidence if sensor else None,
        eligible_routes=eligible if eligible is not None else eligible_routes(facts),
        route_probabilities=dict(sensor.probabilities) if sensor else None,
        complexity=sensor.complexity if sensor else None,
        ambiguity=sensor.ambiguity if sensor else None,
        fallback_reason=fallback_reason,
    )


def select_route(
    facts: RoutingFacts,
    *,
    sensor: RouteDecision | None = None,
    sensor_fallback_reason: str | None = None,
    confidence_threshold: float = 0.60,
) -> RoutingDecision:
    """Apply hard constraints, then the sensor's eligible-route pick, then overrides.

    The sensor's route is used only when it names an eligible route at or above
    the confidence threshold; otherwise the existing deterministic default
    applies. Hard overrides (explicit model/agent, Codex ask, spec uncertainty,
    retry escalation) always win over the sensor.
    """
    eligible = eligible_routes(facts)

    # Hard overrides — deterministic, applied before any fuzzy routing.
    if facts.explicit_model:
        key = MODEL_KEY_BY_ID.get(facts.explicit_model)
        if key:
            return _decision(
                key,
                "R-EXPLICIT-MODEL",
                f"explicit user model override: {facts.explicit_model}",
                facts,
                eligible=eligible,
            )
        return RoutingDecision(
            agent=facts.explicit_agent or "custom",
            model_key="CUSTOM",
            model_id=facts.explicit_model,
            risk=_risk_level(facts),
            rule_id="R-EXPLICIT-MODEL",
            reason=f"explicit non-registry model override: {facts.explicit_model}",
            fallback=facts.explicit_model,
            eligible_routes=eligible,
            fallback_reason=sensor_fallback_reason,
        )
    if facts.user_asked_codex:
        return _decision(
            "CODEX",
            "R-CODEX",
            "user explicitly requested Codex",
            facts,
            eligible=eligible,
        )
    if facts.recorded_spec_uncertainty:
        return _decision(
            "GLM",
            "R-GLM",
            "recorded unresolved specification or architecture uncertainty",
            facts,
            eligible=eligible,
        )
    if facts.is_retry and facts.previous_model_key in {"MINIMAX", "CURSOR", "QWEN"}:
        if facts.previous_model_key == "MINIMAX":
            return _decision(
                "GLM",
                "R-RETRY-ESCALATE",
                "retry after failed MINIMAX attempt revises on GLM",
                facts,
                eligible=eligible,
            )
        if "OPUS" in eligible:
            return _decision(
                "OPUS",
                "R-RETRY-ESCALATE",
                "retry after failed implementation attempt escalates to OPUS",
                facts,
                eligible=eligible,
            )
        return _decision(
            "CODEX",
            "R-RETRY-ESCALATE",
            "OPUS unavailable; retry escalates to CODEX",
            facts,
            eligible=eligible,
        )

    # Fuzzy step: the sensor's pick among eligible routes.
    if (
        sensor is not None
        and sensor.route in eligible
        and sensor.confidence >= confidence_threshold
    ):
        return _decision(
            sensor.route,
            "R-SENSOR",
            (
                f"sensor route {sensor.route} (confidence {sensor.confidence:.2f}, "
                f"complexity {sensor.complexity}, ambiguity {sensor.ambiguity})"
            ),
            facts,
            eligible=eligible,
            sensor=sensor,
        )

    # Deterministic fallback (disabled, unavailable, invalid, low confidence).
    if sensor is not None and sensor_fallback_reason is None:
        if sensor.route not in eligible:
            sensor_fallback_reason = f"sensor route {sensor.route} not eligible"
        else:
            sensor_fallback_reason = (
                f"sensor confidence {sensor.confidence:.2f} below threshold "
                f"{confidence_threshold:.2f}"
            )
    route, reason = deterministic_default(facts, eligible)
    rule_id = {
        "MINIMAX": "R-MINIMAX",
        "QWEN": "R-QWEN",
        "CURSOR": "R-CURSOR",
    }.get(route, "R-ELIGIBLE-FALLBACK")
    return _decision(
        route,
        rule_id,
        reason,
        facts,
        eligible=eligible,
        fallback_reason=sensor_fallback_reason,
    )
