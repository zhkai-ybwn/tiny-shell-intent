"""Tiny Shell Intent: Windows Local Command Semantic Recognition PoC."""

from .schema import CommandIntent, Candidate, QueryResult, RiskLevel, MatchSource
from .store import KnowledgeBaseStore
from .engine import IntentEngine
from .risk import evaluate_command_risk, format_risk_badge

__version__ = "0.1.0"

__all__ = [
    "CommandIntent",
    "Candidate",
    "QueryResult",
    "RiskLevel",
    "MatchSource",
    "KnowledgeBaseStore",
    "IntentEngine",
    "evaluate_command_risk",
    "format_risk_badge",
]
