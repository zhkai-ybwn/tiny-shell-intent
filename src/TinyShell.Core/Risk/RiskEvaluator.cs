using System.Text.RegularExpressions;
using TinyShell.Core.Models;

namespace TinyShell.Core.Risk;

public static class RiskEvaluator
{
    private static readonly (Regex Pattern, string Reason)[] HighRiskRules = new[]
    {
        (new Regex(@"\bRemove-Item\b.*?-Recurse\b.*?-Force\b", RegexOptions.IgnoreCase | RegexOptions.Compiled),
         "Recursively force deletes folders without prompt or recycle bin safety."),
        (new Regex(@"\bStop-Process\b.*?-Force\b", RegexOptions.IgnoreCase | RegexOptions.Compiled),
         "Forcibly kills process immediately without saving unsaved data."),
        (new Regex(@"\b(?:Restart-Computer|Stop-Computer)\b.*?-Force\b", RegexOptions.IgnoreCase | RegexOptions.Compiled),
         "Forcibly shuts down or restarts the machine immediately."),
        (new Regex(@"\bClear-RecycleBin\b.*?-Force\b", RegexOptions.IgnoreCase | RegexOptions.Compiled),
         "Permanently purges all deleted files from the Recycle Bin."),
        (new Regex(@"\b(?:rm\s+-rf|rmdir\s+/s\s+/q|del\s+/f\s+/q|kill\s+-9)\b", RegexOptions.IgnoreCase | RegexOptions.Compiled),
         "Destructive deletion or immediate termination alias.")
    };

    private static readonly (Regex Pattern, string Reason)[] WarningRiskRules = new[]
    {
        (new Regex(@"\bRemove-Item\b", RegexOptions.IgnoreCase | RegexOptions.Compiled),
         "Deletes files or directories."),
        (new Regex(@"\bStop-Process\b", RegexOptions.IgnoreCase | RegexOptions.Compiled),
         "Stops a running process."),
        (new Regex(@"\b(?:Restart-Service|Stop-Service|Start-Service)\b", RegexOptions.IgnoreCase | RegexOptions.Compiled),
         "Modifies system service run states."),
        (new Regex(@"\bSet-ExecutionPolicy\b", RegexOptions.IgnoreCase | RegexOptions.Compiled),
         "Modifies script execution permissions."),
        (new Regex(@"\bMove-Item\b", RegexOptions.IgnoreCase | RegexOptions.Compiled),
         "Moves or renames files or directories.")
    };

    public static (RiskLevel level, string? reason) EvaluateCommandRisk(CommandIntent intent, string command)
    {
        string cmdToScan = string.IsNullOrEmpty(command) ? intent.Command : command;

        // 1. Scan for dangerous rules
        foreach (var (pattern, reason) in HighRiskRules)
        {
            if (pattern.IsMatch(cmdToScan) || pattern.IsMatch(intent.Command))
            {
                return (RiskLevel.Dangerous, reason);
            }
        }

        // 2. Scan for warning rules
        string? warnReason = null;
        bool isWarning = false;
        foreach (var (pattern, reason) in WarningRiskRules)
        {
            if (pattern.IsMatch(cmdToScan) || pattern.IsMatch(intent.Command))
            {
                isWarning = true;
                warnReason = reason;
                break;
            }
        }

        // Non-downgrading rule: take highest between base annotation and scanned risk
        var baseRisk = intent.RiskLevel;
        if (baseRisk == RiskLevel.Dangerous)
        {
            return (RiskLevel.Dangerous, intent.RiskReason ?? "Dangerous command");
        }

        if (isWarning || baseRisk == RiskLevel.Warning)
        {
            return (RiskLevel.Warning, warnReason ?? intent.RiskReason);
        }

        return (RiskLevel.Safe, null);
    }
}
