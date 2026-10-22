"""Knowledge base store and indexer for command intents."""

import json
from pathlib import Path
from typing import Dict, List, Optional
from .schema import CommandIntent, RiskLevel


class KnowledgeBaseStore:
    """In-memory store for command intents loaded from JSON."""

    def __init__(self, json_path: str | Path):
        self.path = Path(json_path)
        self._intents: Dict[str, CommandIntent] = {}
        self._alias_to_intent_id: Dict[str, str] = {}
        self._command_to_intent_id: Dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            raise FileNotFoundError(f"Knowledge base file not found at: {self.path.resolve()}")

        with open(self.path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for item in data:
            risk = RiskLevel(item.get("risk_level", "safe"))
            intent = CommandIntent(
                id=item["id"],
                category=item.get("category", "general"),
                command=item["command"],
                aliases=item.get("aliases", []),
                description=item["description"],
                keywords=item.get("keywords", []),
                intent_phrases=item.get("intent_phrases", []),
                risk_level=risk,
                risk_reason=item.get("risk_reason"),
            )
            self._intents[intent.id] = intent

            # Index aliases (lowercased)
            for alias in intent.aliases:
                clean_alias = alias.strip().lower()
                if clean_alias and clean_alias not in self._alias_to_intent_id:
                    self._alias_to_intent_id[clean_alias] = intent.id

            # Index primary command verb or binary
            cmd_lower = intent.command.strip().lower()
            verb = cmd_lower.split()[0] if cmd_lower else ""
            if verb and verb not in self._command_to_intent_id:
                self._command_to_intent_id[verb] = intent.id

    def get_by_id(self, intent_id: str) -> Optional[CommandIntent]:
        return self._intents.get(intent_id)

    def all_intents(self) -> List[CommandIntent]:
        return list(self._intents.values())

    @property
    def alias_map(self) -> Dict[str, str]:
        return self._alias_to_intent_id

    @property
    def command_map(self) -> Dict[str, str]:
        return self._command_to_intent_id

    def __len__(self) -> int:
        return len(self._intents)
