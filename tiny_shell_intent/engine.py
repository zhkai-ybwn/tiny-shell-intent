"""IntentEngine combining Rule, Fuzzy, and Model matchers into a unified pipeline."""

import re
import time
from pathlib import Path
from typing import Dict, List, Optional
from .schema import Candidate, MatchSource, QueryResult, RiskLevel
from .store import KnowledgeBaseStore
from .matchers.rule_matcher import RuleMatcher
from .matchers.fuzzy_matcher import FuzzyMatcher
from .matchers.model_matcher import ModelMatcher


class IntentEngine:
    """Unified semantic intent recognition engine for Windows PowerShell 7."""

    def __init__(
        self,
        kb_path: str | Path = "data/knowledge_base.json",
        model_path: str | Path = "./models/potion-base-2M",
        offline_mode: bool = True,
    ):
        self.store = KnowledgeBaseStore(kb_path)
        self.rule_matcher = RuleMatcher(self.store)
        self.fuzzy_matcher = FuzzyMatcher(self.store)
        self.model_matcher = ModelMatcher(
            self.store,
            model_name_or_path=str(model_path),
            offline_mode=offline_mode,
        )

    def search(
        self,
        query: str,
        top_k: int = 3,
        mode: str = "hybrid",
        ood_threshold: float = 0.42,
    ) -> QueryResult:
        """Search command intent knowledge base for top matching candidates.

        Args:
            query: User input query string.
            top_k: Max candidate commands to return.
            mode: 'hybrid', 'rule', 'fuzzy', or 'model'.
            ood_threshold: Score threshold below which queries are treated as out-of-domain.

        Returns:
            QueryResult containing top candidate commands and execution metadata.
        """
        start_time = time.perf_counter()

        # Check empty or whitespace query
        if not query or not query.strip():
            elapsed = (time.perf_counter() - start_time) * 1000
            return QueryResult(
                query=query,
                candidates=[],
                latency_ms=elapsed,
                mode=mode,
                is_empty=True,
            )

        clean_q = query.strip()

        # Check pure punctuation / symbols
        if not re.search(r"[a-zA-Z0-9]", clean_q):
            elapsed = (time.perf_counter() - start_time) * 1000
            return QueryResult(
                query=query,
                candidates=[],
                latency_ms=elapsed,
                mode=mode,
                is_out_of_domain=True,
            )

        # Dispatch single-mode search
        if mode == "rule":
            candidates = self.rule_matcher.match(clean_q, top_k=top_k)
            elapsed = (time.perf_counter() - start_time) * 1000
            return QueryResult(query=query, candidates=candidates, latency_ms=elapsed, mode=mode)

        if mode == "fuzzy":
            candidates = self.fuzzy_matcher.match(clean_q, top_k=top_k)
            elapsed = (time.perf_counter() - start_time) * 1000
            return QueryResult(query=query, candidates=candidates, latency_ms=elapsed, mode=mode)

        if mode == "model":
            candidates = self.model_matcher.match(clean_q, top_k=top_k)
            elapsed = (time.perf_counter() - start_time) * 1000
            return QueryResult(query=query, candidates=candidates, latency_ms=elapsed, mode=mode)

        # Hybrid search fusion
        candidates, is_ood = self._hybrid_fusion(clean_q, top_k=top_k, ood_threshold=ood_threshold)
        elapsed = (time.perf_counter() - start_time) * 1000

        return QueryResult(
            query=query,
            candidates=candidates,
            latency_ms=elapsed,
            mode="hybrid",
            is_out_of_domain=is_ood,
        )

    def _hybrid_fusion(
        self,
        query: str,
        top_k: int = 3,
        ood_threshold: float = 0.42,
    ) -> tuple[List[Candidate], bool]:
        """Combine rule, fuzzy, and embedding matchers."""
        # 1. Check exact rule match
        rule_candidates = self.rule_matcher.match(query, top_k=top_k)
        exact_rule = next(
            (c for c in rule_candidates if c.source == MatchSource.RULE_EXACT.value),
            None,
        )

        # 2. Retrieve model & fuzzy candidates
        # Fetch slightly more candidates from model and fuzzy to allow re-ranking fusion
        model_candidates = self.model_matcher.match(query, top_k=10)
        fuzzy_candidates = self.fuzzy_matcher.match(query, top_k=10)

        # Maps for quick score access
        model_map: Dict[str, float] = {c.intent_id: c.score for c in model_candidates}
        fuzzy_map: Dict[str, float] = {c.intent_id: c.score for c in fuzzy_candidates}
        rule_map: Dict[str, Candidate] = {c.intent_id: c for c in rule_candidates}

        # Gather all candidate intent IDs
        all_intent_ids = set(model_map.keys()) | set(fuzzy_map.keys()) | set(rule_map.keys())

        # Determine query nature: conversational natural language vs CLI command-line / abbreviation
        nl_indicators = {
            "how", "what", "which", "where", "why", "is", "are", "can", "does", "do",
            "my", "the", "a", "an", "to", "in", "on", "for", "of", "from", "with",
        }
        tokens = set(query.lower().split())
        is_conversational_nl = (
            len(tokens.intersection(nl_indicators)) >= 2
            or any(query.lower().startswith(p) for p in ("how ", "what ", "where ", "which ", "is ", "can ", "does ", "see if "))
        )

        scored_pool: List[tuple[float, str, str]] = []  # (fused_score, intent_id, primary_source)

        for intent_id in all_intent_ids:
            s_model = model_map.get(intent_id, 0.0)
            s_fuzzy = fuzzy_map.get(intent_id, 0.0)
            rule_cand = rule_map.get(intent_id)

            if rule_cand and rule_cand.source == MatchSource.RULE_EXACT.value:
                # Exact rule match always gets top score
                scored_pool.append((1.0, intent_id, MatchSource.RULE_EXACT.value))
                continue

            if rule_cand and rule_cand.source == MatchSource.RULE_PREFIX.value:
                s_rule = rule_cand.score
            else:
                s_rule = 0.0

            if is_conversational_nl:
                # Natural language questions favor model semantics
                fused = 0.65 * s_model + 0.25 * s_fuzzy + 0.10 * s_rule
                src = MatchSource.MODEL.value if s_model >= s_fuzzy else MatchSource.FUZZY.value
            else:
                # CLI command-line or short queries: fuzzy typos and abbreviations take precedence
                if s_fuzzy >= 0.80:
                    fused = 0.70 * s_fuzzy + 0.20 * s_model + 0.10 * s_rule
                    src = MatchSource.FUZZY.value
                else:
                    fused = 0.45 * s_model + 0.45 * s_fuzzy + 0.10 * s_rule
                    src = MatchSource.FUZZY.value if s_fuzzy >= s_model else MatchSource.MODEL.value

            scored_pool.append((fused, intent_id, src))

        # Sort descending by fused score
        scored_pool.sort(key=lambda x: x[0], reverse=True)

        # Check out-of-domain condition
        is_ood = False
        top_score = scored_pool[0][0] if scored_pool else 0.0
        if not exact_rule and top_score < ood_threshold:
            is_ood = True

        # Build final candidate list
        final_candidates: List[Candidate] = []
        for score, intent_id, source in scored_pool[:top_k]:
            intent = self.store.get_by_id(intent_id)
            if not intent:
                continue

            final_candidates.append(
                Candidate(
                    command=intent.command,
                    intent_id=intent.id,
                    description=intent.description,
                    score=round(score, 4),
                    source=source,
                    risk_level=intent.risk_level.value,
                    category=intent.category,
                    risk_reason=intent.risk_reason,
                )
            )

        return final_candidates, is_ood
