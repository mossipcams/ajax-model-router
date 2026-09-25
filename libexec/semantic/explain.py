"""Structured routing explanation — no chain-of-thought."""

from __future__ import annotations

from typing import Any

from semantic.context import (
    ContextRequirements,
    derive_execution_scope,
    derive_execution_verify,
)
from semantic.facts import RoutingFacts
from semantic.policy import RoutingDecision
from semantic.schema import RouteDecision


def build_explanation(
    *,
    facts: RoutingFacts,
    decision: RoutingDecision,
    context: ContextRequirements,
    sensor: RouteDecision | None = None,
    analysis_source: str = "none",
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    """Inspectable fields only — facts, sensor output, rule, model, context.

    Records enough to evaluate the sensor later: eligible routes, selected route,
    route probabilities/confidence, complexity, ambiguity, whether fallback
    routing was used, and the matched hard override. No chain-of-thought, no
    raw task contents beyond the deterministic facts already logged.
    """
    return {
        "facts": facts.to_dict(),
        "analysis_source": analysis_source,
        "sensor": (
            {
                "route": sensor.route,
                "probabilities": dict(sensor.probabilities),
                "complexity": sensor.complexity,
                "ambiguity": sensor.ambiguity,
                "confidence": sensor.confidence,
            }
            if sensor is not None
            else None
        ),
        "eligible_routes": list(decision.eligible_routes),
        "selected_route": decision.model_key,
        "route_confidence": decision.sensor_confidence,
        "route_probabilities": decision.route_probabilities,
        "complexity": decision.complexity,
        "ambiguity": decision.ambiguity,
        "fallback_used": decision.fallback_reason is not None,
        "fallback_reason": decision.fallback_reason,
        "matched_rule": decision.rule_id,
        "selected_agent": decision.agent,
        "selected_model_key": decision.model_key,
        "selected_model_id": decision.model_id,
        "risk": decision.risk,
        "reason": decision.reason,
        "context_strategy": context.to_dict(),
    }


def build_execution_block(
    *,
    decision: RoutingDecision,
    context: ContextRequirements,
    facts: RoutingFacts,
) -> dict[str, Any]:
    """EXECUTION fields for parents — policy picks agent/model; omit empty SCOPE/VERIFY."""
    block: dict[str, Any] = {
        "AGENT": decision.agent,
        "MODEL": decision.model_id,
        "RISK": decision.risk,
        "REASON": decision.reason,
        "FALLBACK": decision.fallback,
    }
    scope = derive_execution_scope(context, facts)
    verify = derive_execution_verify(context, facts)
    if scope:
        block["SCOPE"] = scope
    if verify:
        block["VERIFY"] = verify
    return block
