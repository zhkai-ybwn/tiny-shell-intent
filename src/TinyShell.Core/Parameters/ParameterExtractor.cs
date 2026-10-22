using System.Text.RegularExpressions;
using TinyShell.Core.Models;

namespace TinyShell.Core.Parameters;

public static class ParameterExtractor
{
    private static readonly Regex PowerShellInjectionPattern = new(
        @"[;&|`$\n\r\x00]|(\$\()|(`\()|(\$\{[^}]*\})|(\[scriptblock\])",
        RegexOptions.IgnoreCase | RegexOptions.Compiled);

    private static readonly Regex Ipv4Pattern = new(
        @"^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$",
        RegexOptions.Compiled);

    private static readonly Regex HostnamePattern = new(
        @"^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$",
        RegexOptions.Compiled);

    private static readonly Regex Ipv4Regex = new(
        @"\b(?:\d{1,3}\.){3}\d{1,3}\b",
        RegexOptions.Compiled);

    private static readonly Regex UrlRegex = new(
        @"https?://[^\s'""]+",
        RegexOptions.IgnoreCase | RegexOptions.Compiled);

    private static readonly Regex FileExtRegex = new(
        @"\b[\w-]+\.(?:tmp|txt|log|json|csv|py|md|ps1|bak|xml|yml|yaml|ini|cfg|zip|tar|gz|sh|exe|dll)\b",
        RegexOptions.IgnoreCase | RegexOptions.Compiled);

    public static string EscapePowerShellLiteral(string value)
    {
        if (PowerShellInjectionPattern.IsMatch(value))
        {
            throw new ArgumentException($"Value contains prohibited PowerShell injection sequences: {value}");
        }

        string escaped = value.Replace("'", "''");
        return $"'{escaped}'";
    }

    public static bool ValidateParameterValue(ParameterSlot slot, object? val, out object? validatedVal, out string? error)
    {
        validatedVal = null;
        error = null;

        if (val == null)
        {
            error = "Missing value";
            return false;
        }

        string sVal = val.ToString()?.Trim() ?? string.Empty;
        if (string.IsNullOrEmpty(sVal))
        {
            error = "Empty parameter value";
            return false;
        }

        if (PowerShellInjectionPattern.IsMatch(sVal))
        {
            error = $"Dangerous command injection sequence detected in '{slot.Name}'";
            return false;
        }

        if (slot.Type == "int")
        {
            if (int.TryParse(sVal, out int num))
            {
                if (slot.Name == "port")
                {
                    if (num < 1 || num > 65535)
                    {
                        error = $"Port must be between 1 and 65535, got {num}";
                        return false;
                    }
                }
                else if (slot.Name == "pid")
                {
                    if (num <= 0)
                    {
                        error = $"PID must be positive integer, got {num}";
                        return false;
                    }
                }
                validatedVal = num;
                return true;
            }
            error = $"Expected integer for '{slot.Name}', got '{sVal}'";
            return false;
        }

        if (slot.Type == "hostname")
        {
            if (Ipv4Pattern.IsMatch(sVal) || HostnamePattern.IsMatch(sVal) || sVal.Equals("localhost", StringComparison.OrdinalIgnoreCase))
            {
                validatedVal = sVal;
                return true;
            }
            error = $"Invalid hostname or IP format for '{slot.Name}': '{sVal}'";
            return false;
        }

        if (slot.Type is "string" or "path")
        {
            if (sVal.Length > 255)
            {
                error = $"Value exceeds max length (255) for '{slot.Name}'";
                return false;
            }
            validatedVal = sVal;
            return true;
        }

        validatedVal = sVal;
        return true;
    }

    public static (string masked, Dictionary<string, string> entities) MaskStructuredEntities(string text)
    {
        var entities = new Dictionary<string, string>();
        string masked = text;

        masked = UrlRegex.Replace(masked, match =>
        {
            string key = $"__URL_{entities.Count}__";
            entities[key] = match.Value;
            return key;
        });

        masked = Ipv4Regex.Replace(masked, match =>
        {
            string key = $"__IP_{entities.Count}__";
            entities[key] = match.Value;
            return key;
        });

        return (masked, entities);
    }

    public static (Dictionary<string, object> parameters, bool isComplete) ExtractParametersFromQuery(CommandIntent intent, string query)
        => ExtractParameters(intent, query);

