"""Regression coverage for the five issues confirmed in the code review."""

import pytest
from tiny_shell_intent import IntentEngine, KnowledgeBaseStore, escape_powershell_literal
from tiny_shell_intent.parameters import (
    extract_parameters_from_query,
    render_command_safely,
    validate_parameter_value,
)


@pytest.fixture
def store():
    return KnowledgeBaseStore("data/knowledge_base.json")


@pytest.mark.parametrize("quote", ["\u2018", "\u2019", "\u201a", "\u201b"])
def test_smart_quotes_cannot_escape_literal(store, quote):
    value = f"C:\\review{quote} -Recurse -ErrorAction {quote}SilentlyContinue"
    with pytest.raises(ValueError):
        escape_powershell_literal(value)
    intent = store.get_by_id("file_delete_single")
    assert not validate_parameter_value(intent.parameter_slots[0], value)[0]


@pytest.mark.parametrize("query, expected", [
    (r"delete file C:\logs\data.tmp", r"C:\logs\data.tmp"),
    ('delete file "C:\\My Documents\\report.txt"', r"C:\My Documents\report.txt"),
    ("delete file 'C:\\My Documents\\report.txt'", r"C:\My Documents\report.txt"),
    (r"delete file .\logs\data.tmp", r".\logs\data.tmp"),
    (r"delete file \\server\share\data.tmp", r"\\server\share\data.tmp"),
    ("delete file logs/data.tmp", "logs/data.tmp"),
    ("delete file data.tmp", "data.tmp"),
])
def test_file_targets_keep_full_path(store, query, expected):
    intent = store.get_by_id("file_delete_single")
    parameters, complete = extract_parameters_from_query(intent, query)
    assert complete
    assert parameters["path"] == expected
    assert render_command_safely(intent.command, intent, parameters) == f"Remove-Item -Path '{expected}' -Force"


@pytest.mark.parametrize("query", [
    r"delete file C:\My Documents\report.txt",
    "delete file a.tmp b.tmp",
    "delete file 'a.tmp' 'b.tmp'",
])
def test_ambiguous_file_targets_stay_incomplete(store, query):
    intent = store.get_by_id("file_delete_single")
    parameters, complete = extract_parameters_from_query(intent, query)
    assert not complete
    assert render_command_safely(intent.command, intent, parameters) is None


@pytest.mark.parametrize("intent_id, query, expected", [
    ("env_get_value", "check env PATH", "$env:PATH"),
    ("env_get_value", "check env NODE_ENV", "$env:NODE_ENV"),
    ("env_set_temp", "set NODE_ENV to production", "$env:NODE_ENV = 'production'"),
])
def test_environment_names_render_as_identifiers(store, intent_id, query, expected):
    intent = store.get_by_id(intent_id)
    parameters, complete = extract_parameters_from_query(intent, query)
    assert complete
    assert render_command_safely(intent.command, intent, parameters) == expected


def test_invalid_environment_identifier_cannot_be_rendered(store):
    intent = store.get_by_id("env_get_value")
    assert not validate_parameter_value(intent.parameter_slots[0], "FOO-BAR")[0]
    assert render_command_safely(intent.command, intent, {"variable_name": "FOO-BAR"}) is None


def test_cache_isolates_initial_and_cached_results():
    engine = IntentEngine(offline_mode=True)
    first = engine.search("kill process 12480 immediately")
    assert first.candidates
    original_command = first.candidates[0].command
    original_parameters = dict(first.candidates[0].parameters)
    assert original_parameters
    first.candidates[0].command = "mutated"
    first.candidates[0].parameters.clear()
    second = engine.search("kill process 12480 immediately")
    assert second is not first
    assert second.candidates[0].command == original_command
    assert second.candidates[0].parameters == original_parameters
    second.candidates[0].parameters.clear()
    second.candidates.clear()
    third = engine.search("kill process 12480 immediately")
    assert third.candidates
    assert third.candidates[0].parameters == original_parameters


def test_cache_isolates_rejected_debug_candidates():
    engine = IntentEngine(offline_mode=True)
    first = engine.search("inspect something", mode="model", ood_threshold=2.0)
    assert first.is_rejected and first.debug_candidates
    expected = first.debug_candidates[0].command
    first.debug_candidates[0].command = "mutated"
    second = engine.search("inspect something", mode="model", ood_threshold=2.0)
    assert second.debug_candidates[0].command == expected
