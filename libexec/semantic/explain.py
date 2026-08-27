"""Structured routing explanation — no chain-of-thought."""

from __future__ import annotations

from typing import Any

from semantic.context import ContextRequirements
from semantic.facts import RoutingFacts
from semantic.policy import RoutingDecision
from semantic.schema import TaskFeatures


def build_explanation(
    *,
    facts: RoutingFacts,
    features: TaskFeatures | None,
    decision: RoutingDecision,
    context: ContextRequirements,
    slm_confidence: float | None = None,
    fallback_reason: str | None = None,
    analysis_source: str = "none",
) -> dict[str, Any]:
    """Inspectable fields only — facts, features, rule, model, context."""
    return {
        "facts": facts.to_dict(),
        "task_features": features.to_dict() if features else None,
        "slm_confidence": slm_confidence,
        "analysis_source": analysis_source,
        "fallback_reason": fallback_reason,
        "matched_rule": decision.rule_id,
        "selected_agent": decision.agent,
        "selected_model_key": decision.model_key,
        "selected_model_id": decision.model_id,
        "risk": decision.risk,
        "reason": decision.reason,
        "context_strategy": context.to_dict(),
    }
