"""Tiny Shell Intent: Windows Local Command Semantic Recognition PoC."""

from .schema import (
    CommandIntent,
    Candidate,
    QueryResult,
    RiskLevel,
    MatchSource,
    ConfidenceLevel,
    ParameterSlot,
)
from .store import KnowledgeBaseStore
from .engine import IntentEngine
from .risk import evaluate_command_risk, format_risk_badge, audit_knowledge_base_risks
from .parameters import extract_parameters_from_query, render_command_safely, escape_powershell_literal

__version__ = "0.1.0"

__all__ = [
    "CommandIntent",
    "Candidate",
    "QueryResult",
    "RiskLevel",
    "MatchSource",
    "ConfidenceLevel",
    "ParameterSlot",
    "KnowledgeBaseStore",
    "IntentEngine",
    "evaluate_command_risk",
    "format_risk_badge",
    "audit_knowledge_base_risks",
    "extract_parameters_from_query",
    "render_command_safely",
    "escape_powershell_literal",
]
