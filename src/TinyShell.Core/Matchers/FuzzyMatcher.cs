using System;
using System.Collections.Generic;
using System.Linq;
using TinyShell.Core.Models;
using TinyShell.Core.Storage;

namespace TinyShell.Core.Matchers;

/// <summary>
/// Lightweight string similarity algorithms matching RapidFuzz behavior.
/// </summary>
public static class FuzzyUtils
{
    /// <summary>
    /// Computes Longest Common Subsequence length between two strings.
    /// </summary>
    public static int LongestCommonSubsequence(string s1, string s2)
    {
        if (string.IsNullOrEmpty(s1) || string.IsNullOrEmpty(s2))
            return 0;

        int m = s1.Length;
        int n = s2.Length;

        // Use single row DP for O(N) memory
        int[] dp = new int[n + 1];

        for (int i = 0; i < m; i++)
        {
            int prev = 0;
            char c1 = s1[i];
            for (int j = 0; j < n; j++)
            {
                int temp = dp[j + 1];
                if (c1 == s2[j])
                {
                    dp[j + 1] = prev + 1;
                }
                else
                {
                    dp[j + 1] = Math.Max(dp[j + 1], dp[j]);
                }
                prev = temp;
            }
        }

        return dp[n];
    }

    /// <summary>
    /// Computes standard Indel / Sequence similarity ratio in [0.0, 1.0].
    /// Ratio = 2 * LCS / (len1 + len2).
    /// </summary>
    public static double Ratio(string s1, string s2)
    {
        if (string.IsNullOrEmpty(s1) && string.IsNullOrEmpty(s2))
            return 1.0;
        if (string.IsNullOrEmpty(s1) || string.IsNullOrEmpty(s2))
            return 0.0;

        int lcs = LongestCommonSubsequence(s1, s2);
        return (2.0 * lcs) / (s1.Length + s2.Length);
    }

    /// <summary>
    /// Computes token sort ratio: splits tokens, sorts alphabetically, and computes ratio.
    /// </summary>
    public static double TokenSortRatio(string s1, string s2)
    {
        if (string.IsNullOrEmpty(s1) && string.IsNullOrEmpty(s2))
            return 1.0;
        if (string.IsNullOrEmpty(s1) || string.IsNullOrEmpty(s2))
            return 0.0;

        string[] tokens1 = s1.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries);
        string[] tokens2 = s2.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries);

        Array.Sort(tokens1, StringComparer.OrdinalIgnoreCase);
        Array.Sort(tokens2, StringComparer.OrdinalIgnoreCase);

        string sorted1 = string.Join(" ", tokens1);
        string sorted2 = string.Join(" ", tokens2);

        return Ratio(sorted1, sorted2);
    }

    /// <summary>
    /// Computes partial ratio by sliding the shorter string across the longer string.
    /// </summary>
    public static double PartialRatio(string s1, string s2)
    {
        if (string.IsNullOrEmpty(s1) && string.IsNullOrEmpty(s2))
            return 1.0;
        if (string.IsNullOrEmpty(s1) || string.IsNullOrEmpty(s2))
            return 0.0;

        string shorter = s1.Length <= s2.Length ? s1 : s2;
        string longer = s1.Length <= s2.Length ? s2 : s1;

        int n = shorter.Length;
        int m = longer.Length;

        if (n == m)
            return Ratio(shorter, longer);

        double best = 0.0;
        for (int i = 0; i <= m - n; i++)
        {
            string sub = longer.Substring(i, n);
            double r = Ratio(shorter, sub);
            if (r > best)
            {
                best = r;
                if (best >= 1.0)
                    break;
            }
        }

        return best;
    }

    /// <summary>
    /// Computes WRatio matching RapidFuzz logic for command abbreviations and short inputs.
    /// </summary>
    public static double WRatio(string s1, string s2)
    {
        if (string.IsNullOrEmpty(s1) && string.IsNullOrEmpty(s2))
            return 1.0;
        if (string.IsNullOrEmpty(s1) || string.IsNullOrEmpty(s2))
            return 0.0;

        double baseRatio = Ratio(s1, s2);
        if (s1.Length == s2.Length)
            return baseRatio;

        int minLen = Math.Min(s1.Length, s2.Length);
        int maxLen = Math.Max(s1.Length, s2.Length);
        double lenRatio = (double)maxLen / minLen;

        double partialScale = lenRatio > 8.0 ? 0.60 : 0.90;
        double pr = PartialRatio(s1, s2) * partialScale;
        double tsr = TokenSortRatio(s1, s2) * 0.95 * (lenRatio > 1.5 ? 0.95 : 1.0);

        return Math.Max(baseRatio, Math.Max(pr, tsr));
    }
}