    public static (Dictionary<string, object> parameters, bool isComplete) ExtractParameters(CommandIntent intent, string query)
    {
        bool hasPlaceholders = Regex.IsMatch(intent.Command, @"<[^>]+>");
        if (intent.ParameterSlots.Count == 0)
        {
            return (new Dictionary<string, object>(), !hasPlaceholders);
        }

        string cleanQ = query.Trim();
        var extracted = new Dictionary<string, object>();
        var slotsByName = intent.ParameterSlots.ToDictionary(s => s.Name, s => s, StringComparer.OrdinalIgnoreCase);

        var (maskedQ, _) = MaskStructuredEntities(cleanQ);

        // 1. net_test_port & net_listening_ports
        if (intent.Id is "net_test_port" or "net_listening_ports")
        {
            var portMatch = Regex.Match(maskedQ, @"\bport\s*[:=]?\s*(\d{1,5})\b", RegexOptions.IgnoreCase);
            if (!portMatch.Success) portMatch = Regex.Match(maskedQ, @"\bon\s+port\s+(\d{1,5})\b", RegexOptions.IgnoreCase);
            if (!portMatch.Success) portMatch = Regex.Match(maskedQ, @"\busing\s+port\s+(\d{1,5})\b", RegexOptions.IgnoreCase);
            if (!portMatch.Success) portMatch = Regex.Match(maskedQ, @"\b(\d{1,5})\s*/(?:tcp|udp)\b", RegexOptions.IgnoreCase);
            if (!portMatch.Success) portMatch = Regex.Match(maskedQ, @"(?<![\.\d]):(\d{1,5})\b");

            if (portMatch.Success)
            {
                extracted["port"] = portMatch.Groups[1].Value;
            }

            if (intent.Id == "net_test_port")
            {
                var ipM = Ipv4Regex.Match(cleanQ);
                if (ipM.Success)
                {
                    extracted["host"] = ipM.Value;
                }
                else if (Regex.IsMatch(cleanQ, @"\blocalhost\b", RegexOptions.IgnoreCase))
                {
                    extracted["host"] = "localhost";
                }
                else
                {
                    var hostM = Regex.Match(cleanQ, @"\b(?:on|to|host|server|at)\s+([a-zA-Z0-9.-]+)\b", RegexOptions.IgnoreCase);
                    if (hostM.Success && !int.TryParse(hostM.Groups[1].Value, out _))
                    {
                        extracted["host"] = hostM.Groups[1].Value;
                    }
                }
            }
        }
        // 2. net_ping_host & net_trace_route
        else if (intent.Id is "net_ping_host" or "net_trace_route")
        {
            var ipM = Ipv4Regex.Match(cleanQ);
            if (ipM.Success)
            {
                extracted["host"] = ipM.Value;
            }
            else if (Regex.IsMatch(cleanQ, @"\blocalhost\b", RegexOptions.IgnoreCase))
            {
                extracted["host"] = "localhost";
            }
            else
            {
                var hostM = Regex.Match(cleanQ, @"\b(?:ping|to|target|reach|gateway|host|server|traceroute)\s+([a-zA-Z0-9.-]+)\b", RegexOptions.IgnoreCase);
                if (hostM.Success && !int.TryParse(hostM.Groups[1].Value, out _))
                {
                    extracted["host"] = hostM.Groups[1].Value;
                }
            }
        }
        // 3. net_dns_resolve
        else if (intent.Id == "net_dns_resolve")
        {
            var m = Regex.Match(cleanQ, @"\b(?:resolve|lookup|dns|name)\s+([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\b", RegexOptions.IgnoreCase);
            if (!m.Success) m = Regex.Match(cleanQ, @"\b([a-zA-Z0-9-]+\.[a-zA-Z]{2,})\b");
            if (m.Success)
            {
                extracted["domain"] = m.Groups[1].Value;
            }
        }
        // 4. proc_kill_id
        else if (intent.Id == "proc_kill_id")
        {
            var pidM = Regex.Match(maskedQ, @"\b(?:pid|process\s*id|task\s*id)\s*[:=]?\s*(\d{2,7})\b", RegexOptions.IgnoreCase);
            if (!pidM.Success) pidM = Regex.Match(maskedQ, @"\b(?:kill|terminate|stop-process)\s+(?:-id\s+)?(\d{2,7})\b", RegexOptions.IgnoreCase);
            if (!pidM.Success) pidM = Regex.Match(maskedQ, @"\bprocess\s+(\d{2,7})\b", RegexOptions.IgnoreCase);
            if (!pidM.Success && (cleanQ.Contains("kill", StringComparison.OrdinalIgnoreCase) || cleanQ.Contains("terminate", StringComparison.OrdinalIgnoreCase) || cleanQ.Contains("stop", StringComparison.OrdinalIgnoreCase)))
            {
                pidM = Regex.Match(maskedQ, @"\b(\d{2,7})\b");
            }

            if (pidM.Success)
            {
                extracted["pid"] = pidM.Groups[1].Value;
            }
        }
        // 5. proc_kill_name & proc_wait
        else if (intent.Id is "proc_kill_name" or "proc_wait")
        {
            var nameM = Regex.Match(cleanQ, @"\b(?:process\s+named|named|kill|stop-process|wait-process|wait\s+for)\s+([a-zA-Z_][a-zA-Z0-9_.-]*)\b", RegexOptions.IgnoreCase);
            if (nameM.Success)
            {
                string procVal = nameM.Groups[1].Value.ToLowerInvariant();
                if (procVal is not ("process" or "immediately" or "force" or "task" or "named" or "id" or "pid" or "for"))
                {
                    extracted["name"] = procVal;
                }
            }
            else if (cleanQ.Split(' ', StringSplitOptions.RemoveEmptyEntries).Length == 2)
            {
                var parts = cleanQ.Split(' ', StringSplitOptions.RemoveEmptyEntries);
                if (parts[0].Equals("kill", StringComparison.OrdinalIgnoreCase) || parts[0].Equals("pkill", StringComparison.OrdinalIgnoreCase))
                {
                    if (!int.TryParse(parts[1], out _))
                    {
                        extracted["name"] = parts[1];
                    }
                }
            }
        }
        // 6. proc_find
        else if (intent.Id == "proc_find")
        {
            var m = Regex.Match(cleanQ, @"\b(?:if|find|check|search\s+for|is\s+my)\s+([a-zA-Z_][a-zA-Z0-9_.-]*)\s+(?:daemon|service|process|is\s+running|running|open)?\b", RegexOptions.IgnoreCase);
            if (m.Success)
            {
                string cand = m.Groups[1].Value.ToLowerInvariant();
                if (cand is not ("a" or "the" or "my" or "process" or "service" or "daemon" or "if"))
                {
                    extracted["name"] = cand;
                }
            }
        }
        // 7. proc_start
        else if (intent.Id == "proc_start")
        {
            var m = Regex.Match(cleanQ, @"\b(?:start|launch|run|open|exec)\s+([a-zA-Z_][a-zA-Z0-9_.-]*)\b", RegexOptions.IgnoreCase);
            if (m.Success)
            {
                string cand = m.Groups[1].Value.ToLowerInvariant();
                if (cand is not ("a" or "the" or "program" or "app" or "application" or "as" or "with" or "process"))
                {
                    extracted["program"] = cand;
                }
            }
            var argsM = Regex.Match(cleanQ, @"\b(?:with\s+arguments?|args?)\s+(.+)$", RegexOptions.IgnoreCase);
            if (argsM.Success)
            {
                extracted["args"] = argsM.Groups[1].Value.Trim();
            }
        }
        // 8. sys_service_*
        else if (intent.Id is "sys_service_restart" or "sys_service_stop" or "sys_service_start")
        {
            var srvM = Regex.Match(cleanQ, @"\b(?:restart|stop|start|bounce)\s+([a-zA-Z0-9_.-]+)\s+(?:service|daemon)?\b", RegexOptions.IgnoreCase);
            if (srvM.Success)
            {
                string cand = srvM.Groups[1].Value;
                if (cand.ToLowerInvariant() is not ("service" or "daemon" or "windows" or "the" or "a"))
                {
                    extracted["service"] = cand;
                }
            }
        }
        // 9. Single file ops
        else if (intent.Id is "file_delete_single" or "file_test_exists" or "file_read_head" or "file_read_tail" or "file_count_lines" or "file_checksum_sha256")
        {
            var fileM = FileExtRegex.Match(cleanQ);
            if (fileM.Success)
            {
                string targetFile = fileM.Value;
                string slotName = slotsByName.ContainsKey("path") ? "path" : "file";
                extracted[slotName] = targetFile;
            }
            else
            {
                var qStr = Regex.Match(cleanQ, @"['""]([^'""]+)['""]");
                if (qStr.Success)
                {
                    string slotName = slotsByName.ContainsKey("path") ? "path" : "file";
                    extracted[slotName] = qStr.Groups[1].Value;
                }
            }
        }
        // 10. env_get_value
        else if (intent.Id == "env_get_value")
        {
            var tokens = cleanQ.Split(' ', StringSplitOptions.RemoveEmptyEntries);
            foreach (var token in tokens)
            {
                string cleanToken = token.Trim('$', '%', ':', ';', ',', '.');
                if (cleanToken.Length >= 2 && cleanToken.All(char.IsUpper) && cleanToken is not ("GET" or "CHECK" or "WHAT" or "SET" or "TO" or "IS" or "ENV"))
                {
                    extracted["variable_name"] = cleanToken;
                    break;
                }
            }
        }
        // 11. env_set_temp
        else if (intent.Id == "env_set_temp")
        {
            var m = Regex.Match(cleanQ, @"\bset\s+([A-Z_][A-Z0-9_]*)\s+(?:to|=)\s+([^\s]+)", RegexOptions.IgnoreCase);
            if (m.Success)
            {
                extracted["variable_name"] = m.Groups[1].Value;
                extracted["value"] = m.Groups[2].Value;
            }
        }

        // Validate extracted parameters
        var validated = new Dictionary<string, object>();
        foreach (var (name, rawVal) in extracted)
        {
            if (slotsByName.TryGetValue(name, out var slot))
            {
                if (ValidateParameterValue(slot, rawVal, out var val, out _))
                {
                    validated[name] = val!;
                }
            }
        }

        bool isComplete = true;
        foreach (var slot in intent.ParameterSlots)
        {
            if (slot.Required && !validated.ContainsKey(slot.Name))
            {
                isComplete = false;
                break;
            }
        }

        return (validated, isComplete);
    }

