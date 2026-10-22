"""Risk tagging and security analysis for shell commands."""

import re
from typing import Optional, Tuple, List, Dict, Any
from .schema import RiskLevel, CommandIntent


# Color codes for terminal display
ANSI_RED = "\033[91m"
ANSI_YELLOW = "\033[93m"
ANSI_GREEN = "\033[92m"
ANSI_BOLD = "\033[1m"
ANSI_RESET = "\033[0m"


DANGEROUS_PATTERNS = [
    (re.compile(r"remove-item\s+.*-recurse", re.IGNORECASE), "Permanently purges entire directory tree recursively."),
    (re.compile(r"rm\s+-rf", re.IGNORECASE), "Recursively deletes directory tree without confirmation."),
    (re.compile(r"rmdir\s+/s", re.IGNORECASE), "Recursively deletes folder structure without confirmation."),
    (re.compile(r"stop-process\s+.*-force", re.IGNORECASE), "Forcibly terminates processes without saving unsaved data."),
    (re.compile(r"kill\s+-9", re.IGNORECASE), "Sends uncatchable SIGKILL to terminate process immediately."),
    (re.compile(r"restart-computer", re.IGNORECASE), "Immediately reboots the operating system."),
    (re.compile(r"stop-computer", re.IGNORECASE), "Immediately powers off and halts the computer."),
    (re.compile(r"clear-recyclebin", re.IGNORECASE), "Permanently empties all Recycle Bin contents across all drives."),
    (re.compile(r"format\s+[a-z]:", re.IGNORECASE), "Formats disk volume, destroying existing filesystem data."),
]

WARNING_PATTERNS = [
    (re.compile(r"remove-item", re.IGNORECASE), "Deletes file bypassing recycle bin."),
    (re.compile(r"move-item", re.IGNORECASE), "Relocates file and may overwrite existing destinations."),
    (re.compile(r"restart-service", re.IGNORECASE), "Temporarily interrupts service availability."),
    (re.compile(r"stop-service", re.IGNORECASE), "Halts active system background service."),
    (re.compile(r"set-executionpolicy", re.IGNORECASE), "Modifies PowerShell script security policy."),
    (re.compile(r"clear-dnsclientcache", re.IGNORECASE), "Flushes local DNS resolver cache."),
    (re.compile(r"\$env:[a-zA-Z0-9_]+\s*=", re.IGNORECASE), "Modifies session environment variable state."),
]


def scan_command_risk(command_str: str) -> Tuple[RiskLevel, Optional[str]]:
    """Scan raw or rendered command string against regex security rules.

    Returns:
        (detected_risk_level, detected_reason)
    """
    clean_cmd = command_str.strip()

    # 1. Dangerous checks
    for pattern, reason in DANGEROUS_PATTERNS:
        if pattern.search(clean_cmd):
            return RiskLevel.DANGEROUS, reason

    # 2. Warning checks
    for pattern, reason in WARNING_PATTERNS:
        if pattern.search(clean_cmd):
            return RiskLevel.WARNING, reason

    return RiskLevel.SAFE, None


def evaluate_command_risk(
    intent: CommandIntent,
    command_override: Optional[str] = None,
) -> Tuple[RiskLevel, Optional[str]]:
    """Determine the effective risk level for an intent and its command.

    Combines human-verified annotations with dynamic automated rule scans.
    Guarantee: Rendered command risk will NEVER be lower than the template's base risk.
    """
    base_level = intent.risk_level or RiskLevel.SAFE
    base_reason = intent.risk_reason

    # Scan the template command
    tmpl_level, tmpl_reason = scan_command_risk(intent.command)

    # Scan rendered command if supplied
    override_level = RiskLevel.SAFE
    override_reason = None
    if command_override:
        override_level, override_reason = scan_command_risk(command_override)

    # Effective risk is the highest among annotated, template-scanned, and override-scanned
    final_level = base_level
    final_reason = base_reason

    # Compare with template scan
    if tmpl_level > final_level:
        final_level = tmpl_level
        final_reason = tmpl_reason

    # Compare with override scan
    if override_level > final_level:
        final_level = override_level
        final_reason = override_reason

    return final_level, final_reason


def audit_knowledge_base_risks(intents: List[CommandIntent]) -> List[Dict[str, Any]]:
    """Verify consistency between annotated risk levels and automated security rules."""
    discrepancies = []
    for intent in intents:
        scanned_level, scanned_reason = scan_command_risk(intent.command)
        if scanned_level > intent.risk_level:
            discrepancies.append({
                "intent_id": intent.id,
                "command": intent.command,
                "annotated_level": intent.risk_level.value,
                "scanned_level": scanned_level.value,
                "scanned_reason": scanned_reason,
            })
    return discrepancies


def format_risk_badge(risk_level: str | RiskLevel, use_color: bool = True) -> str:
    """Format risk level badge with optional terminal colors."""
    level = risk_level.value if isinstance(risk_level, RiskLevel) else str(risk_level).lower()

    if not use_color:
        return f"[{level.upper()}]"

    if level == RiskLevel.DANGEROUS.value:
        return f"{ANSI_RED}{ANSI_BOLD}[DANGEROUS]{ANSI_RESET}"
    elif level == RiskLevel.WARNING.value:
        return f"{ANSI_YELLOW}{ANSI_BOLD}[WARNING]{ANSI_RESET}"
    else:
        return f"{ANSI_GREEN}[SAFE]{ANSI_RESET}"
