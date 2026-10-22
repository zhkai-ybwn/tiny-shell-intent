"""Risk tagging and security analysis for shell commands."""

import re
from typing import Tuple
from .schema import RiskLevel, CommandIntent


# Color codes for terminal display
ANSI_RED = "\033[91m"
ANSI_YELLOW = "\033[93m"
ANSI_GREEN = "\033[92m"
ANSI_BOLD = "\033[1m"
ANSI_RESET = "\033[0m"


DANGEROUS_PATTERNS = [
    re.compile(r"remove-item\s+.*-recurse", re.IGNORECASE),
    re.compile(r"rm\s+-rf", re.IGNORECASE),
    re.compile(r"rmdir\s+/s", re.IGNORECASE),
    re.compile(r"stop-process\s+.*-force", re.IGNORECASE),
    re.compile(r"kill\s+-9", re.IGNORECASE),
    re.compile(r"restart-computer", re.IGNORECASE),
    re.compile(r"stop-computer", re.IGNORECASE),
    re.compile(r"clear-recyclebin", re.IGNORECASE),
    re.compile(r"format\s+[a-z]:", re.IGNORECASE),
]

WARNING_PATTERNS = [
    re.compile(r"remove-item", re.IGNORECASE),
    re.compile(r"move-item", re.IGNORECASE),
    re.compile(r"restart-service", re.IGNORECASE),
    re.compile(r"stop-service", re.IGNORECASE),
    re.compile(r"set-executionpolicy", re.IGNORECASE),
    re.compile(r"clear-dnsclientcache", re.IGNORECASE),
]


def evaluate_command_risk(intent: CommandIntent) -> Tuple[RiskLevel, str | None]:
    """Return the risk level and reason for a given command intent."""
    if intent.risk_level:
        return intent.risk_level, intent.risk_reason

    cmd = intent.command
    for pattern in DANGEROUS_PATTERNS:
        if pattern.search(cmd):
            return RiskLevel.DANGEROUS, "Destructive operation that permanently deletes data or halts system processes."

    for pattern in WARNING_PATTERNS:
        if pattern.search(cmd):
            return RiskLevel.WARNING, "Modifies system state, file paths, or service configurations."

    return RiskLevel.SAFE, None


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
