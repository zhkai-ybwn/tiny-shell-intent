namespace TinyShell.Core.Models;

public enum RiskLevel
{
    Safe = 1,
    Warning = 2,
    Dangerous = 3
}

public static class RiskLevelExtensions
{
    public static string ToSerializedString(this RiskLevel level) => level switch
    {
        RiskLevel.Safe => "safe",
        RiskLevel.Warning => "warning",
        RiskLevel.Dangerous => "dangerous",
        _ => "safe"
    };

    public static RiskLevel FromString(string? value) => value?.ToLowerInvariant() switch
    {
        "dangerous" => RiskLevel.Dangerous,
        "warning" => RiskLevel.Warning,
        _ => RiskLevel.Safe
    };
}
