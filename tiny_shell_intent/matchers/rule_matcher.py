"""Rule-based matcher supporting exact alias and prefix matching with 1-to-many disambiguation."""

import re
from typing import List, Optional, Set
from ..schema import Candidate, MatchSource, CommandIntent
from ..store import KnowledgeBaseStore
from .base import BaseMatcher

# Words indicating that a query is natural language rather than a raw CLI syntax invocation
NATURAL_LANGUAGE_MARKERS = {
    "how", "what", "which", "where", "why", "is", "are", "can", "does", "do",
    "please", "should", "would", "could", "to", "from", "over", "into", "with",
    "without", "after", "before", "immediately", "completely", "recursively",
    "all", "the", "my", "this", "that", "these", "those", "process", "service",
    "running", "started", "stopped", "turned", "on", "off", "folder", "directory",
    "file", "files", "lines", "notes", "machine", "computer", "server", "host",
}


class RuleMatcher(BaseMatcher):
    """Matches queries using exact alias matching and command/alias prefix matching."""

    def __init__(self, store: KnowledgeBaseStore):
        self.store = store

    def match(self, query: str, top_k: int = 3) -> List[Candidate]:
        clean_q = query.strip().lower()
        if not clean_q:
            return []

        candidates: List[Candidate] = []
        seen_ids: Set[str] = set()

        # 1. Exact whole-query alias or command verb match (e.g. "pwd", "cls", "ls -la", "rm -rf")
        exact_matches = self._match_exact(clean_q)
        for cand in exact_matches:
            if cand.intent_id not in seen_ids:
                candidates.append(cand)
                seen_ids.add(cand.intent_id)
            if len(candidates) >= top_k:
                return candidates[:top_k]

        # 2. Genuine CLI command invocation with arguments (e.g., "kill 1234", "curl http://...", "rm file.txt")
        # Must be verified as raw CLI syntax and NOT a natural language sentence
        words = clean_q.split()
        if len(words) >= 2:
            cli_candidates = self._match_cli_invocation(words, clean_q, seen_ids)
            for cand in cli_candidates:
                if cand.intent_id not in seen_ids:
                    candidates.append(cand)
                    seen_ids.add(cand.intent_id)
                if len(candidates) >= top_k:
                    return candidates[:top_k]

        # 3. Prefix matching: only for single tokens or command-like tokens (minimum 2 chars)
        if len(candidates) < top_k and len(words) == 1 and len(clean_q) >= 2:
            prefix_matches = self._match_prefix(clean_q, exclude_ids=seen_ids)
            for cand in prefix_matches:
                if cand.intent_id not in seen_ids:
                    candidates.append(cand)
                    seen_ids.add(cand.intent_id)
                if len(candidates) >= top_k:
                    break

        return candidates[:top_k]

    def _match_exact(self, query: str) -> List[Candidate]:
        """Match query exactly against known aliases or primary command strings."""
        matches: List[Candidate] = []

        # 1. Exact alias match (supporting 1-to-many)
        alias_intent_ids = self.store.get_intent_ids_by_alias(query)
        if alias_intent_ids:
            for iid in alias_intent_ids:
                intent = self.store.get_by_id(iid)
                if intent:
                    # If single unambiguous alias, full 1.0; if multiple, 0.98
                    score = 1.0 if len(alias_intent_ids) == 1 else 0.98
                    matches.append(self._to_candidate(intent, score=score, source=MatchSource.RULE_EXACT.value))
            return matches

        # 2. Exact match against canonical command verb / executable (e.g. "Get-Process", "Clear-Host")
        for intent in self.store.all_intents():
            cmd_norm = intent.command.strip().lower()
            cmd_verb = cmd_norm.split()[0]
            if query == cmd_verb or query == cmd_norm:
                matches.append(self._to_candidate(intent, score=1.0, source=MatchSource.RULE_EXACT.value))

        return matches

    def _match_cli_invocation(self, words: List[str], full_query: str, seen_ids: Set[str]) -> List[Candidate]:
        """Detect and match structured CLI invocations like 'kill 1234' or 'curl http://...'."""
        first_word = words[0]
        arg_tokens = words[1:]

        # Disqualify if query contains natural language marker words
        has_nl_markers = any(w in NATURAL_LANGUAGE_MARKERS for w in arg_tokens)
        if has_nl_markers:
            return []

        # Check if the subsequent arguments look like CLI flags, numbers, paths, or URLs
        is_cli_arg = any(
            w.startswith(("-", "/", "--", "$", ".", "~"))
            or w.isdigit()
            or w.startswith(("http://", "https://"))
            or "\\" in w
            or "/" in w
            for w in arg_tokens
        ) or len(words) == 2

        if not is_cli_arg:
            return []

        # Lookup candidate intents for the first command word
        candidate_ids = self.store.get_intent_ids_by_alias(first_word)
        if not candidate_ids:
            # Check command verbs
            candidate_ids = self.store.command_map.get(first_word, [])

        if not candidate_ids:
            return []

        matches: List[Candidate] = []

        # Disambiguate if multiple intents share the same alias/verb
        # e.g. 'kill 1234' -> proc_kill_id vs 'kill chrome' -> proc_kill_name
        has_numeric_arg = any(w.isdigit() for w in arg_tokens)
        has_recursive_flag = any(w in ("-recurse", "-r", "-rf", "/s") for w in arg_tokens)

        for iid in candidate_ids:
            if iid in seen_ids:
                continue
            intent = self.store.get_by_id(iid)
            if not intent:
                continue

            score = 0.95

            # PID vs process name disambiguation
            if "proc_kill" in iid:
                if has_numeric_arg and iid == "proc_kill_id":
                    score = 0.99
                elif not has_numeric_arg and iid == "proc_kill_name":
                    score = 0.99
                else:
                    score = 0.85

            # Single file vs recursive directory delete disambiguation
            if "file_delete" in iid:
                if has_recursive_flag and iid == "file_delete_recursive":
                    score = 0.99
                elif not has_recursive_flag and iid == "file_delete_single":
                    score = 0.95
                else:
                    score = 0.85

            matches.append(self._to_candidate(intent, score=score, source=MatchSource.RULE_EXACT.value))

        matches.sort(key=lambda c: c.score, reverse=True)
        return matches

    def _match_prefix(self, query: str, exclude_ids: Set[str]) -> List[Candidate]:
        matches: List[Candidate] = []

        for intent in self.store.all_intents():
            if intent.id in exclude_ids:
                continue

            # Check if primary command starts with query
            cmd_verb = intent.command.strip().lower().split()[0]
            if cmd_verb.startswith(query):
                score = min(0.92, 0.78 + 0.14 * (len(query) / max(len(cmd_verb), 1)))
                matches.append(self._to_candidate(intent, score=score, source=MatchSource.RULE_PREFIX.value))
                continue

            # Check if any alias starts with query
            for alias in intent.aliases:
                alias_clean = alias.strip().lower()
                if alias_clean.startswith(query):
                    score = min(0.90, 0.75 + 0.15 * (len(query) / max(len(alias_clean), 1)))
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
            score=round(score, 4),
            source=source,
            risk_level=intent.risk_level.value,
            category=intent.category,
            risk_reason=intent.risk_reason,
            command_template=intent.command,
            is_complete=len(intent.parameter_slots) == 0,
        )
