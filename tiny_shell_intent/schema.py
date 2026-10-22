"""Data models and schemas for Tiny Shell Intent engine."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List


class RiskLevel(str, Enum):
    SAFE = "safe"
    WARNING = "warning"
    DANGEROUS = "dangerous"


class MatchSource(str, Enum):
    RULE_EXACT = "rule_exact"
    RULE_PREFIX = "rule_prefix"
    FUZZY = "fuzzy"
    MODEL = "model"
    HYBRID = "hybrid"


@dataclass
class CommandIntent:
    """A command intent representation in the knowledge base."""
    id: str
    category: str
    command: str
    aliases: List[str]
    description: str
    keywords: List[str]
    intent_phrases: List[str]
    risk_level: RiskLevel
    risk_reason: Optional[str] = None


@dataclass
class Candidate:
    """A matched command candidate returned by a matcher or the engine."""
    command: str
    intent_id: str
    description: str
    score: float
    source: str
    risk_level: str
    category: str
    risk_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "command": self.command,
            "intent_id": self.intent_id,
            "description": self.description,
            "score": round(self.score, 4),
            "source": self.source,
            "risk_level": self.risk_level,
            "risk_reason": self.risk_reason,
            "category": self.category,
        }


@dataclass
class QueryResult:
    """Result of querying the intent engine."""
    query: str
    candidates: List[Candidate] = field(default_factory=list)
    latency_ms: float = 0.0
    mode: str = "hybrid"
    is_empty: bool = False
    is_out_of_domain: bool = False

    @property
    def top_candidate(self) -> Optional[Candidate]:
        return self.candidates[0] if self.candidates else None
