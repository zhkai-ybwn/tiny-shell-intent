"""IntentEngine combining Rule, Fuzzy, and Model matchers into a unified pipeline."""

import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from .schema import Candidate, MatchSource, QueryResult, RiskLevel, ConfidenceLevel, CommandIntent
from .store import KnowledgeBaseStore
from .matchers.rule_matcher import RuleMatcher
from .matchers.fuzzy_matcher import FuzzyMatcher
from .matchers.model_matcher import ModelMatcher
from .parameters import extract_parameters_from_query, render_command_safely
from .risk import evaluate_command_risk


# Polarity / Action keywords for semantic intent disambiguation
STOP_ACTIONS = {"stop", "kill", "terminate", "halt", "end", "abort", "quit", "pkill"}
START_ACTIONS = {"start", "launch", "run", "begin", "open", "exec"}
DELETE_ACTIONS = {"delete", "remove", "erase", "wipe", "destroy", "purge", "trash", "rm", "del", "clean up"}
COPY_ACTIONS = {"copy", "clone", "duplicate", "backup", "cp"}
UPTIME_QUERY_ACTIONS = {"how long", "how many", "uptime", "turned on", "running time", "boot time", "since reboot"}

# Valid external tools that are outside the 50-intent PowerShell baseline
EXTERNAL_CLI_TOOLS = {
    "git", "docker", "kubectl", "npm", "yarn", "pnpm", "cargo", "pip", "python",
    "node", "mvn", "gradle", "terraform", "aws", "az", "gcloud", "apt", "apt-get",
    "chmod", "chown", "brew", "choco", "winget"
}

# Non-shell technical and programming language patterns (near-domain negative triggers)
NON_SHELL_PATTERNS = [
    re.compile(r"^\s*(def|class|import|from|function|const|let|var|package|public|private)\b"),
    re.compile(r"\b(console\.log|printf|cout|system\.out\.println)\b", re.IGNORECASE),
    re.compile(r"^\s*(apt-get|apt|yum|pacman|dnf|brew|chmod|chown)\b", re.IGNORECASE),
    re.compile(r"\b(linked\s+list|binary\s+tree|quicksort|mergesort|reverse\s+a\s+string)\b", re.IGNORECASE),
]


