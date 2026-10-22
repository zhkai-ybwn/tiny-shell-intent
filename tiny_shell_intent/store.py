"""Knowledge base store and indexer for command intents."""

import json
from pathlib import Path
from typing import Dict, List, Optional
from .schema import CommandIntent, RiskLevel, ParameterSlot


class KnowledgeBaseStore:
    """In-memory store for command intents loaded from JSON."""

    def __init__(self, json_path: str | Path):
        self.path = Path(json_path)
        self._intents: Dict[str, CommandIntent] = {}
        # 1-to-many alias and command verb mapping
        self._alias_to_intent_ids: Dict[str, List[str]] = {}
        self._command_to_intent_ids: Dict[str, List[str]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            raise FileNotFoundError(f"Knowledge base file not found at: {self.path.resolve()}")

        with open(self.path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for item in data:
            risk = RiskLevel(item.get("risk_level", "safe"))

            # Parse parameter slots if defined
            raw_slots = item.get("parameter_slots", [])
            parameter_slots = [
                ParameterSlot(
                    name=s["name"],
                    type=s.get("type", "string"),
                    required=s.get("required", True),
                    placeholder=s.get("placeholder", ""),
                    description=s.get("description", ""),
                )
                for s in raw_slots
            ]

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
                parameter_slots=parameter_slots,
            )
            self._intents[intent.id] = intent

            # Index aliases (lowercased) - supporting 1-to-many mappings
            for alias in intent.aliases:
                clean_alias = alias.strip().lower()
                if clean_alias:
                    id_list = self._alias_to_intent_ids.setdefault(clean_alias, [])
                    if intent.id not in id_list:
                        id_list.append(intent.id)

            # Index primary command verb or binary
            cmd_lower = intent.command.strip().lower()
            verb = cmd_lower.split()[0] if cmd_lower else ""
            if verb:
                v_list = self._command_to_intent_ids.setdefault(verb, [])
                if intent.id not in v_list:
                    v_list.append(intent.id)

    def get_by_id(self, intent_id: str) -> Optional[CommandIntent]:
        return self._intents.get(intent_id)

    def all_intents(self) -> List[CommandIntent]:
        return list(self._intents.values())

    def get_intent_ids_by_alias(self, alias: str) -> List[str]:
        """Get all intent IDs associated with an alias (1-to-many)."""
        return self._alias_to_intent_ids.get(alias.strip().lower(), [])

    @property
    def alias_map(self) -> Dict[str, List[str]]:
        return self._alias_to_intent_ids

    @property
    def command_map(self) -> Dict[str, List[str]]:
        return self._command_to_intent_ids

    def __len__(self) -> int:
        return len(self._intents)
