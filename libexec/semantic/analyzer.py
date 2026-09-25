"""SemanticAnalyzer implementations — the local GLiNER sensor is advisory;
any failure degrades to deterministic routing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from semantic.config import SemanticConfig, load_semantic_config
from semantic.errors import (
    SemanticDisabledError,
    SemanticError,
    SemanticLowConfidenceError,
)
from semantic.gliner import GlinerAnalyzer
from semantic.facts import RoutingFacts
from semantic.schema import RouteDecision


@dataclass
class TaskAnalysisInput:
    user_request: str
    facts: RoutingFacts
    eligible_routes: tuple[str, ...]


class SemanticAnalyzer(Protocol):
    def analyze_task(self, input_data: TaskAnalysisInput) -> RouteDecision: ...


class DisabledSemanticAnalyzer:
    """Raises SemanticDisabledError — policy uses deterministic fallback."""

    def analyze_task(self, input_data: TaskAnalysisInput) -> RouteDecision:
        raise SemanticDisabledError("semantic analysis disabled")


def create_analyzer(config: SemanticConfig | None = None) -> SemanticAnalyzer:
    """Build the configured sensor: local GLiNER, or disabled."""
    cfg = config or load_semantic_config()
    if not cfg.enabled:
        return DisabledSemanticAnalyzer()
    return GlinerAnalyzer(cfg)


def analyze_with_fallback(
    analyzer: SemanticAnalyzer,
    input_data: TaskAnalysisInput,
) -> tuple[RouteDecision | None, str | None, str]:
    """Return (decision, fallback_reason, analysis_source). Never raises."""
    try:
        decision = analyzer.analyze_task(input_data)
        return decision, None, "sensor"
    except SemanticDisabledError:
        return None, "semantic analysis disabled", "disabled"
    except SemanticLowConfidenceError as error:
        return None, str(error), "sensor_rejected"
    except SemanticError as error:
        return None, str(error), "sensor_failed"


