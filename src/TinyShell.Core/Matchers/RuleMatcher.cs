using TinyShell.Core.Models;
using TinyShell.Core.Storage;

namespace TinyShell.Core.Matchers;

public sealed class RuleMatcher : IMatcher
{
    private static readonly HashSet<string> NaturalLanguageMarkers = new(StringComparer.OrdinalIgnoreCase)
    {
        "how", "what", "which", "where", "why", "is", "are", "can", "does", "do",
        "please", "should", "would", "could", "to", "from", "over", "into", "with",
        "without", "after", "before", "immediately", "completely", "recursively",
        "all", "the", "my", "this", "that", "these", "those", "process", "service",
        "running", "started", "stopped", "turned", "on", "off", "folder", "directory",
        "file", "files", "lines", "notes", "machine", "computer", "server", "host",
    };

    private readonly KnowledgeBaseStore _store;

    public RuleMatcher(KnowledgeBaseStore store)
    {
        _store = store;
    }

    public List<Candidate> Match(string query, int topK = 3)
    {
        string cleanQ = query.Trim().ToLowerInvariant();
        if (string.IsNullOrEmpty(cleanQ))
        {
            return new List<Candidate>();
        }

        var candidates = new List<Candidate>();
        var seenIds = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        // 1. Exact match against alias or canonical command
        var exactMatches = MatchExact(cleanQ);
        foreach (var cand in exactMatches)
        {
            if (seenIds.Add(cand.IntentId))
            {
                candidates.Add(cand);
            }
            if (candidates.Count >= topK)
            {
                return candidates.Take(topK).ToList();
            }
        }

        // 2. Structured CLI invocation (e.g. "kill 1234", "curl http://...", "rm file.txt")
        var words = cleanQ.Split(' ', StringSplitOptions.RemoveEmptyEntries);
        if (words.Length >= 2)
        {
            var cliMatches = MatchCliInvocation(words, seenIds);
            foreach (var cand in cliMatches)
            {
                if (seenIds.Add(cand.IntentId))
                {
                    candidates.Add(cand);
                }
                if (candidates.Count >= topK)
                {
                    return candidates.Take(topK).ToList();
                }
            }
        }

        // 3. Prefix matching: only for single tokens with >= 2 chars
        if (candidates.Count < topK && words.Length == 1 && cleanQ.Length >= 2)
        {
            var prefixMatches = MatchPrefix(cleanQ, seenIds);
            foreach (var cand in prefixMatches)
            {
                if (seenIds.Add(cand.IntentId))
                {
                    candidates.Add(cand);
                }
                if (candidates.Count >= topK)
                {
                    break;
                }
            }
        }

        return candidates.Take(topK).ToList();
    }

    private List<Candidate> MatchExact(string query)
    {
        var matches = new List<Candidate>();

        // Exact alias lookup
        var aliasIntents = _store.GetByAlias(query);
        if (aliasIntents.Count > 0)
        {
            float score = aliasIntents.Count == 1 ? 1.0f : 0.98f;
            foreach (var it in aliasIntents)
            {
                matches.Add(ToCandidate(it, score, MatchSource.RuleExact));
            }
            return matches;
        }

        // Exact match against canonical command verb / executable
        foreach (var intent in _store.AllIntents)
        {
            string cmdNorm = intent.Command.Trim().ToLowerInvariant();
            string cmdVerb = cmdNorm.Split(' ')[0];
            if (query == cmdVerb || query == cmdNorm)
            {
                matches.Add(ToCandidate(intent, 1.0f, MatchSource.RuleExact));
            }
        }

        return matches;
    }

