"""Comprehensive regression and unit test suite for Tiny Shell Intent."""

import pytest
from tiny_shell_intent import (
    IntentEngine,
    KnowledgeBaseStore,
    RiskLevel,
    MatchSource,
    ConfidenceLevel,
    escape_powershell_literal,
    audit_knowledge_base_risks,
    evaluate_command_risk,
)


@pytest.fixture
def fresh_engine():
    """Create a fresh engine for testing lazy loading behavior."""
    return IntentEngine(
        kb_path="data/knowledge_base.json",
        model_path="./models/potion-base-2M",
        offline_mode=True,
    )


def test_lazy_loading_and_short_circuit(fresh_engine):
    """P1-01: Rule / Exact queries must short-circuit without loading neural model."""
    assert not fresh_engine.is_model_loaded, "Model should not be loaded on engine initialization"

    # Exact short-circuit query
    res = fresh_engine.search("pwd", mode="hybrid")
    assert not fresh_engine.is_model_loaded, "Model should NOT be loaded for unambiguous exact 'pwd'"
    assert res.is_accepted is True
    assert len(res.candidates) == 1
    assert res.candidates[0].intent_id == "file_print_working_dir"
    assert res.candidates[0].source == MatchSource.RULE_EXACT.value
    assert res.candidates[0].score == 1.0

    # Another exact short-circuit
    res_cls = fresh_engine.search("cls", mode="hybrid")
    assert not fresh_engine.is_model_loaded, "Model should NOT be loaded for 'cls'"
    assert res_cls.candidates[0].intent_id == "sys_clear_screen"

    # Rule mode query
    res_rule = fresh_engine.search("Get-Process", mode="rule")
    assert not fresh_engine.is_model_loaded, "Model should NOT be loaded in pure rule mode"


def test_model_loaded_only_when_needed(fresh_engine):
    """Model is loaded only when natural language or model mode requires it."""
    assert not fresh_engine.is_model_loaded
    res = fresh_engine.search("which processes consume most cpu", mode="hybrid")
    assert fresh_engine.is_model_loaded, "Model should now be loaded for complex semantic query"
    assert res.is_accepted is True
    assert res.top_candidate.intent_id == "proc_list"


def test_pid_kill_vs_name_kill(fresh_engine):
    """P0-01: Disambiguation between PID kill and process name kill."""
    # Natural language with numeric PID
    res_pid = fresh_engine.search("kill process 12480 immediately", mode="hybrid")
    assert res_pid.is_accepted is True
    assert res_pid.top_candidate.intent_id == "proc_kill_id"
    assert res_pid.top_candidate.parameters.get("pid") == 12480
    assert res_pid.top_candidate.rendered_command == "Stop-Process -Id 12480 -Force"
    assert res_pid.top_candidate.is_complete is True

    # Process by name
    res_name = fresh_engine.search("kill chrome", mode="hybrid")
    assert res_name.is_accepted is True
    assert res_name.top_candidate.intent_id == "proc_kill_name"
    assert res_name.top_candidate.parameters.get("name") == "chrome"
    assert res_name.top_candidate.rendered_command == "Stop-Process -Name 'chrome' -Force"


def test_polarity_stop_vs_start(fresh_engine):
    """P0-01: Stopping a service must NEVER recommend starting it as #1 candidate."""
    res = fresh_engine.search("stop windows update service immediately", mode="hybrid")
    assert res.is_accepted is True
    assert res.top_candidate.intent_id == "sys_service_stop"
    # Ensure start-service is not top-1
    assert res.top_candidate.intent_id != "sys_service_start"


def test_uptime_vs_reboot_polarity(fresh_engine):
    """P0-01: Querying uptime must NEVER recommend force reboot."""
    res = fresh_engine.search("how long has this computer been turned on without restarting", mode="hybrid")
    assert res.is_accepted is True
    assert res.top_candidate.intent_id == "sys_uptime"
    assert res.top_candidate.intent_id != "sys_reboot_machine"
    assert res.top_candidate.intent_id != "sys_shutdown_machine"


