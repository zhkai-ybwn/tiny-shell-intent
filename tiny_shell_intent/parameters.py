"""Parameter extraction, validation, and safe PowerShell command rendering."""

import re
from typing import Any, Dict, List, Optional, Tuple
from .schema import ParameterSlot, CommandIntent

# Dangerous characters and patterns in PowerShell that could lead to command injection
POWERSHELL_INJECTION_PATTERN = re.compile(
    r"[;&|`$\n\r\x00\u2018-\u201f]|(\$\()|(`\()|(\$\{[^}]*\})|(\[scriptblock\])",
    re.IGNORECASE,
)

IPV4_PATTERN = re.compile(
    r"^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$"
)

HOSTNAME_PATTERN = re.compile(
    r"^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
)

# Regex helpers for entity extraction and entity protection
IPV4_REGEX = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
URL_REGEX = re.compile(r"https?://[^\s'\"]+", re.IGNORECASE)
FILE_EXT_REGEX = re.compile(
    r"\b[\w-]+\.(?:tmp|txt|log|json|csv|py|md|ps1|bak|xml|yml|yaml|ini|cfg|zip|tar|gz|sh|exe|dll)\b",
    re.IGNORECASE,
)
ENV_VAR_REGEX = re.compile(r"\b([A-Z_][A-Z0-9_]{1,63})\b")


def mask_structured_entities(text: str) -> Tuple[str, Dict[str, str]]:
    """Mask IP addresses, URLs, and paths to protect them during numeric/token extraction.

    This prevents standalone port/PID regexes from accidentally matching subfields of
    IP addresses (e.g. matching '192' in '192.168.1.1').
    """
    masked = text
    entities: Dict[str, str] = {}

    # 1. Mask URLs
    def _url_sub(match):
        key = f"__URL_{len(entities)}__"
        entities[key] = match.group(0)
        return key
    masked = URL_REGEX.sub(_url_sub, masked)

    # 2. Mask IPv4 addresses
    def _ip_sub(match):
        key = f"__IP_{len(entities)}__"
        entities[key] = match.group(0)
        return key
    masked = IPV4_REGEX.sub(_ip_sub, masked)

    return masked, entities


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

    if slot.name == "variable_name" and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", s_val):
        return False, None, "Invalid environment variable identifier"

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


def _unquoted_file_targets(query: str) -> List[str]:
    return [token for token in query.split()
            if "\\" in token or "/" in token or FILE_EXT_REGEX.fullmatch(token)]


def _extract_file_target(query: str) -> Optional[str]:
    """Keep full paths; ambiguous targets must not silently become basenames."""
    quoted_pattern = (r'"(?P<double>[^"]+)"|' r"'(?P<single>(?:[^']|'')+)'")
    quoted = list(re.finditer(quoted_pattern, query))
    if quoted:
        if len(quoted) != 1:
            return None
        match = quoted[0]
        remainder = query[:match.start()] + query[match.end():]
        if '"' in remainder or "'" in remainder or _unquoted_file_targets(remainder):
            return None
        if match.group("double") is not None:
            return match.group("double")
        return match.group("single").replace("''", "'")
    if '"' in query or "'" in query:
        return None
    targets = _unquoted_file_targets(query)
    return targets[0] if len(targets) == 1 else None