class IntentEngine:
    """Unified semantic intent recognition engine for Windows PowerShell 7."""

    def __init__(
        self,
        kb_path: str | Path = "data/knowledge_base.json",
        model_path: str | Path = "./models/potion-base-2M",
        offline_mode: bool = True,
        max_cache_size: int = 128,
    ):
        self.kb_path = kb_path
        self.model_path = str(model_path)
        self.offline_mode = offline_mode
        self.max_cache_size = max_cache_size

        self.store = KnowledgeBaseStore(kb_path)
        self.rule_matcher = RuleMatcher(self.store)
        self.fuzzy_matcher = FuzzyMatcher(self.store)

        # Lazy model initialization: ModelMatcher is NOT loaded until needed
        self._model_matcher: Optional[ModelMatcher] = None
        self._cache: Dict[str, QueryResult] = {}

    @property
    def is_model_loaded(self) -> bool:
        """Check whether the neural ModelMatcher has been loaded into memory."""
        return self._model_matcher is not None

    @property
    def model_matcher(self) -> ModelMatcher:
        """On-demand initialization of the Model2Vec semantic matcher."""
        if self._model_matcher is None:
            self._model_matcher = ModelMatcher(
                store=self.store,
                model_name_or_path=self.model_path,
                offline_mode=self.offline_mode,
            )
        return self._model_matcher

    def search(
        self,
        query: str,
        top_k: int = 3,
        mode: str = "hybrid",
        ood_threshold: float = 0.42,
    ) -> QueryResult:
        """Search command intents for a query string across requested modes.

        Modes:
            - "hybrid": Rule exact -> Fuzzy + Model weighted fusion with intent constraints
            - "rule": RuleMatcher only
            - "fuzzy": FuzzyMatcher only
            - "model": ModelMatcher only
        """
        start_time = time.perf_counter()

        # 1. Check query cache
        cache_key = f"{mode}:{query.strip()}:{top_k}:{ood_threshold}"
        if cache_key in self._cache:
            cached_res = self._cache[cache_key]
            # Fast return from cache
            return cached_res

        # 2. Input normalization and validation
        if not query or not query.strip():
            elapsed = (time.perf_counter() - start_time) * 1000
            res = QueryResult(
                query=query,
                candidates=[],
                debug_candidates=[],
                confidence_level=ConfidenceLevel.REJECTED,
                is_accepted=False,
                is_rejected=True,
                rejection_reason="empty_query",
                latency_ms=elapsed,
                mode=mode,
                is_empty=True,
                is_out_of_domain=True,
            )
            self._save_to_cache(cache_key, res)
            return res

        clean_q = query.strip()

        # 3. Unicode and non-alphanumeric check
        has_letters_or_digits = any(c.isalnum() for c in clean_q)
        if not has_letters_or_digits:
            elapsed = (time.perf_counter() - start_time) * 1000
            res = QueryResult(
                query=query,
                candidates=[],
                debug_candidates=[],
                confidence_level=ConfidenceLevel.REJECTED,
                is_accepted=False,
                is_rejected=True,
                rejection_reason="non_alphanumeric_or_symbolic_query",
                latency_ms=elapsed,
                mode=mode,
                is_empty=False,
                is_out_of_domain=True,
            )
            self._save_to_cache(cache_key, res)
            return res

        # Detect CJK (Chinese/Japanese/Korean)
        has_cjk = any("\u4e00" <= c <= "\u9fff" for c in clean_q)

        # 4. Check for external CLI tools outside the 50-intent PowerShell baseline
        tokens = clean_q.split()
        first_token = tokens[0].lower() if tokens else ""
        if first_token in EXTERNAL_CLI_TOOLS:
            # Check if this tool is mapped as an alias in KB (e.g. curl/wget)
            rule_check = self.rule_matcher.match(clean_q, top_k=1)
            if not rule_check or rule_check[0].score < 0.95:
                elapsed = (time.perf_counter() - start_time) * 1000
                res = QueryResult(
                    query=query,
                    candidates=[],
                    debug_candidates=[],
                    confidence_level=ConfidenceLevel.REJECTED,
                    is_accepted=False,
                    is_rejected=True,
                    rejection_reason="unsupported_external_tool",
                    latency_ms=elapsed,
                    mode=mode,
                    is_out_of_domain=True,
                )
                self._save_to_cache(cache_key, res)
                return res

        # 5. Check for non-shell near-domain programming code or Linux syntax
        if any(p.search(clean_q) for p in NON_SHELL_PATTERNS):
            elapsed = (time.perf_counter() - start_time) * 1000
            res = QueryResult(
                query=query,
                candidates=[],
                debug_candidates=[],
                confidence_level=ConfidenceLevel.REJECTED,
                is_accepted=False,
                is_rejected=True,
                rejection_reason="near_domain_code_or_unsupported_system",
                latency_ms=elapsed,
                mode=mode,
                is_out_of_domain=True,
            )
            self._save_to_cache(cache_key, res)
            return res

        # 6. Unambiguous exact match short-circuit (applies to hybrid and rule mode)
        # If input is a single token or exact command alias with exactly one mapping (e.g. 'pwd', 'cls')
        if mode in ("hybrid", "rule"):
            rule_candidates = self.rule_matcher.match(clean_q, top_k=top_k)
            # Short circuit condition: single unambiguous exact match with 1.0 score
            if len(rule_candidates) == 1 and rule_candidates[0].score == 1.0 and rule_candidates[0].source == MatchSource.RULE_EXACT.value:
                exact_cand = rule_candidates[0]
                intent = self.store.get_by_id(exact_cand.intent_id)
                if intent:
                    params, is_complete = extract_parameters_from_query(intent, clean_q)
                    rendered = render_command_safely(intent.command, intent, params)
                    exact_cand.parameters = params
                    if rendered:
                        exact_cand.rendered_command = rendered
                        exact_cand.command = rendered
                    exact_cand.is_complete = is_complete and not bool(re.search(r"<[^>]+>", exact_cand.command))
                    eff_risk, eff_reason = evaluate_command_risk(intent, exact_cand.command)
                    exact_cand.risk_level = eff_risk.value
                    if eff_reason:
                        exact_cand.risk_reason = eff_reason

                elapsed = (time.perf_counter() - start_time) * 1000
                res = QueryResult(
                    query=query,
                    candidates=[exact_cand],
                    debug_candidates=[],
                    confidence_level=ConfidenceLevel.HIGH,
                    is_accepted=True,
                    is_rejected=False,
                    latency_ms=elapsed,
                    mode=mode,
                )
                self._save_to_cache(cache_key, res)
                return res

        # 7. Single-mode dispatch
        if mode == "rule":
            candidates = self.rule_matcher.match(clean_q, top_k=top_k)
            self._enrich_candidates(candidates, clean_q)
            elapsed = (time.perf_counter() - start_time) * 1000
            res = QueryResult(
                query=query,
                candidates=candidates,
                latency_ms=elapsed,
                mode=mode,
                confidence_level=ConfidenceLevel.HIGH if candidates else ConfidenceLevel.REJECTED,
                is_accepted=bool(candidates),
                is_rejected=not bool(candidates),
                rejection_reason="no_rule_match" if not candidates else None,
            )
            self._save_to_cache(cache_key, res)
            return res

        if mode == "fuzzy":
            candidates = self.fuzzy_matcher.match(clean_q, top_k=top_k)
            self._enrich_candidates(candidates, clean_q)
            elapsed = (time.perf_counter() - start_time) * 1000
            is_good = bool(candidates and candidates[0].score >= 0.40)
            res = QueryResult(
                query=query,
                candidates=candidates if is_good else [],
                debug_candidates=candidates if not is_good else [],
                latency_ms=elapsed,
                mode=mode,
                confidence_level=ConfidenceLevel.MEDIUM if is_good else ConfidenceLevel.REJECTED,
                is_accepted=is_good,
                is_rejected=not is_good,
                rejection_reason="low_fuzzy_similarity" if not is_good else None,
            )
            self._save_to_cache(cache_key, res)
            return res

        if mode == "model":
            candidates = self.model_matcher.match(clean_q, top_k=top_k)
            self._enrich_candidates(candidates, clean_q)
            elapsed = (time.perf_counter() - start_time) * 1000
            is_good = bool(candidates and candidates[0].score >= ood_threshold)
            res = QueryResult(
                query=query,
                candidates=candidates if is_good else [],
                debug_candidates=candidates if not is_good else [],
                latency_ms=elapsed,
                mode=mode,
                confidence_level=ConfidenceLevel.MEDIUM if is_good else ConfidenceLevel.REJECTED,
                is_accepted=is_good,
                is_rejected=not is_good,
                rejection_reason="low_semantic_similarity" if not is_good else None,
                is_out_of_domain=not is_good,
            )
            self._save_to_cache(cache_key, res)
            return res

        # 8. Hybrid search fusion
        accepted_candidates, debug_candidates, conf_level, is_ood, reject_reason = self._hybrid_fusion(
            clean_q, top_k=top_k, ood_threshold=ood_threshold, has_cjk=has_cjk
        )
        elapsed = (time.perf_counter() - start_time) * 1000

        res = QueryResult(
            query=query,
            candidates=accepted_candidates,
            debug_candidates=debug_candidates,
            confidence_level=conf_level,
            is_accepted=len(accepted_candidates) > 0,
            is_rejected=len(accepted_candidates) == 0,
            rejection_reason=reject_reason,
            latency_ms=elapsed,
            mode="hybrid",
            is_out_of_domain=is_ood,
        )
        self._save_to_cache(cache_key, res)
        return res

    def _hybrid_fusion(
        self,
        query: str,
        top_k: int = 3,
        ood_threshold: float = 0.42,
        has_cjk: bool = False,
    ) -> Tuple[List[Candidate], List[Candidate], ConfidenceLevel, bool, Optional[str]]:
        """Combine rule, fuzzy, and embedding matchers with intent and scope constraints."""
        # 1. Fetch candidates from all matchers
        rule_candidates = self.rule_matcher.match(query, top_k=10)
        fuzzy_candidates = self.fuzzy_matcher.match(query, top_k=10)
        model_candidates = self.model_matcher.match(query, top_k=10)

        # Build score maps
        model_map: Dict[str, float] = {c.intent_id: c.score for c in model_candidates}
        fuzzy_map: Dict[str, float] = {c.intent_id: c.score for c in fuzzy_candidates}
        rule_map: Dict[str, Candidate] = {c.intent_id: c for c in rule_candidates}

        # Gather all unique intent IDs and sort deterministically
        all_intent_ids = sorted(set(model_map.keys()) | set(fuzzy_map.keys()) | set(rule_map.keys()))

        # Analyze query characteristics
        lower_q = query.lower()
        q_tokens = set(lower_q.split())

        has_stop = any(w in q_tokens for w in STOP_ACTIONS)
        has_start = any(w in q_tokens for w in START_ACTIONS)
        has_delete = any(w in q_tokens for w in DELETE_ACTIONS) or "delete" in lower_q or "trash" in lower_q
        has_copy = any(w in q_tokens for w in COPY_ACTIONS) or "clone" in lower_q
        has_uptime = any(k in lower_q for k in UPTIME_QUERY_ACTIONS)
        has_numeric_pid = bool(re.search(r"\b(?:pid\s*)?(\d{2,7})\b", lower_q)) and ("kill" in lower_q or "process" in lower_q)

        # Scope Analysis: File vs Directory vs System Recycle Bin
        has_file_target = (
            bool(re.search(r"\b[\w-]+\.(?:tmp|txt|log|json|csv|py|md|ps1|bak|xml|yml|yaml|ini|cfg)\b", lower_q))
            or any(w in q_tokens for w in ("file", "temporary", "temp", "notes", "single"))
        )
        has_dir_target = any(w in q_tokens for w in ("folder", "directory", "dir", "tree", "subfolder", "subdirectories"))
        has_recycle_bin = "recycle" in lower_q or ("trash" in lower_q and not has_file_target)

        # Scope Analysis: Ping / ICMP reachability
        has_icmp_or_ping = any(w in lower_q for w in ("icmp", "ping", "reachability", "packet", "answers icmp"))

        # Scope Analysis: Status checking vs State mutation
        has_status_query = (
            any(w in q_tokens for w in ("is", "check", "whether", "status"))
            and any(w in q_tokens for w in ("running", "open", "active", "alive"))
        )

        # Scope Analysis: Environment variables
        has_env = "env" in lower_q or "userprofile" in lower_q or "variable" in lower_q

        # Scope Analysis: Recursive search everywhere
        has_recurse_search = (
            any(w in lower_q for w in ("everywhere", "subdirectories", "recursively"))
            and any(w in lower_q for w in ("search", "find", "locate"))
        )

        scored_pool: List[Tuple[float, str, str]] = []  # (fused_score, intent_id, primary_source)

        for intent_id in all_intent_ids:
            s_model = model_map.get(intent_id, 0.0)
            s_fuzzy = fuzzy_map.get(intent_id, 0.0)
            rule_cand = rule_map.get(intent_id)

            if rule_cand and rule_cand.source == MatchSource.RULE_EXACT.value:
                s_rule = rule_cand.score
            elif rule_cand and rule_cand.source == MatchSource.RULE_PREFIX.value:
                s_rule = rule_cand.score * 0.90
            else:
                s_rule = 0.0

            # Weighting
            is_short_command = len(query.split()) == 1 or len(query) <= 6
            if is_short_command:
                if s_fuzzy >= 0.80:
                    fused = 0.70 * s_fuzzy + 0.20 * s_model + 0.10 * s_rule
                    src = MatchSource.FUZZY.value
                else:
                    fused = 0.35 * s_model + 0.35 * s_fuzzy + 0.30 * s_rule
                    src = MatchSource.RULE_EXACT.value if s_rule >= 0.95 else (
                        MatchSource.FUZZY.value if s_fuzzy >= s_model else MatchSource.MODEL.value
                    )
            else:
                if s_fuzzy >= 0.85:
                    fused = 0.60 * s_fuzzy + 0.30 * s_model + 0.10 * s_rule
                    src = MatchSource.FUZZY.value
                else:
                    fused = 0.60 * s_model + 0.30 * s_fuzzy + 0.10 * s_rule
                    src = MatchSource.RULE_EXACT.value if s_rule >= 0.98 else (
                        MatchSource.MODEL.value if s_model >= s_fuzzy else MatchSource.FUZZY.value
                    )

            # --- Intent & Scope Constraints ---

            # Constraint 1: STOP vs START polarity
            if has_stop and not has_start and not has_status_query:
                if "sys_service_start" in intent_id or "proc_start" in intent_id:
                    fused *= 0.20  # Severely suppress start when user requested stop
                elif "sys_service_stop" in intent_id or "proc_kill" in intent_id:
                    fused += 0.15  # Boost stop intent

            if has_start and not has_stop and not has_status_query:
                if "sys_service_stop" in intent_id or "proc_kill" in intent_id:
                    fused *= 0.20
                elif "sys_service_start" in intent_id or "proc_start" in intent_id:
                    fused += 0.15

            # Constraint 2: COPY / CLONE vs DELETE
            if has_copy and not has_delete:
                if "file_delete" in intent_id or "sys_clear_recycle_bin" in intent_id:
                    fused *= 0.10  # Never recommend deletion for a copy/clone command
                elif "file_copy" in intent_id:
                    fused += 0.20

            # Constraint 3: Uptime query vs Reboot / Shutdown
            if has_uptime:
                if "sys_reboot" in intent_id or "sys_shutdown" in intent_id:
                    fused *= 0.10  # Never recommend reboot/shutdown for an uptime duration query
                elif "sys_uptime" in intent_id:
                    fused += 0.25

            # Constraint 4: Numeric PID targeting
            if has_numeric_pid:
                if intent_id == "proc_kill_id":
                    fused += 0.25
                elif intent_id == "proc_kill_name":
                    fused *= 0.70

            # Constraint 5: Operation Scope - Single File vs Global Recycle Bin vs Recursive Directory
            if has_delete:
                if has_file_target and not has_recycle_bin:
                    if intent_id == "sys_clear_recycle_bin":
                        fused *= 0.05  # Wiping recycle bin is NOT deleting a target file!
                    elif intent_id == "file_delete_single":
                        fused += 0.35  # Strongly boost deleting the single file
                    elif intent_id == "file_delete_recursive" and not has_dir_target:
                        fused *= 0.40
                elif has_recycle_bin:
                    if intent_id == "sys_clear_recycle_bin":
                        fused += 0.30
                elif has_dir_target:
                    if intent_id == "file_delete_recursive":
                        fused += 0.30
                    elif intent_id == "file_delete_single":
                        fused *= 0.50

            # Constraint 6: Ping / ICMP Reachability vs Listening Ports vs Port Scanning
            if has_icmp_or_ping:
                if intent_id == "net_ping_host":
                    fused += 0.35
                elif intent_id in ("net_test_port", "net_ip_config"):
                    fused *= 0.50

            has_listening_query = "port" in lower_q and (
                any(w in q_tokens for w in ("process", "using", "listening", "occupying", "who", "what", "which", "pid"))
                or "running on" in lower_q
            )
            has_test_conn_query = any(w in q_tokens for w in ("test", "connect", "reach", "remote", "ping", "server", "gateway"))

            if has_listening_query and not has_test_conn_query:
                if intent_id == "net_listening_ports":
                    fused += 0.45
                elif intent_id == "net_test_port":
                    fused *= 0.30
            elif has_test_conn_query and "port" in lower_q:
                if intent_id == "net_test_port":
                    fused += 0.35
                elif intent_id == "net_listening_ports":
                    fused *= 0.40

            # Constraint 7: Status / Liveness Query vs Service Mutation
            if has_status_query and not has_start and not has_stop:
                if intent_id == "proc_find":
                    fused += 0.30
                elif intent_id in ("sys_service_start", "sys_service_restart"):
                    fused *= 0.30

            # Constraint 8: Environment Variable Queries & Assignments
            if has_env:
                if any(w in lower_q for w in ("set", "export", "assign", "production", "development")):
                    if intent_id == "env_set_temp":
                        fused += 0.35
                elif any(w in lower_q for w in ("what", "check", "read", "value", "is set to")):
                    if intent_id == "env_get_value":
                        fused += 0.35

            # Constraint 9: Recursive Search Everywhere
            if has_recurse_search:
                if intent_id == "file_find_recurse":
                    fused += 0.35
                elif intent_id == "sys_system_info":
                    fused *= 0.20

            scored_pool.append((fused, intent_id, src))

        # Sort deterministically by descending score, tie-breaking on intent_id
        scored_pool.sort(key=lambda x: (-round(x[0], 4), x[1]))

        # Rejection & Out-of-domain decision
        top_score = scored_pool[0][0] if scored_pool else 0.0
        has_exact_rule = any(
            rule_map.get(iid) and rule_map[iid].source == MatchSource.RULE_EXACT.value and rule_map[iid].score >= 0.95
            for _, iid, _ in scored_pool[:1]
        )

        is_ood = False
        rejection_reason = None

        if has_cjk and not has_exact_rule:
            is_ood = True
            rejection_reason = "unsupported_non_latin_language"
        elif not has_exact_rule and top_score < ood_threshold:
            is_ood = True
            rejection_reason = "low_semantic_confidence_out_of_domain"

        # Build Candidate objects
        raw_candidates: List[Candidate] = []
        for score, intent_id, source in scored_pool[:top_k]:
            intent = self.store.get_by_id(intent_id)
            if not intent:
                continue

            has_placeholders = bool(re.search(r"<[^>]+>", intent.command))
            init_complete = (not has_placeholders) and (len(intent.parameter_slots) == 0)

            raw_candidates.append(
                Candidate(
                    command=intent.command,
                    intent_id=intent.id,
                    description=intent.description,
                    score=round(score, 4),
                    source=source,
                    risk_level=intent.risk_level.value,
                    category=intent.category,
                    risk_reason=intent.risk_reason,
                    command_template=intent.command,
                    is_complete=init_complete,
                )
            )

        # Enrich with parameter parsing, safe rendering, and risk evaluation
        self._enrich_candidates(raw_candidates, query)

        if is_ood:
            # When rejected or OOD: actionable candidates must be EMPTY!
            accepted_candidates = []
            debug_candidates = raw_candidates
            conf_level = ConfidenceLevel.REJECTED
        else:
            accepted_candidates = raw_candidates
            debug_candidates = []
            conf_level = ConfidenceLevel.HIGH if top_score >= 0.70 else ConfidenceLevel.MEDIUM

        return accepted_candidates, debug_candidates, conf_level, is_ood, rejection_reason

    def _enrich_candidates(self, candidates: List[Candidate], query: str) -> None:
        """Extract parameters, render safe command string, and evaluate effective risk."""
        for cand in candidates:
            intent = self.store.get_by_id(cand.intent_id)
            if not intent:
                continue

            params, is_complete = extract_parameters_from_query(intent, query)
            cand.parameters = params

            rendered = render_command_safely(intent.command, intent, params)
            if rendered:
                cand.rendered_command = rendered
                cand.command = rendered

            # Crucial requirement: If any placeholder remains in command, is_complete MUST be False!
            cand.is_complete = is_complete and not bool(re.search(r"<[^>]+>", cand.command))

            # Compute effective risk combining base annotations and scanned command string
            eff_risk, eff_reason = evaluate_command_risk(intent, cand.command)
            cand.risk_level = eff_risk.value
            if eff_reason:
                cand.risk_reason = eff_reason

    def _save_to_cache(self, key: str, res: QueryResult) -> None:
        """Simple LRU eviction cache."""
        if len(self._cache) >= self.max_cache_size:
            # Evict oldest entry
            oldest_key = next(iter(self._cache))
            self._cache.pop(oldest_key, None)
        self._cache[key] = res
