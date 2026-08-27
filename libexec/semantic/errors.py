"""Typed errors for semantic analysis — SLM failures never block routing."""

from __future__ import annotations


class SemanticError(Exception):
    """Base semantic-layer error."""


class SemanticDisabledError(SemanticError):
    """SLM analysis is disabled in configuration."""


class SemanticUnavailableError(SemanticError):
    """SLM endpoint unreachable or unsupported."""


class SemanticTimeoutError(SemanticError):
    """SLM request timed out."""


class SemanticValidationError(SemanticError):
    """SLM output failed schema validation."""


class SemanticLowConfidenceError(SemanticError):
    """SLM confidence below configured threshold."""
