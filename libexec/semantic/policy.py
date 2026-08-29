"""Deterministic routing policy — SLM never picks the final model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from semantic.facts import RoutingFacts
from semantic.schema import Complexity, TaskFeatures, TaskRisk, TaskType

# Registry keys — model IDs live only in SKILL.md registry table.
REGISTRY: dict[str, tuple[str, str]] = {
    "CODEX": ("codex", "gpt-5.6-sol"),
    "CURSOR": ("cursor", "composer-2.5"),
    "MINIMAX": ("pi", "opencode-go/minimax-m3"),
    "GLM": ("pi", "opencode-go/glm-5.2"),
}

MODEL_KEY_BY_ID = {model_id: key for key, (_, model_id) in REGISTRY.items()}


@dataclass(frozen=True)
class RoutingDecision:
    agent: str
    model_key: str
    model_id: str
    risk: str
    rule_id: str
    reason: str
    fallback: str
    slm_used: bool
    features: TaskFeatures | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "model_key": self.model_key,
            "model_id": self.model_id,
            "risk": self.risk,
            "rule_id": self.rule_id,
            "reason": self.reason,
            "fallback": self.fallback,
            "slm_used": self.slm_used,
            "task_features": self.features.to_dict() if self.features else None,
        }


def _decision(
    model_key: str,
    rule_id: str,
    reason: str,
    *,
    risk: str = "medium",
    fallback: str = "STOP",
    slm_used: bool = False,
    features: TaskFeatures | None = None,
) -> RoutingDecision:
    agent, model_id = REGISTRY[model_key]
    return RoutingDecision(
        agent=agent,
        model_key=model_key,
        model_id=model_id,
        risk=risk,
        rule_id=rule_id,
        reason=reason,
        fallback=fallback,
        slm_used=slm_used,
        features=features,
    )


def _risk_from_features(features: TaskFeatures | None, facts: RoutingFacts) -> str:
    if features:
        if features.risk == TaskRisk.HIGH:
            return "high"
        if features.risk == TaskRisk.LOW:
            return "low"
    if facts.diff_line_count > 200 or facts.changed_file_count > 5:
        return "medium"
    return "low"


def _matches_minimax_cheap_task(features: TaskFeatures | None, facts: RoutingFacts) -> bool:
    if features:
        if features.task_type not in {
            TaskType.DOCUMENTATION,
            TaskType.TEST,
        } and features.complexity not in {Complexity.TRIVIAL, Complexity.LOW}:
            return False
        if features.reasoning_depth.value == "deep":
            return False
    elif facts.changed_file_count == 0 and facts.diff_line_count == 0:
        return False
    if facts.changed_file_count > 2:
        return False
    if facts.diff_line_count > 60:
        return False
    return True


def select_route(
    features: TaskFeatures | None,
    facts: RoutingFacts,
    *,
    slm_used: bool = False,
) -> RoutingDecision:
    """Apply hard rules first; SLM features inform but never override them."""
    risk = _risk_from_features(features, facts)

    # Hard: explicit user model override
    if facts.explicit_model:
        key = MODEL_KEY_BY_ID.get(facts.explicit_model)
        if key:
            return _decision(
                key,
                "R-EXPLICIT-MODEL",
                f"explicit user model override: {facts.explicit_model}",
                risk=risk,
                slm_used=slm_used,
                features=features,
            )
        agent = facts.explicit_agent or "cursor"
        return RoutingDecision(
            agent=agent,
            model_key="CUSTOM",
            model_id=facts.explicit_model,
            risk=risk,
            rule_id="R-EXPLICIT-MODEL",
            reason=f"explicit user model override: {facts.explicit_model}",
            fallback="STOP",
            slm_used=slm_used,
            features=features,
        )

    # Hard: user asked Codex (SKILL R-CODEX)
    if facts.user_asked_codex:
        return _decision(
            "CODEX",
            "R-CODEX",
            "user explicitly asked Codex to implement",
            risk=risk,
            slm_used=slm_used,
            features=features,
        )

    # Hard: recorded spec/architecture uncertainty (SKILL R-GLM)
    if facts.recorded_spec_uncertainty:
        return _decision(
            "GLM",
            "R-GLM",
            "recorded unresolved specification or architecture uncertainty",
            risk=risk,
            slm_used=slm_used,
            features=features,
        )

    # Hard: retry after failed cheap-model attempt → escalate
    if facts.is_retry and facts.previous_model_key in {"MINIMAX", "CURSOR"}:
        if facts.previous_model_key == "MINIMAX":
            return _decision(
                "GLM",
                "R-RETRY-ESCALATE",
                "retry after failed MINIMAX attempt revises on GLM",
                risk=risk,
                slm_used=slm_used,
                features=features,
            )
        return _decision(
            "CODEX",
            "R-RETRY-ESCALATE",
            "retry after failed cheap-model attempt escalates to CODEX",
            risk=risk,
            slm_used=slm_used,
            features=features,
        )

    if features:
        # Hard: architecture + high complexity → CODEX
        if (
            features.task_type == TaskType.ARCHITECTURE
            and features.complexity == Complexity.HIGH
        ):
            return _decision(
                "CODEX",
                "R-ARCH-HIGH",
                "architecture task with high complexity",
                risk="high",
                slm_used=slm_used,
                features=features,
            )

        # Hard: localized + low/medium complexity → CURSOR
        if (
            features.scope.value == "localized"
            and features.complexity in {Complexity.LOW, Complexity.MEDIUM}
            and features.task_type
            in {TaskType.BUG_FIX, TaskType.FEATURE, TaskType.REFACTOR, TaskType.TEST}
        ):
            return _decision(
                "CURSOR",
                "R-LOCALIZED-IMPL",
                "localized implementation with low/medium complexity",
                risk=risk,
                slm_used=slm_used,
                features=features,
            )

        # Trivial → cheapest qualified (MINIMAX when constraints match)
        if features.complexity == Complexity.TRIVIAL:
            if _matches_minimax_cheap_task(features, facts):
                return _decision(
                    "MINIMAX",
                    "R-MINIMAX",
                    "trivial shallow docs/boilerplate within file/line limits",
                    risk="low",
                    slm_used=slm_used,
                    features=features,
                )
            return _decision(
                "CURSOR",
                "R-TRIVIAL-DEFAULT",
                "trivial task defaulting to CURSOR",
                risk="low",
                slm_used=slm_used,
                features=features,
            )

    # SKILL R-MINIMAX: shallow docs/boilerplate (needs feature signal or bounded diff)
    if features is not None and _matches_minimax_cheap_task(features, facts):
        shallow = features is None or features.reasoning_depth.value in {
            "shallow",
            "unknown",
        }
        docs = features is None or features.task_type in {
            TaskType.DOCUMENTATION,
            TaskType.UNKNOWN,
            TaskType.TEST,
        }
        if shallow and docs:
            return _decision(
                "MINIMAX",
                "R-MINIMAX",
                "routine docs/boilerplate within file/line limits",
                risk="low",
                slm_used=slm_used,
                features=features,
            )

    # Default CURSOR (SKILL R-CURSOR)
    return _decision(
        "CURSOR",
        "R-CURSOR",
        "no exception matched; default implementation",
        risk=risk,
        slm_used=slm_used,
        features=features,
    )
