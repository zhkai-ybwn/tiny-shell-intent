namespace TinyShell.Core.Models;

public static class MatchSource
{
    public const string RuleExact = "rule_exact";
    public const string RulePrefix = "rule_prefix";
    public const string Fuzzy = "fuzzy";
    public const string Model = "model";
    public const string Hybrid = "hybrid";
}

public enum ConfidenceLevel
{
    High,
    Medium,
    Low,
    Rejected
}

public static class ConfidenceLevelExtensions
{
    public static string ToSerializedString(this ConfidenceLevel level) => level switch
    {
        ConfidenceLevel.High => "high",
        ConfidenceLevel.Medium => "medium",
        ConfidenceLevel.Low => "low",
        ConfidenceLevel.Rejected => "rejected",
        _ => "rejected"
    };

    public static ConfidenceLevel FromString(string? value) => value?.ToLowerInvariant() switch
    {
        "high" => ConfidenceLevel.High,
        "medium" => ConfidenceLevel.Medium,
        "low" => ConfidenceLevel.Low,
        _ => ConfidenceLevel.Rejected
    };
}