    public static string? RenderCommandSafely(string template, CommandIntent intent, Dictionary<string, object> parameters)
    {
        if (parameters.Count == 0 && intent.ParameterSlots.Count > 0)
        {
            // If all slots are optional, check if required slots exist
            bool hasRequired = intent.ParameterSlots.Any(s => s.Required);
            if (hasRequired) return null;
        }

        string rendered = template;
        foreach (var slot in intent.ParameterSlots)
        {
            string placeholder = slot.Placeholder;
            if (string.IsNullOrEmpty(placeholder) || !rendered.Contains(placeholder))
            {
                continue;
            }

            if (!parameters.TryGetValue(slot.Name, out var val))
            {
                if (slot.Required)
                {
                    return null;
                }
                else
                {
                    // Clean up optional parameter clause
                    rendered = Regex.Replace(rendered, $@"\s*-[a-zA-Z0-9_]+\s+[""']?{Regex.Escape(placeholder)}[""']?", "");
                    rendered = rendered.Replace($"\"{placeholder}\"", "").Replace(placeholder, "").Trim();
                    continue;
                }
            }

            if (slot.Type == "int")
            {
                rendered = rendered.Replace(placeholder, val.ToString());
            }
            else if (slot.Type is "hostname" or "string" or "path")
            {
                string quotedPlaceholder = $"\"{placeholder}\"";
                string singleQuotedVal = EscapePowerShellLiteral(val.ToString() ?? "");

                if (rendered.Contains(quotedPlaceholder))
                {
                    rendered = rendered.Replace(quotedPlaceholder, singleQuotedVal);
                }
                else
                {
                    string sVal = val.ToString() ?? "";
                    if (slot.Type == "hostname" && (HostnamePattern.IsMatch(sVal) || Ipv4Pattern.IsMatch(sVal)))
                    {
                        rendered = rendered.Replace(placeholder, sVal);
                    }
                    else
                    {
                        rendered = rendered.Replace(placeholder, singleQuotedVal);
                    }
                }
            }
        }

        // If any unresolved placeholder remains in the rendered string, it is NOT executable
        if (Regex.IsMatch(rendered, @"<[^>]+>"))
        {
            return null;
        }

        return rendered;
    }
}
