"""Rule-based matcher supporting exact alias and prefix matching."""

import re
from typing import List, Optional
from ..schema import Candidate, MatchSource, CommandIntent
from ..store import KnowledgeBaseStore
from .base import BaseMatcher


class RuleMatcher(BaseMatcher):
    """Matches queries using exact alias matching and command/alias prefix matching."""

    def __init__(self, store: KnowledgeBaseStore):
        self.store = store

    def match(self, query: str, top_k: int = 3) -> List[Candidate]:
        clean_q = query.strip().lower()
        if not clean_q:
            return []

        candidates: List[Candidate] = []
        seen_ids = set()

        # 1. Exact alias match
        exact_candidate = self._match_exact(clean_q)
        if exact_candidate:
            candidates.append(exact_candidate)
            seen_ids.add(exact_candidate.intent_id)

        # 2. Command word exact match (e.g., "kill 1234", "curl https://...")
        # Only treat as CLI invocation if it's <= 2 words, or contains flags/digits,
        # avoiding hijacking long natural language queries starting with common English verbs like "find", "clear", "start", "set".
        if len(candidates) < top_k:
            words = clean_q.split()
            first_word = words[0]
            is_cli_invocation = False
            if len(words) <= 2:
                is_cli_invocation = True
            elif any(w.startswith(("-", "/", "--", "$")) or w.isdigit() for w in words[1:]):
                is_cli_invocation = True

            if is_cli_invocation and first_word in self.store.alias_map:
                intent_id = self.store.alias_map[first_word]
                if intent_id not in seen_ids:
                    intent = self.store.get_by_id(intent_id)
                    if intent:
                        candidates.append(self._to_candidate(
                            intent=intent,
                            score=0.98,
                            source=MatchSource.RULE_EXACT.value,
                        ))
                        seen_ids.add(intent_id)

        # 3. Prefix matching (minimum 2 chars to avoid noisy single letter matching)
        if len(candidates) < top_k and len(clean_q) >= 2:
            prefix_matches = self._match_prefix(clean_q, exclude_ids=seen_ids)
            for cand in prefix_matches:
                if len(candidates) >= top_k:
                    break
                if cand.intent_id not in seen_ids:
                    candidates.append(cand)
                    seen_ids.add(cand.intent_id)

        return candidates[:top_k]

    def _match_exact(self, query: str) -> Optional[Candidate]:
        # Direct alias index lookup
        if query in self.store.alias_map:
            intent_id = self.store.alias_map[query]
            intent = self.store.get_by_id(intent_id)
            if intent:
                return self._to_candidate(intent, score=1.0, source=MatchSource.RULE_EXACT.value)

        # Check against full command string without params (e.g. "Get-Process")
        for intent in self.store.all_intents():
            cmd_norm = intent.command.strip().lower()
            cmd_verb = cmd_norm.split()[0]
            if query == cmd_verb:
                return self._to_candidate(intent, score=1.0, source=MatchSource.RULE_EXACT.value)

        return None

    def _match_prefix(self, query: str, exclude_ids: set) -> List[Candidate]:
        matches: List[Candidate] = []

        for intent in self.store.all_intents():
            if intent.id in exclude_ids:
                continue

            # Check if primary command starts with query
            cmd_verb = intent.command.strip().lower().split()[0]
            if cmd_verb.startswith(query):
                score = min(0.95, 0.80 + 0.15 * (len(query) / max(len(cmd_verb), 1)))
                matches.append(self._to_candidate(intent, score=score, source=MatchSource.RULE_PREFIX.value))
                continue

            # Check if any alias starts with query
            for alias in intent.aliases:
                alias_clean = alias.strip().lower()
                if alias_clean.startswith(query):
                    score = min(0.92, 0.78 + 0.14 * (len(query) / max(len(alias_clean), 1)))
                    matches.append(self._to_candidate(intent, score=score, source=MatchSource.RULE_PREFIX.value))
                    break

        # Sort prefix matches by score descending
        matches.sort(key=lambda c: c.score, reverse=True)
        return matches

    def _to_candidate(self, intent: CommandIntent, score: float, source: str) -> Candidate:
        return Candidate(
            command=intent.command,
            intent_id=intent.id,
            description=intent.description,
            score=score,
            source=source,
            risk_level=intent.risk_level.value,
            category=intent.category,
            risk_reason=intent.risk_reason,
        )
