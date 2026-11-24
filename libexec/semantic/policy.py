"""Deterministic routing policy — the sensor is advisory; it never picks the final model.

Pipeline: facts → hard constraints (eligibility) → hard overrides → QWEN first,
then HAIKU, then CURSOR. QWEN is local and cheap, so nothing diverts away from
it except an explicit user ask, recorded spec uncertainty, or retry escalation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from semantic.facts import RoutingFacts
from semantic.schema import RouteDecision

# Model IDs live only in the SKILL.md Model Registry table (with per-row notes);
# this reads it so the router never carries its own copy.
REGISTRY_TABLE = Path(__file__).resolve().parents[2] / "skills" / "model-router" / "SKILL.md"


def load_registry(path: Path = REGISTRY_TABLE) -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
    """(key -> (agent, model ID), key -> base URL) from the registry table rows."""
    text = path.read_text()
    section = text.partition("## Model Registry")[2].partition("\n## ")[0]
    registry: dict[str, tuple[str, str]] = {}
    base_urls: dict[str, str] = {}
    for line in section.splitlines():
        if not line.startswith("| `"):
            continue
        key, model_id, agent, _provider, base_url = (
            cell.strip().strip("`") for cell in line.split("|")[1:6]
        )
        registry[key] = (agent, model_id)
        if base_url.startswith("http"):
            base_urls[key] = base_url
    if not registry:
        raise RuntimeError(f"no Model Registry rows in {path}")
    return registry, base_urls


REGISTRY, BASE_URLS = load_registry()

# Canonical route order (cheap → strongest), used for tie-breaking and logs.
ROUTE_ORDER: tuple[str, ...] = ("DEEPSEEK", "QWEN", "HAIKU", "CURSOR", "CODEX")

# Routes only an explicit user ask may select; never reached by fallback or retry.
EXPLICIT_ONLY: frozenset[str] = frozenset({"CODEX"})

# Retry after a failed attempt moves to the next cheap route, never to a premium one.
RETRY_NEXT: dict[str, tuple[str, ...]] = {
    "DEEPSEEK": ("HAIKU", "CURSOR"),
    "QWEN": ("HAIKU", "CURSOR"),
    "HAIKU": ("CURSOR",),
    "CURSOR": ("HAIKU",),
}

# Bare IDs (the part after "provider/") stay valid for explicit user overrides.
MODEL_KEY_BY_ID: dict[str, str] = {
    alias: key
    for key, (_, model_id) in REGISTRY.items()
    for alias in {model_id, model_id.rpartition("/")[2]}
}


def fallback_chain(primary: str, eligible: tuple[str, ...]) -> tuple[str, ...]:
    """Routes to try, in order, when `primary` is unavailable (quota, auth, missing tool).

    Stronger routes after the primary first, then cheaper ones; never the primary
    itself, never DEEPSEEK unless the primary was DEEPSEEK (its lane is bounded),
    and never an explicit-only route (CODEX) unless it was the primary.
    """
    if primary not in ROUTE_ORDER:
        return ()
    start = ROUTE_ORDER.index(primary)
    ordered = ROUTE_ORDER[start + 1 :] + ROUTE_ORDER[:start]
    return tuple(
        key
        for key in ordered
        if key in eligible
        and (key != "DEEPSEEK" or primary == "DEEPSEEK")
        and key not in EXPLICIT_ONLY
    )

@dataclass(frozen=True)
class RoutingDecision:
    agent: str
    model_key: str
    model_id: str
    risk: str
    rule_id: str
    reason: str
    fallback: str
    fallback_chain: tuple[str, ...] = field(default_factory=tuple)
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
            "fallback_chain": list(self.fallback_chain),
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
        or (facts.is_retry and facts.previous_model_key in RETRY_NEXT)
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
        routes = [key for key in routes if key != "DEEPSEEK"]
    return tuple(routes)


def deterministic_default(
    facts: RoutingFacts, eligible: tuple[str, ...]
) -> tuple[str, str]:
    """QWEN first (local, cheap), then HAIKU, then CURSOR, then anything eligible."""
    if "QWEN" in eligible:
        return "QWEN", "default implementation: local QWEN first"
    if "HAIKU" in eligible:
        return "HAIKU", "QWEN unavailable; fallback implementation"
    if "CURSOR" in eligible:
        return "CURSOR", "QWEN and HAIKU unavailable; fallback implementation"
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
    eligible = eligible if eligible is not None else eligible_routes(facts)
    chain = fallback_chain(key, eligible)
    return RoutingDecision(
        agent=agent,
        model_key=key,
        model_id=model_id,
        risk=_risk_level(facts),
        rule_id=rule_id,
        reason=reason,
        fallback=chain[0] if chain else "STOP",
        fallback_chain=chain,
        sensor_used=sensor is not None,
        sensor_confidence=sensor.confidence if sensor else None,
        eligible_routes=eligible,
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
    """Hard overrides first, then QWEN-first availability order.

    `sensor` and `confidence_threshold` are accepted for caller compatibility
    but never change the route: QWEN is always tried first when eligible.
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
            "DEEPSEEK",
            "R-DEEPSEEK-SPEC",
            "recorded unresolved specification or architecture uncertainty",
            facts,
            eligible=eligible,
        )
    if facts.is_retry and facts.previous_model_key in RETRY_NEXT:
        for key in RETRY_NEXT[facts.previous_model_key]:
            if key in eligible:
                return _decision(
                    key,
                    "R-RETRY-ESCALATE",
                    f"retry after failed {facts.previous_model_key} attempt moves to {key}",
                    facts,
                    eligible=eligible,
                )
        # No cheap escalation target is up: fall through to the default order.

    # The sensor is no longer consulted for the pick: QWEN always goes first.
    route, reason = deterministic_default(facts, eligible)
    rule_id = {
        "QWEN": "R-QWEN",
        "HAIKU": "R-HAIKU",
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
