"""Static model capability registry — no fake learned precision."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from semantic.config import ModelCapability, load_capabilities


@dataclass(frozen=True)
class CapabilityQueryResult:
    models: tuple[str, ...]
    data_sufficient: bool
    note: str


class CapabilityRegistry:
    def __init__(self, capabilities: dict[str, ModelCapability] | None = None):
        self._capabilities = capabilities or load_capabilities()

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._capabilities))

    def get(self, key: str) -> ModelCapability | None:
        return self._capabilities.get(key)

    def cheapest_eligible(
        self,
        *,
        min_strength_field: str,
        min_strength: int,
        expected_success_threshold: float | None = None,
    ) -> CapabilityQueryResult:
        """Return cheapest models meeting a static strength floor."""
        if expected_success_threshold is not None:
            return CapabilityQueryResult(
                models=(),
                data_sufficient=False,
                note="historical success rates unavailable; threshold queries need outcome data",
            )
        eligible: list[tuple[int, str]] = []
        for key, cap in self._capabilities.items():
            strength = getattr(cap, min_strength_field, 0)
            if strength >= min_strength:
                eligible.append((cap.cost_tier, key))
        eligible.sort()
        return CapabilityQueryResult(
            models=tuple(key for _, key in eligible),
            data_sufficient=True,
            note="static strength only; no historical success rate",
        )

    def to_dict(self) -> dict[str, dict[str, Any]]:
        return {
            key: {
                "cost_tier": cap.cost_tier,
                "architecture_strength": cap.architecture_strength,
                "localized_implementation_strength": cap.localized_implementation_strength,
                "frontend_strength": cap.frontend_strength,
                "rust_strength": cap.rust_strength,
                "debugging_strength": cap.debugging_strength,
                "test_writing_strength": cap.test_writing_strength,
                "large_context_strength": cap.large_context_strength,
                "review_strength": cap.review_strength,
            }
            for key, cap in self._capabilities.items()
        }
