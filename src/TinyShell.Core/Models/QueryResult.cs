using System.Text.Json.Serialization;

namespace TinyShell.Core.Models;

public sealed class ParameterSlot
{
    [JsonPropertyName("name")]
    public string Name { get; set; } = string.Empty;

    [JsonPropertyName("type")]
    public string Type { get; set; } = "string";

    [JsonPropertyName("required")]
    public bool Required { get; set; } = true;

    [JsonPropertyName("placeholder")]
    public string Placeholder { get; set; } = string.Empty;

    [JsonPropertyName("description")]
    public string Description { get; set; } = string.Empty;
}

public sealed class CommandIntent
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = string.Empty;

    [JsonPropertyName("category")]
    public string Category { get; set; } = string.Empty;

    [JsonPropertyName("command")]
    public string Command { get; set; } = string.Empty;

    [JsonPropertyName("aliases")]
    public List<string> Aliases { get; set; } = new();

    [JsonPropertyName("description")]
    public string Description { get; set; } = string.Empty;

    [JsonPropertyName("keywords")]
    public List<string> Keywords { get; set; } = new();

    [JsonPropertyName("intent_phrases")]
    public List<string> IntentPhrases { get; set; } = new();

    [JsonPropertyName("risk_level")]
    public string RiskLevelString { get; set; } = "safe";

    [JsonIgnore]
    public RiskLevel RiskLevel => RiskLevelExtensions.FromString(RiskLevelString);

    [JsonPropertyName("risk_reason")]
    public string? RiskReason { get; set; }

    [JsonPropertyName("parameter_slots")]
    public List<ParameterSlot> ParameterSlots { get; set; } = new();
}

public sealed class Candidate
{
    public string Command { get; set; } = string.Empty;
    public string IntentId { get; set; } = string.Empty;
    public string Description { get; set; } = string.Empty;
    public float Score { get; set; }
    public string Source { get; set; } = MatchSource.Hybrid;
    public string RiskLevel { get; set; } = "safe";
    public string Category { get; set; } = string.Empty;
    public string? RiskReason { get; set; }
    public string CommandTemplate { get; set; } = string.Empty;
    public string? RenderedCommand { get; set; }
    public Dictionary<string, object> Parameters { get; set; } = new();
    public bool IsComplete { get; set; }
    public ConfidenceLevel ConfidenceLevel { get; set; } = ConfidenceLevel.High;

    public Candidate() { }

    internal Candidate Copy()
    {
        var copy = (Candidate)MemberwiseClone();
        // Extracted parameter values are immutable strings or boxed integers.
        copy.Parameters = new Dictionary<string, object>(Parameters);
        return copy;
    }

    public Candidate(
        string command,
        string intentId,
        string description,
        float score,
        string source,
        string riskLevel,
        string category,
        string? riskReason = null,
        string commandTemplate = "",
        bool isComplete = false)
    {
        Command = command;
        IntentId = intentId;
        Description = description;
        Score = score;
        Source = source;
        RiskLevel = riskLevel;
        Category = category;
        RiskReason = riskReason;
        CommandTemplate = string.IsNullOrEmpty(commandTemplate) ? command : commandTemplate;
        IsComplete = isComplete;
    }
}

public sealed class QueryResult
{
    public string Query { get; set; } = string.Empty;
    public List<Candidate> Candidates { get; set; } = new();
    public List<Candidate> DebugCandidates { get; set; } = new();
    public ConfidenceLevel ConfidenceLevel { get; set; } = ConfidenceLevel.High;
    public bool IsAccepted { get; set; } = true;
    public bool IsRejected { get; set; } = false;
    public string? RejectionReason { get; set; }
    public double LatencyMs { get; set; }
    public string Mode { get; set; } = "hybrid";
    public bool IsEmpty { get; set; } = false;
    public bool IsOutOfDomain { get; set; } = false;

    public Candidate? TopCandidate => Candidates.Count > 0 ? Candidates[0] : null;
    public Candidate? TopDebugCandidate => DebugCandidates.Count > 0 ? DebugCandidates[0] : null;

    internal QueryResult Copy()
    {
        var copy = (QueryResult)MemberwiseClone();
        copy.Candidates = Candidates.Select(candidate => candidate.Copy()).ToList();
        copy.DebugCandidates = DebugCandidates.Select(candidate => candidate.Copy()).ToList();
        return copy;
    }
}
