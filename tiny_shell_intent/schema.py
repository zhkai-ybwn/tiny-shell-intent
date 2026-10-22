"""Data models and schemas for Tiny Shell Intent engine."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any


class RiskLevel(str, Enum):
    SAFE = "safe"
    WARNING = "warning"
    DANGEROUS = "dangerous"

    @property
    def severity(self) -> int:
        levels = {RiskLevel.SAFE: 1, RiskLevel.WARNING: 2, RiskLevel.DANGEROUS: 3}
        return levels.get(self, 1)

    def __ge__(self, other: "RiskLevel") -> bool:
        if not isinstance(other, RiskLevel):
            return NotImplemented
        return self.severity >= other.severity

    def __gt__(self, other: "RiskLevel") -> bool:
        if not isinstance(other, RiskLevel):
            return NotImplemented
        return self.severity > other.severity

    def __le__(self, other: "RiskLevel") -> bool:
        if not isinstance(other, RiskLevel):
            return NotImplemented
        return self.severity <= other.severity

    def __lt__(self, other: "RiskLevel") -> bool:
        if not isinstance(other, RiskLevel):
            return NotImplemented
        return self.severity < other.severity


class MatchSource(str, Enum):
    RULE_EXACT = "rule_exact"
    RULE_PREFIX = "rule_prefix"
    FUZZY = "fuzzy"
    MODEL = "model"
    HYBRID = "hybrid"


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    REJECTED = "rejected"


@dataclass
class ParameterSlot:
    """Definition of an extractable parameter slot for a command intent."""
    name: str
    type: str  # "int", "string", "hostname", "path"
    required: bool = True
    placeholder: str = ""
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type,
            "required": self.required,
            "placeholder": self.placeholder,
            "description": self.description,
        }


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
    parameter_slots: List[ParameterSlot] = field(default_factory=list)


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
    command_template: str = ""
    rendered_command: Optional[str] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    is_complete: bool = False
    confidence_level: ConfidenceLevel = ConfidenceLevel.HIGH

    def __post_init__(self):
        if not self.command_template:
            self.command_template = self.command
        # If rendered_command is provided, command should point to rendered version
        if self.rendered_command:
            self.command = self.rendered_command

    def to_dict(self) -> dict:
        return {
            "command": self.command,
            "command_template": self.command_template,
            "rendered_command": self.rendered_command,
            "parameters": self.parameters,
            "is_complete": self.is_complete,
            "intent_id": self.intent_id,
            "description": self.description,
            "score": round(self.score, 4),
            "source": self.source,
            "risk_level": self.risk_level,
            "risk_reason": self.risk_reason,
            "category": self.category,
            "confidence_level": self.confidence_level.value,
        }


@dataclass
class QueryResult:
    """Result of querying the intent engine."""
    query: str
    candidates: List[Candidate] = field(default_factory=list)  # Actionable accepted candidates ONLY
    debug_candidates: List[Candidate] = field(default_factory=list)  # Retained for inspection when rejected
    confidence_level: ConfidenceLevel = ConfidenceLevel.HIGH
    is_accepted: bool = True
    is_rejected: bool = False
    rejection_reason: Optional[str] = None
    latency_ms: float = 0.0
    mode: str = "hybrid"
    is_empty: bool = False
    is_out_of_domain: bool = False

    @property
    def top_candidate(self) -> Optional[Candidate]:
        """Return the top actionable accepted candidate, or None if rejected / empty."""
        return self.candidates[0] if self.candidates else None

    @property
    def top_debug_candidate(self) -> Optional[Candidate]:
        """Return the top candidate from debug candidates (for inspection when rejected)."""
        return self.debug_candidates[0] if self.debug_candidates else None