def test_copy_vs_delete_polarity(fresh_engine):
    """P0-01: Cloning directory must NEVER recommend recursive delete as #1."""
    res = fresh_engine.search("clone directory tree over to d drive", mode="hybrid")
    assert res.is_accepted is True
    assert res.top_candidate.intent_id == "file_copy"
    assert res.top_candidate.intent_id != "file_delete_recursive"


def test_parameter_extraction_and_safe_rendering(fresh_engine):
    """P1-02: Parameter slot extraction and safe PowerShell rendering."""
    # Complete parameter extraction
    res = fresh_engine.search("test port 8080 on localhost", mode="hybrid")
    assert res.is_accepted is True
    top = res.top_candidate
    assert top.intent_id == "net_test_port"
    assert top.parameters == {"port": 8080, "host": "localhost"}
    assert top.is_complete is True
    assert top.rendered_command == "Test-NetConnection -ComputerName localhost -Port 8080"

    # Missing parameter
    intent = fresh_engine.store.get_by_id("net_test_port")
    from tiny_shell_intent.parameters import extract_parameters_from_query, render_command_safely
    params, complete = extract_parameters_from_query(intent, "test port")
    assert complete is False
    assert render_command_safely(intent.command, intent, params) is None


def test_powershell_injection_defense():
    """P1-02: Injection attempts must be blocked."""
    from tiny_shell_intent.parameters import validate_parameter_value, ParameterSlot
    slot = ParameterSlot(name="host", type="hostname", required=True)

    # Valid
    ok, val, err = validate_parameter_value(slot, "localhost")
    assert ok is True

    # Injection with semicolon
    ok, val, err = validate_parameter_value(slot, "localhost; Stop-Computer")
    assert ok is False
    assert "injection" in err.lower()

    # Injection with subexpression
    ok, val, err = validate_parameter_value(slot, "$(whoami)")
    assert ok is False

    # Injection in escape_powershell_literal
    with pytest.raises(ValueError):
        escape_powershell_literal("foo; rm -rf /")


def test_ood_and_rejection_policy(fresh_engine):
    """P0-02: OOD and rejected queries must have empty candidates list."""
    # Lifestyle OOD
    res_cookies = fresh_engine.search("how to bake chocolate chip cookies", mode="hybrid")
    assert res_cookies.is_rejected is True
    assert res_cookies.is_accepted is False
    assert res_cookies.is_out_of_domain is True
    assert len(res_cookies.candidates) == 0, "Accepted candidates must be EMPTY for OOD queries"
    assert len(res_cookies.debug_candidates) > 0, "Debug candidates should be retained for inspection"

    # Near-domain code negative
    res_code = fresh_engine.search("def quicksort(arr): return arr", mode="hybrid")
    assert res_code.is_rejected is True
    assert len(res_code.candidates) == 0

    # Near-domain linux command
    res_linux = fresh_engine.search("chmod -R 777 /var/www", mode="hybrid")
    assert res_linux.is_rejected is True
    assert len(res_linux.candidates) == 0


def test_edge_and_empty_inputs(fresh_engine):
    """Edge cases: empty, whitespace, and symbols."""
    res_empty = fresh_engine.search("", mode="hybrid")
    assert res_empty.is_empty is True
    assert res_empty.is_rejected is True
    assert len(res_empty.candidates) == 0

    res_ws = fresh_engine.search("   ", mode="hybrid")
    assert res_ws.is_empty is True
    assert len(res_ws.candidates) == 0

    res_sym = fresh_engine.search("???", mode="hybrid")
    assert res_sym.is_rejected is True
    assert len(res_sym.candidates) == 0


def test_unicode_chinese_graceful_handling(fresh_engine):
    """P0-02: Chinese Unicode input must not crash and reject gracefully."""
    res = fresh_engine.search("列出当前目录的所有文件", mode="hybrid")
    assert res.is_rejected is True
    assert res.rejection_reason == "unsupported_non_latin_language"
    assert len(res.candidates) == 0