/// <summary>
/// Fuzzy string matcher using string metrics across aliases, commands, keywords and phrases.
/// Matches Python rapidfuzz FuzzyMatcher behavior.
/// </summary>
public class FuzzyMatcher : IMatcher
{
    private readonly KnowledgeBaseStore _store;

    public FuzzyMatcher(KnowledgeBaseStore store)
    {
        _store = store ?? throw new ArgumentNullException(nameof(store));
    }

    public List<Candidate> Match(string query, int topK = 3)
    {
        if (string.IsNullOrWhiteSpace(query))
            return new List<Candidate>();

        string cleanQ = query.Trim().ToLowerInvariant();
        var scoredCandidates = new List<(double Score, CommandIntent Intent)>();

        foreach (var intent in _store.AllIntents)
        {
            double score = ComputeIntentFuzzyScore(cleanQ, intent);
            if (score > 0.20) // Noise threshold
            {
                scoredCandidates.Add((score, intent));
            }
        }

        scoredCandidates.Sort((a, b) => b.Score.CompareTo(a.Score));

        var candidates = new List<Candidate>();
        foreach (var (score, intent) in scoredCandidates.Take(topK))
        {
            candidates.Add(ToCandidate(intent, score));
        }

        return candidates;
    }

    public double ComputeIntentFuzzyScore(string query, CommandIntent intent)
    {
        double bestScore = 0.0;
        string[] words = query.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries);
        string firstWord = words.Length > 0 ? words[0] : query;
        var queryWordSet = new HashSet<string>(words, StringComparer.OrdinalIgnoreCase);

        // 1. Check aliases & command verb
        string[] cmdParts = intent.Command.Trim().ToLowerInvariant().Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries);
        string cmdVerb = cmdParts.Length > 0 ? cmdParts[0] : "";

        var targetsExact = new List<string> { cmdVerb };
        foreach (var a in intent.Aliases)
        {
            targetsExact.Add(a.Trim().ToLowerInvariant());
        }

        foreach (var target in targetsExact)
        {
            if (string.IsNullOrEmpty(target)) continue;

            double r = FuzzyUtils.Ratio(query, target);
            bestScore = Math.Max(bestScore, r);

            // If query is a short command or abbreviation, allow WRatio
            if (words.Length <= 2)
            {
                double wr = FuzzyUtils.WRatio(query, target);
                bestScore = Math.Max(bestScore, wr);
            }

            // Check typo on first command word if multi-word query (e.g. "stopp-procss chrome")
            if (words.Length > 1)
            {
                double pr = FuzzyUtils.Ratio(firstWord, target);
                if (pr > 0.75)
                {
                    bestScore = Math.Max(bestScore, pr * 0.90);
                }
            }
        }

        // 2. Check intent phrases using token_sort_ratio (penalizes length mismatch)
        foreach (var phrase in intent.IntentPhrases)
        {
            string phraseClean = phrase.Trim().ToLowerInvariant();
            if (string.IsNullOrEmpty(phraseClean)) continue;

            double tsr = FuzzyUtils.TokenSortRatio(query, phraseClean);
            double r = FuzzyUtils.Ratio(query, phraseClean);
            bestScore = Math.Max(bestScore, Math.Max(tsr * 0.95, r * 0.95));
        }

        // 3. Check keywords with word coverage
        if (words.Length == 1)
        {
            foreach (var kw in intent.Keywords)
            {
                double r = FuzzyUtils.Ratio(query, kw.Trim().ToLowerInvariant());
                bestScore = Math.Max(bestScore, r * 0.85);
            }
        }
        else
        {
            var kwSet = new HashSet<string>(intent.Keywords.Select(k => k.Trim().ToLowerInvariant()), StringComparer.OrdinalIgnoreCase);
            int commonCount = 0;
            foreach (var w in queryWordSet)
            {
                if (kwSet.Contains(w)) commonCount++;
            }

            if (commonCount > 0 && words.Length > 0)
            {
                double coverage = (double)commonCount / words.Length;
                bestScore = Math.Max(bestScore, coverage * 0.70);
            }
        }

        // 4. Check description with token_sort_ratio
        double descScore = FuzzyUtils.TokenSortRatio(query, intent.Description.ToLowerInvariant());
        bestScore = Math.Max(bestScore, descScore * 0.70);

        return Math.Min(1.0, Math.Max(0.0, bestScore));
    }

    private static Candidate ToCandidate(CommandIntent intent, double score)
    {
        return new Candidate
        {
            Command = intent.Command,
            IntentId = intent.Id,
            Description = intent.Description,
            Score = (float)Math.Round(score, 4),
            Source = MatchSource.Fuzzy,
            RiskLevel = intent.RiskLevel.ToSerializedString(),
            Category = intent.Category,
            RiskReason = intent.RiskReason,
            CommandTemplate = intent.Command,
            IsComplete = intent.ParameterSlots.Count == 0,
        };
    }
}