def extract_parameters_from_query(
    intent: CommandIntent,
    query: str,
) -> Tuple[Dict[str, Any], bool]:
    """Extract, validate, and return parameters for a given intent.

    Returns:
        (extracted_dict, is_complete)
    """
    has_placeholders = bool(re.search(r"<[^>]+>", intent.command))

    if not intent.parameter_slots:
        # If template contains placeholders but no slots are defined, it cannot be complete!
        return {}, not has_placeholders

    clean_q = query.strip()
    extracted: Dict[str, Any] = {}
    slots_by_name = {s.name: s for s in intent.parameter_slots}

    # Mask structured entities (IP addresses, URLs) to avoid mis-extracting subfields
    masked_q, entity_map = mask_structured_entities(clean_q)

    # 1. net_test_port & net_listening_ports
    if intent.id in ("net_test_port", "net_listening_ports"):
        # Port extraction: STRICT context required. Never extract arbitrary digits!
        port_match = re.search(r"\bport\s*[:=]?\s*(\d{1,5})\b", masked_q, re.IGNORECASE)
        if not port_match:
            port_match = re.search(r"\bon\s+port\s+(\d{1,5})\b", masked_q, re.IGNORECASE)
        if not port_match:
            port_match = re.search(r"\busing\s+port\s+(\d{1,5})\b", masked_q, re.IGNORECASE)
        if not port_match:
            port_match = re.search(r"\b(\d{1,5})\s*/(?:tcp|udp)\b", masked_q, re.IGNORECASE)
        if not port_match:
            # Match colon-separated port (e.g. localhost:8080) on masked string (IPs are protected)
            port_match = re.search(r"(?<![\.\d]):(\d{1,5})\b", masked_q)

        if port_match:
            extracted["port"] = port_match.group(1)

        # Host extraction (for net_test_port only)
        if intent.id == "net_test_port":
            ip_m = IPV4_REGEX.search(clean_q)
            if ip_m:
                extracted["host"] = ip_m.group(0)
            elif re.search(r"\blocalhost\b", clean_q, re.IGNORECASE):
                extracted["host"] = "localhost"
            else:
                host_m = re.search(r"\b(?:on|to|host|server|at)\s+([a-zA-Z0-9.-]+)\b", clean_q, re.IGNORECASE)
                if host_m and not host_m.group(1).isdigit():
                    extracted["host"] = host_m.group(1)

    # 2. net_ping_host & net_trace_route (host)
    elif intent.id in ("net_ping_host", "net_trace_route"):
        ip_m = IPV4_REGEX.search(clean_q)
        if ip_m:
            extracted["host"] = ip_m.group(0)
        elif re.search(r"\blocalhost\b", clean_q, re.IGNORECASE):
            extracted["host"] = "localhost"
        else:
            host_m = re.search(
                r"\b(?:ping|to|target|reach|gateway|host|server|traceroute)\s+([a-zA-Z0-9.-]+)\b",
                clean_q,
                re.IGNORECASE,
            )
            if host_m and not host_m.group(1).isdigit():
                extracted["host"] = host_m.group(1)

    # 3. net_dns_resolve (domain)
    elif intent.id == "net_dns_resolve":
        m = re.search(r"\b(?:resolve|lookup|dns|name)\s+([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\b", clean_q, re.IGNORECASE)
        if not m:
            m = re.search(r"\b([a-zA-Z0-9-]+\.[a-zA-Z]{2,})\b", clean_q)
        if m:
            extracted["domain"] = m.group(1)

    # 4. proc_kill_id (pid)
    elif intent.id == "proc_kill_id":
        # Search on masked_q so subfields of IPs or URLs are not treated as PIDs
        pid_m = re.search(r"\b(?:pid|process\s*id|task\s*id)\s*[:=]?\s*(\d{2,7})\b", masked_q, re.IGNORECASE)
        if not pid_m:
            pid_m = re.search(r"\b(?:kill|terminate|stop-process)\s+(?:-id\s+)?(\d{2,7})\b", masked_q, re.IGNORECASE)
        if not pid_m:
            pid_m = re.search(r"\bprocess\s+(\d{2,7})\b", masked_q, re.IGNORECASE)
        if not pid_m and any(w in clean_q.lower() for w in ("kill", "terminate", "stop")):
            # Fallback to standalone number only if action keyword is explicitly kill/stop
            pid_m = re.search(r"\b(\d{2,7})\b", masked_q)

        if pid_m:
            extracted["pid"] = pid_m.group(1)

    # 5. proc_kill_name & proc_wait (name)
    elif intent.id in ("proc_kill_name", "proc_wait"):
        name_m = re.search(
            r"\b(?:process\s+named|named|kill|stop-process|wait-process|wait\s+for)\s+([a-zA-Z_][a-zA-Z0-9_.-]*)\b",
            clean_q,
            re.IGNORECASE,
        )
        if name_m:
            proc_val = name_m.group(1).lower()
            if proc_val not in ("process", "immediately", "force", "task", "named", "id", "pid", "for"):
                extracted["name"] = proc_val
        elif len(clean_q.split()) == 2 and clean_q.split()[0].lower() in ("kill", "pkill"):
            second = clean_q.split()[1]
            if not second.isdigit():
                extracted["name"] = second

    # 6. proc_find (name)
    elif intent.id == "proc_find":
        m = re.search(
            r"\b(?:if|find|check|search\s+for|is\s+my)\s+([a-zA-Z_][a-zA-Z0-9_.-]*)\s+(?:daemon|service|process|is\s+running|running|open)?\b",
            clean_q,
            re.IGNORECASE,
        )
        if m:
            cand = m.group(1).lower()
            if cand not in ("a", "the", "my", "process", "service", "daemon", "if"):
                extracted["name"] = cand

    # 7. sys_service_* (service)
    elif intent.id in ("sys_service_restart", "sys_service_stop", "sys_service_start"):
        srv_m = re.search(
            r"\b(?:restart|stop|start|bounce)\s+([a-zA-Z0-9_.-]+)\s+(?:service|daemon)?\b",
            clean_q,
            re.IGNORECASE,
        )
        if srv_m:
            cand = srv_m.group(1)
            if cand.lower() not in ("service", "daemon", "windows", "the", "a"):
                extracted["service"] = cand

    # 8. Single file operations: file_delete_single, file_test_exists, file_read_head, file_read_tail, etc.
    elif intent.id in ("file_delete_single", "file_test_exists", "file_read_head", "file_read_tail", "file_count_lines", "file_checksum_sha256"):
        target_file = _extract_file_target(clean_q)
        if target_file is not None:
            slot_name = "path" if "path" in slots_by_name else "file"
            extracted[slot_name] = target_file

    # 9. Environment variable queries
    elif intent.id == "env_get_value":
        # Look for uppercase identifier (e.g. USERPROFILE, PATH, TEMP)
        for token in clean_q.split():
            clean_token = token.strip("$%:;,.")
            if re.fullmatch(r"[A-Z_][A-Z0-9_]+", clean_token) and clean_token not in ("GET", "CHECK", "WHAT", "SET", "TO", "IS", "ENV"):
                extracted["variable_name"] = clean_token
                break

    elif intent.id == "env_set_temp":
        # e.g. "set NODE_ENV to production in this console"
        m = re.search(r"\bset\s+([A-Z_][A-Z0-9_]*)\s+(?:to|=)\s+([^\s]+)", clean_q, re.IGNORECASE)
        if m:
            extracted["variable_name"] = m.group(1)
            extracted["value"] = m.group(2)

    # 10. Process start
    elif intent.id == "proc_start":
        m = re.search(r"\b(?:start|launch|run|open|exec)\s+([a-zA-Z_][a-zA-Z0-9_.-]*)\b", clean_q, re.IGNORECASE)
        if m:
            cand = m.group(1).lower()
            if cand not in ("a", "the", "program", "app", "application", "as", "with", "process"):
                extracted["program"] = cand
        args_m = re.search(r"\b(?:with\s+arguments?|args?)\s+(.+)$", clean_q, re.IGNORECASE)
        if args_m:
            extracted["args"] = args_m.group(1).strip()

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
        Rendered command string, or None if required parameters are missing or
        unresolved placeholders remain.
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
            else:
                # If optional slot is omitted, clean up its parameter clause (e.g. -ArgumentList "<args>")
                rendered = re.sub(rf'\s*-[a-zA-Z0-9_]+\s+["\']?{re.escape(placeholder)}["\']?', '', rendered)
                rendered = rendered.replace(f'"{placeholder}"', '').replace(placeholder, '').strip()
                continue

        val = parameters[slot.name]
        if slot.name == "variable_name" and intent.id in ("env_get_value", "env_set_temp"):
            name = str(val)
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                return None
            rendered = rendered.replace(placeholder, name)
        elif slot.type == "int":
            rendered = rendered.replace(placeholder, str(val))
        elif slot.type in ("hostname", "string", "path"):
            quoted_placeholder = f'"{placeholder}"'
            single_quoted_val = escape_powershell_literal(str(val))
            if quoted_placeholder in rendered:
                rendered = rendered.replace(quoted_placeholder, single_quoted_val)
            else:
                if slot.type == "hostname" and (HOSTNAME_PATTERN.match(str(val)) or IPV4_PATTERN.match(str(val))):
                    rendered = rendered.replace(placeholder, str(val))
                else:
                    rendered = rendered.replace(placeholder, single_quoted_val)

    # If any unresolved placeholder remains in the rendered string, it is NOT executable!
    if re.search(r"<[^>]+>", rendered):
        return None

    return rendered