def test_risk_detection_and_escalation(fresh_engine):
    """P1-03: Risk detection logic, audit, and escalation."""
    # Check consistency of the KB
    discrepancies = audit_knowledge_base_risks(fresh_engine.store.all_intents())
    assert len(discrepancies) == 0

    # High risk command
    res_rm = fresh_engine.search("rm -rf", mode="hybrid")
    assert res_rm.top_candidate.risk_level == RiskLevel.DANGEROUS.value
    assert res_rm.top_candidate.risk_reason is not None

    # Safe command
    res_safe = fresh_engine.search("pwd", mode="hybrid")
    assert res_safe.top_candidate.risk_level == RiskLevel.SAFE.value

    # Dynamic risk escalation: if a template was marked safe, but rendered with dangerous flag
    intent_safe = fresh_engine.store.get_by_id("file_list")
    eff_risk, reason = evaluate_command_risk(intent_safe, "Remove-Item -Path C:\\ -Recurse -Force")
    assert eff_risk == RiskLevel.DANGEROUS


def test_deterministic_sorting(fresh_engine):
    """P1-01: Multiple searches with the same query produce identical order."""
    q = "how many lines in log file"
    res1 = fresh_engine.search(q, mode="hybrid")
    res2 = fresh_engine.search(q, mode="hybrid")
    ids1 = [c.intent_id for c in res1.candidates]
    ids2 = [c.intent_id for c in res2.candidates]
    assert ids1 == ids2
    scores1 = [c.score for c in res1.candidates]
    scores2 = [c.score for c in res2.candidates]
    assert scores1 == scores2


def test_template_unresolved_placeholder_not_complete(fresh_engine):
    """P0: Any command template containing unresolved <...> placeholders must NOT be complete."""
    res = fresh_engine.search("copy files over to another place", mode="hybrid")
    assert res.is_accepted is True
    top = res.top_candidate
    assert "<" in top.command and ">" in top.command
    assert top.is_complete is False, "Template with unresolved placeholders cannot be complete or directly executable"


def test_port_extraction_does_not_split_ip(fresh_engine):
    """P0: Port extraction must not treat octets of an IPv4 address (e.g. 192) as a port."""
    res = fresh_engine.search("test if gateway 192.168.1.1 answers icmp packets", mode="hybrid")
    assert res.is_accepted is True
    assert res.top_candidate.intent_id == "net_ping_host"
    assert res.top_candidate.parameters.get("host") == "192.168.1.1"

    # Verify net_test_port did NOT extract 192 as a port
    for c in res.candidates:
        if c.intent_id == "net_test_port":
            assert c.parameters.get("port") != 192


def test_trash_single_file_scope_constraint(fresh_engine):
    """P0: Query targeting a specific file must NEVER recommend Clear-RecycleBin."""
    res = fresh_engine.search("trash temporary file data.tmp", mode="hybrid")
    assert res.is_accepted is True
    assert res.top_candidate.intent_id == "file_delete_single"
    assert res.top_candidate.intent_id != "sys_clear_recycle_bin"
    assert res.top_candidate.parameters.get("path") == "data.tmp"
    assert res.top_candidate.is_complete is True


def test_top_candidate_property_isolation(fresh_engine):
    """P1: top_candidate must return None on OOD / rejection to prevent accidental bypass."""
    res = fresh_engine.search("how to bake chocolate chip cookies", mode="hybrid")
    assert res.is_rejected is True
    assert res.top_candidate is None, "top_candidate must be None when query is rejected"
    assert res.top_debug_candidate is not None, "top_debug_candidate retains debug candidates"


def test_external_tool_product_scope(fresh_engine):
    """Product Scope: Valid external CLI commands outside the 50 KB must be classified cleanly."""
    res = fresh_engine.search("git commit -m 'update docs'", mode="hybrid")
    assert res.is_rejected is True
    assert res.is_out_of_domain is True
    assert res.rejection_reason == "unsupported_external_tool"
    assert res.top_candidate is None

