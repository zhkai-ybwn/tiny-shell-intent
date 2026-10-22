"""Fuzzy string matcher using RapidFuzz."""

from typing import List
from rapidfuzz import fuzz
from ..schema import Candidate, MatchSource, CommandIntent
from ..store import KnowledgeBaseStore
from .base import BaseMatcher


class FuzzyMatcher(BaseMatcher):
    """Matches queries using fuzzy string metrics across aliases, commands, keywords and phrases."""

    def __init__(self, store: KnowledgeBaseStore):
        self.store = store

    def match(self, query: str, top_k: int = 3) -> List[Candidate]:
        clean_q = query.strip().lower()
        if not clean_q:
            return []

        scored_candidates: List[tuple[float, CommandIntent]] = []

        for intent in self.store.all_intents():
            score = self._compute_intent_fuzzy_score(clean_q, intent)
            if score > 0.20:  # Noise threshold
                scored_candidates.append((score, intent))

        # Sort descending by score
        scored_candidates.sort(key=lambda x: x[0], reverse=True)

        candidates = [
            self._to_candidate(intent, score)
            for score, intent in scored_candidates[:top_k]
        ]
        return candidates

    def _compute_intent_fuzzy_score(self, query: str, intent: CommandIntent) -> float:
        best_score = 0.0
        words = query.split()
        first_word = words[0] if words else query
        query_word_set = set(words)

        # 1. Check aliases & command verb
        cmd_verb = intent.command.strip().lower().split()[0]
        targets_exact = [cmd_verb] + [a.strip().lower() for a in intent.aliases]
        for target in targets_exact:
            r = fuzz.ratio(query, target) / 100.0
            best_score = max(best_score, r)

            # If query is a short command or abbreviation, allow WRatio
            if len(words) <= 2:
                wr = fuzz.WRatio(query, target) / 100.0
                best_score = max(best_score, wr)

            # Check typo on first command word if multi-word query (e.g. "stopp-procss chrome")
            if len(words) > 1:
                pr = fuzz.ratio(first_word, target) / 100.0
                if pr > 0.75:
                    best_score = max(best_score, pr * 0.90)

        # 2. Check intent phrases using token_sort_ratio (penalizes length mismatch)
        for phrase in intent.intent_phrases:
            phrase_clean = phrase.strip().lower()
            tsr = fuzz.token_sort_ratio(query, phrase_clean) / 100.0
            r = fuzz.ratio(query, phrase_clean) / 100.0
            best_score = max(best_score, tsr * 0.95, r * 0.95)

        # 3. Check keywords with word coverage
        if len(words) == 1:
            for kw in intent.keywords:
                r = fuzz.ratio(query, kw.strip().lower()) / 100.0
                best_score = max(best_score, r * 0.85)
        else:
            kw_set = {k.strip().lower() for k in intent.keywords}
            common = query_word_set.intersection(kw_set)
            if common and words:
                coverage = len(common) / len(words)
                best_score = max(best_score, coverage * 0.70)

        # 4. Check description with token_sort_ratio
        desc_score = fuzz.token_sort_ratio(query, intent.description.lower()) / 100.0
        best_score = max(best_score, desc_score * 0.70)

        return min(1.0, max(0.0, best_score))

    def _to_candidate(self, intent: CommandIntent, score: float) -> Candidate:
        return Candidate(
            command=intent.command,
            intent_id=intent.id,
            description=intent.description,
            score=round(score, 4),
            source=MatchSource.FUZZY.value,
            risk_level=intent.risk_level.value,
            category=intent.category,
            risk_reason=intent.risk_reason,
            command_template=intent.command,
            is_complete=len(intent.parameter_slots) == 0,
        )
