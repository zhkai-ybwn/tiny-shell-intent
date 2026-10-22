"""Parameter extraction, validation, and safe PowerShell command rendering."""

import re
from typing import Any, Dict, List, Optional, Tuple
from .schema import ParameterSlot, CommandIntent

# Dangerous characters and patterns in PowerShell that could lead to command injection
POWERSHELL_INJECTION_PATTERN = re.compile(
    r"[;&|`$\n\r\x00]|(\$\()|(`\()|(\$\{[^}]*\})|(\[scriptblock\])",
    re.IGNORECASE,
)

IPV4_PATTERN = re.compile(
    r"^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$"
)

HOSTNAME_PATTERN = re.compile(
    r"^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
)


def escape_powershell_literal(value: str) -> str:
    """Safely format a string as a PowerShell single-quoted literal.

    In PowerShell, single-quoted strings are verbatim literals.
    Variables ($var), subexpressions ($(...)), and backtick escapes are NOT evaluated.
    The only escaped character is a single quote itself, doubled as ''.
    """
    if POWERSHELL_INJECTION_PATTERN.search(value):
        raise ValueError(f"Value contains prohibited PowerShell injection sequences: {value!r}")

    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def validate_parameter_value(slot: ParameterSlot, val: Any) -> Tuple[bool, Any, Optional[str]]:
    """Validate a parameter's type, range, and injection safety."""
    if val is None:
        return False, None, "Missing value"

    s_val = str(val).strip()
    if not s_val:
        return False, None, "Empty parameter value"

    # Check for prohibited command injection characters
    if POWERSHELL_INJECTION_PATTERN.search(s_val):
        return False, None, f"Dangerous command injection sequence detected in '{slot.name}'"

    if slot.type == "int":
        try:
            num = int(s_val)
            if slot.name == "port":
                if not (1 <= num <= 65535):
                    return False, None, f"Port must be between 1 and 65535, got {num}"
            elif slot.name == "pid":
                if not (1 <= num <= 2147483647):
                    return False, None, f"PID must be positive integer, got {num}"
            return True, num, None
        except ValueError:
            return False, None, f"Expected integer for '{slot.name}', got {s_val!r}"

    if slot.type == "hostname":
        # Check IPv4 or hostname format
        if IPV4_PATTERN.match(s_val) or HOSTNAME_PATTERN.match(s_val) or s_val.lower() == "localhost":
            return True, s_val, None
        return False, None, f"Invalid hostname or IP format for '{slot.name}': {s_val!r}"

    if slot.type == "string" or slot.type == "path":
        # Check length & forbidden characters
        if len(s_val) > 255:
            return False, None, f"Value exceeds max length (255) for '{slot.name}'"
        return True, s_val, None

    return True, s_val, None