    private List<Candidate> MatchCliInvocation(string[] words, HashSet<string> seenIds)
    {
        string firstWord = words[0];
        string[] argTokens = words.Skip(1).ToArray();

        // Disqualify if query contains natural language marker words
        if (argTokens.Any(w => NaturalLanguageMarkers.Contains(w)))
        {
            return new List<Candidate>();
        }

        bool isCliArg = argTokens.Any(w =>
            w.StartsWith("-") || w.StartsWith("/") || w.StartsWith("--") ||
            w.StartsWith("$") || w.StartsWith(".") || w.StartsWith("~") ||
            int.TryParse(w, out _) ||
            w.StartsWith("http://", StringComparison.OrdinalIgnoreCase) ||
            w.StartsWith("https://", StringComparison.OrdinalIgnoreCase) ||
            w.Contains('\\') || w.Contains('/')
        ) || words.Length == 2;

        if (!isCliArg)
        {
            return new List<Candidate>();
        }

        var candidateIntents = _store.GetByAlias(firstWord).ToList();
        if (candidateIntents.Count == 0)
        {
            // Try matching first token against command primary verbs
            foreach (var it in _store.AllIntents)
            {
                if (it.Command.StartsWith("git ", StringComparison.OrdinalIgnoreCase)) continue;
                string cmdVerb = it.Command.Trim().ToLowerInvariant().Split(' ')[0];
                if (cmdVerb.Equals(firstWord, StringComparison.OrdinalIgnoreCase))
                {
                    candidateIntents.Add(it);
                }
            }
        }

        if (candidateIntents.Count == 0)
        {
            return new List<Candidate>();
        }

        var matches = new List<Candidate>();
        bool hasNumericArg = argTokens.Any(w => int.TryParse(w, out _));
        bool hasRecursiveFlag = argTokens.Any(w => w is "-recurse" or "-r" or "-rf" or "/s");

        foreach (var intent in candidateIntents)
        {
            if (seenIds.Contains(intent.Id)) continue;

            float score = 0.95f;

            // PID vs process name disambiguation
            if (intent.Id.Contains("proc_kill"))
            {
                if (hasNumericArg && intent.Id == "proc_kill_id") score = 0.99f;
                else if (!hasNumericArg && intent.Id == "proc_kill_name") score = 0.99f;
                else score = 0.85f;
            }

            // Single file vs recursive directory delete disambiguation
            if (intent.Id.Contains("file_delete"))
            {
                if (hasRecursiveFlag && intent.Id == "file_delete_recursive") score = 0.99f;
                else if (!hasRecursiveFlag && intent.Id == "file_delete_single") score = 0.95f;
                else score = 0.85f;
            }

            matches.Add(ToCandidate(intent, score, MatchSource.RuleExact));
        }

        matches.Sort((a, b) => b.Score.CompareTo(a.Score));
        return matches;
    }

    private List<Candidate> MatchPrefix(string query, HashSet<string> excludeIds)
    {
        var matches = new List<Candidate>();

        foreach (var intent in _store.AllIntents)
        {
            if (excludeIds.Contains(intent.Id)) continue;

            string cmdVerb = intent.Command.Trim().ToLowerInvariant().Split(' ')[0];
            if (cmdVerb.StartsWith(query, StringComparison.OrdinalIgnoreCase))
            {
                float score = Math.Min(0.92f, 0.78f + 0.14f * ((float)query.Length / Math.Max(cmdVerb.Length, 1)));
                matches.Add(ToCandidate(intent, score, MatchSource.RulePrefix));
                continue;
            }

            foreach (var alias in intent.Aliases)
            {
                string aliasClean = alias.Trim().ToLowerInvariant();
                if (aliasClean.StartsWith(query, StringComparison.OrdinalIgnoreCase))
                {
                    float score = Math.Min(0.90f, 0.75f + 0.15f * ((float)query.Length / Math.Max(aliasClean.Length, 1)));
                    matches.Add(ToCandidate(intent, score, MatchSource.RulePrefix));
                    break;
                }
            }
        }

        matches.Sort((a, b) => b.Score.CompareTo(a.Score));
        return matches;
    }

    private static Candidate ToCandidate(CommandIntent intent, float score, string source)
    {
        return new Candidate(
            command: intent.Command,
            intentId: intent.Id,
            description: intent.Description,
            score: (float)Math.Round(score, 4),
            source: source,
            riskLevel: intent.RiskLevel.ToSerializedString(),
            category: intent.Category,
            riskReason: intent.RiskReason,
            commandTemplate: intent.Command,
            isComplete: intent.ParameterSlots.Count == 0
        );
    }
}
