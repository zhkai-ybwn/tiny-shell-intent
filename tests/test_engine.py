"""Unit tests for Tiny Shell Intent engine."""

import pytest
from tiny_shell_intent import IntentEngine, KnowledgeBaseStore, RiskLevel, MatchSource


@pytest.fixture(scope="session")
def engine():
    return IntentEngine(
        kb_path="data/knowledge_base.json",
        model_path="./models/potion-base-2M",
        offline_mode=True,
    )


def test_kb_store_loading(engine):
    store = engine.store
    assert len(store) == 50
    assert "proc_kill_name" in store._intents
    intent = store.get_by_id("proc_kill_name")
    assert intent.risk_level == RiskLevel.DANGEROUS
    assert "kill" in intent.aliases


def test_exact_alias_rule(engine):
    res = engine.search("kill", mode="rule")
    assert len(res.candidates) > 0
    top = res.top_candidate
    assert top.intent_id == "proc_kill_name"
    assert top.source == MatchSource.RULE_EXACT.value
    assert top.score == 1.0
    assert top.risk_level == RiskLevel.DANGEROUS.value


def test_prefix_rule(engine):
    res = engine.search("stop-proc", mode="rule")
    assert len(res.candidates) > 0
    top = res.top_candidate
    assert top.intent_id in ("proc_kill_name", "proc_kill_id")
    assert top.source == MatchSource.RULE_PREFIX.value


def test_fuzzy_matching(engine):
    res = engine.search("stopp-procss chrome", mode="fuzzy")
    assert len(res.candidates) > 0
    top_ids = [c.intent_id for c in res.candidates]
    assert "proc_kill_name" in top_ids


def test_model_semantic_matching(engine):
    res = engine.search("terminate stuck background program", mode="model")
    assert len(res.candidates) > 0
    top_ids = [c.intent_id for c in res.candidates]
    assert "proc_kill_name" in top_ids


def test_hybrid_natural_language(engine):
    res = engine.search("is port 8080 reachable", mode="hybrid")
    assert len(res.candidates) > 0
    top = res.top_candidate
    assert top.intent_id == "net_test_port"


def test_risk_tagging(engine):
    res_danger = engine.search("rm -rf", mode="hybrid")
    assert res_danger.top_candidate.risk_level == RiskLevel.DANGEROUS.value
    assert res_danger.top_candidate.risk_reason is not None

    res_safe = engine.search("pwd", mode="hybrid")
    assert res_safe.top_candidate.risk_level == RiskLevel.SAFE.value


def test_empty_and_whitespace(engine):
    res_empty = engine.search("", mode="hybrid")
    assert res_empty.is_empty is True
    assert len(res_empty.candidates) == 0

    res_ws = engine.search("   \t  ", mode="hybrid")
    assert res_ws.is_empty is True
    assert len(res_ws.candidates) == 0


def test_punctuation_and_symbols(engine):
    res = engine.search("!@#$%^&*", mode="hybrid")
    assert res.is_out_of_domain is True
    assert len(res.candidates) == 0


def test_out_of_domain_query(engine):
    res = engine.search("how to bake chocolate chip cookies", mode="hybrid")
    assert res.is_out_of_domain is True