def extract_parameters_from_query(
    intent: CommandIntent,
    query: str,
) -> Tuple[Dict[str, Any], bool]:
    """Extract, validate, and return parameters for a given intent.

    Returns:
        (extracted_dict, is_complete)
    """
    if not intent.parameter_slots:
        # Intent does not require any parameters
        return {}, True

    clean_q = query.strip()
    extracted: Dict[str, Any] = {}
    slots_by_name = {s.name: s for s in intent.parameter_slots}

    # Intent-specific rule-based extraction
    if intent.id == "net_test_port":
        # 1. Port extraction (e.g. "port 8080", "8080", ":8080")
        port_match = re.search(r"\bport\s*[:=]?\s*(\d{1,5})\b", clean_q, re.IGNORECASE)
        if not port_match:
            port_match = re.search(r":(\d{1,5})\b", clean_q)
        if not port_match:
            # Standalone digits if preceding word is host or following word is on/port
            port_match = re.search(r"\b(\d{2,5})\b", clean_q)

        if port_match:
            extracted["port"] = port_match.group(1)

        # 2. Host extraction (e.g. "on localhost", "to 192.168.1.1", "host api.com")
        host_match = re.search(r"\b(?:on|to|host|server|at)\s+([a-zA-Z0-9.-]+)\b", clean_q, re.IGNORECASE)
        if not host_match:
            # Check for standalone IPv4 or "localhost"
            ip_m = re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", clean_q)
            if ip_m:
                extracted["host"] = ip_m.group(0)
            elif re.search(r"\blocalhost\b", clean_q, re.IGNORECASE):
                extracted["host"] = "localhost"
        else:
            cand_host = host_match.group(1)
            # Avoid picking up numbers as host
            if not cand_host.isdigit():
                extracted["host"] = cand_host

    elif intent.id == "net_ping_host":
        ip_m = re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", clean_q)
        if ip_m:
            extracted["host"] = ip_m.group(0)
        else:
            host_m = re.search(r"\b(?:ping|to|target|reach)\s+([a-zA-Z0-9.-]+)\b", clean_q, re.IGNORECASE)
            if host_m and not host_m.group(1).isdigit():
                extracted["host"] = host_m.group(1)

    elif intent.id == "proc_kill_id":
        pid_m = re.search(r"\b(?:pid|process|id|task)?\s*[:=]?\s*(\d{2,7})\b", clean_q, re.IGNORECASE)
        if not pid_m:
            pid_m = re.search(r"\b(\d{2,7})\b", clean_q)
        if pid_m:
            extracted["pid"] = pid_m.group(1)

    elif intent.id == "proc_kill_name":
        # If query has digit PID, it shouldn't be captured as a process name!
        name_m = re.search(r"\b(?:process\s+named|named|kill|stop-process)\s+([a-zA-Z_][a-zA-Z0-9_.-]*)\b", clean_q, re.IGNORECASE)
        if name_m:
            proc_val = name_m.group(1).lower()
            if proc_val not in ("process", "immediately", "force", "task", "named", "id", "pid"):
                extracted["name"] = proc_val
        elif len(clean_q.split()) == 2 and clean_q.split()[0].lower() in ("kill", "pkill"):
            second = clean_q.split()[1]
            if not second.isdigit():
                extracted["name"] = second

    elif intent.id == "proc_find":
        m = re.search(r"\b(?:if|find|check|search\s+for)\s+([a-zA-Z_][a-zA-Z0-9_.-]*)\s+(?:is\s+running|is\s+open|process)?\b", clean_q, re.IGNORECASE)
        if m:
            extracted["name"] = m.group(1)

    elif intent.id in ("sys_service_restart", "sys_service_stop", "sys_service_start"):
        # e.g. "restart spooler printing service" -> service="spooler"
        srv_m = re.search(r"\b(?:restart|stop|start|bounce)\s+([a-zA-Z0-9_.-]+)\s+(?:service|daemon)?\b", clean_q, re.IGNORECASE)
        if srv_m:
            cand = srv_m.group(1)
            if cand.lower() not in ("service", "daemon", "windows", "the", "a"):
                extracted["service"] = cand

    # Validate all extracted parameters
    validated: Dict[str, Any] = {}
    for name, raw_val in extracted.items():
        if name in slots_by_name:
            slot = slots_by_name[name]
            ok, val, err = validate_parameter_value(slot, raw_val)
            if ok:
                validated[name] = val

    # Check if all required slots are satisfied
    is_complete = True
    for slot in intent.parameter_slots:
        if slot.required and slot.name not in validated:
            is_complete = False
            break

    return validated, is_complete


def render_command_safely(
    template: str,
    intent: CommandIntent,
    parameters: Dict[str, Any],
) -> Optional[str]:
    """Render a PowerShell command template safely replacing placeholders.

    Returns:
        Rendered command string, or None if required parameters are missing.
    """
    if not parameters and intent.parameter_slots:
        return None

    rendered = template
    for slot in intent.parameter_slots:
        placeholder = slot.placeholder
        if not placeholder or placeholder not in rendered:
            continue

        if slot.name not in parameters:
            if slot.required:
                return None
            continue

        val = parameters[slot.name]
        if slot.type == "int":
            rendered = rendered.replace(placeholder, str(val))
        elif slot.type in ("hostname", "string", "path"):
            # If the placeholder is enclosed in quotes in the template (e.g. "<name>"),
            # replace "<name>" with the single-quoted literal, or replace <name> safely
            quoted_placeholder = f'"{placeholder}"'
            single_quoted_val = escape_powershell_literal(str(val))
            if quoted_placeholder in rendered:
                rendered = rendered.replace(quoted_placeholder, single_quoted_val)
            else:
                # If slot is hostname, unquoted safe hostname or single quoted
                if slot.type == "hostname" and (HOSTNAME_PATTERN.match(str(val)) or IPV4_PATTERN.match(str(val))):
                    rendered = rendered.replace(placeholder, str(val))
                else:
                    rendered = rendered.replace(placeholder, single_quoted_val)

    # If any unresolved required placeholder remains, render is incomplete
    for slot in intent.parameter_slots:
        if slot.required and slot.placeholder in rendered:
            return None

    return rendered
