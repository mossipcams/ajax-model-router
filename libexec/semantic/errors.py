"""Typed errors for semantic analysis — Laya failures never block routing."""

from __future__ import annotations


class SemanticError(Exception):
    """Base semantic-layer error."""


class SemanticDisabledError(SemanticError):
    """Laya analysis is disabled in configuration."""


class SemanticUnavailableError(SemanticError):
    """Laya endpoint unreachable or unsupported."""


class SemanticTimeoutError(SemanticError):
    """Laya request timed out."""


class SemanticValidationError(SemanticError):
    """Laya output failed schema validation."""


class SemanticLowConfidenceError(SemanticError):
    """Laya confidence below configured threshold."""
