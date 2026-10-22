using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using TinyShell.Core.Matchers;
using TinyShell.Core.Models;
using TinyShell.Core.Parameters;
using TinyShell.Core.Risk;
using TinyShell.Core.Storage;

namespace TinyShell.Core;

/// <summary>
/// Unified semantic intent recognition engine for Windows PowerShell 7.
/// </summary>
public class IntentEngine
{
    private static readonly HashSet<string> StopActions = new(StringComparer.OrdinalIgnoreCase)
    {
        "stop", "kill", "terminate", "halt", "end", "abort", "quit", "pkill"
    };

    private static readonly HashSet<string> StartActions = new(StringComparer.OrdinalIgnoreCase)
    {
        "start", "launch", "run", "begin", "open", "exec"
    };

    private static readonly HashSet<string> DeleteActions = new(StringComparer.OrdinalIgnoreCase)
    {
        "delete", "remove", "erase", "wipe", "destroy", "purge", "trash", "rm", "del", "clean up"
    };

    private static readonly HashSet<string> CopyActions = new(StringComparer.OrdinalIgnoreCase)
    {
        "copy", "clone", "duplicate", "backup", "cp"
    };

    private static readonly string[] UptimeQueryActions = new[]
    {
        "how long", "how many", "uptime", "turned on", "running time", "boot time", "since reboot"
    };

    private static readonly HashSet<string> ExternalCliTools = new(StringComparer.OrdinalIgnoreCase)
    {
        "git", "docker", "kubectl", "npm", "yarn", "pnpm", "cargo", "pip", "python",
        "node", "mvn", "gradle", "terraform", "aws", "az", "gcloud", "apt", "apt-get",
        "chmod", "chown", "brew", "choco", "winget"
    };

    private static readonly Regex[] NonShellPatterns = new[]
    {
        new Regex(@"^\s*(def|class|import|from|function|const|let|var|package|public|private)\b", RegexOptions.Compiled | RegexOptions.IgnoreCase),
        new Regex(@"\b(console\.log|printf|cout|system\.out\.println)\b", RegexOptions.Compiled | RegexOptions.IgnoreCase),
        new Regex(@"^\s*(apt-get|apt|yum|pacman|dnf|brew|chmod|chown)\b", RegexOptions.Compiled | RegexOptions.IgnoreCase),
        new Regex(@"\b(linked\s+list|binary\s+tree|quicksort|mergesort|reverse\s+a\s+string)\b", RegexOptions.Compiled | RegexOptions.IgnoreCase),
    };

    private readonly string _kbPath;
    private readonly string _modelPath;
    private readonly bool _offlineMode;
    private readonly int _maxCacheSize;

    public KnowledgeBaseStore Store { get; }
    public RuleMatcher RuleMatcher { get; }
    public FuzzyMatcher FuzzyMatcher { get; }

    private ModelMatcher? _modelMatcher;
    private readonly object _modelLock = new();
    private readonly Dictionary<string, QueryResult> _cache = new(StringComparer.Ordinal);
    private readonly LinkedList<string> _cacheOrder = new();
    private readonly object _cacheLock = new();

    public IntentEngine(
        string kbPath = "data/knowledge_base.json",
        string modelPath = "models/potion-base-2M",
        bool offlineMode = true,
        int maxCacheSize = 128)
    {
        _kbPath = kbPath;
        _modelPath = modelPath;
        _offlineMode = offlineMode;
        _maxCacheSize = maxCacheSize;

        Store = new KnowledgeBaseStore(kbPath);
        RuleMatcher = new RuleMatcher(Store);
        FuzzyMatcher = new FuzzyMatcher(Store);
    }

    /// <summary>
    /// Check whether the neural ModelMatcher has been loaded into memory.
    /// </summary>
    public bool IsModelLoaded => _modelMatcher != null;

    /// <summary>
    /// On-demand initialization of the Model2Vec semantic matcher.
    /// </summary>
    public ModelMatcher GetModelMatcher()
    {
        if (_modelMatcher == null)
        {
            lock (_modelLock)
            {
                _modelMatcher ??= new ModelMatcher(Store, _modelPath, _offlineMode);
            }
        }
        return _modelMatcher;
    }

    public QueryResult Search(
        string query,
        int topK = 3,
        string mode = "hybrid",
        double oodThreshold = 0.42)
    {
        var sw = Stopwatch.StartNew();
        string cleanQuery = query?.Trim() ?? "";
        string cacheKey = $"{mode}:{cleanQuery}:{topK}:{oodThreshold}";

        lock (_cacheLock)
        {
            if (_cache.TryGetValue(cacheKey, out var cached))
            {
                return cached;
            }
        }

        // Input normalization and validation
        if (string.IsNullOrWhiteSpace(cleanQuery))
        {
            sw.Stop();
            var res = new QueryResult
            {
                Query = query ?? "",
                Candidates = new List<Candidate>(),
                DebugCandidates = new List<Candidate>(),
                ConfidenceLevel = ConfidenceLevel.Rejected,
                IsAccepted = false,
                IsRejected = true,
                RejectionReason = "empty_query",
                LatencyMs = sw.Elapsed.TotalMilliseconds,
                Mode = mode,
                IsEmpty = true,
                IsOutOfDomain = true,
            };
            SaveToCache(cacheKey, res);
            return res;
        }

        bool hasLettersOrDigits = cleanQuery.Any(char.IsLetterOrDigit);
        if (!hasLettersOrDigits)
        {
            sw.Stop();
            var res = new QueryResult
            {
                Query = query ?? "",
                Candidates = new List<Candidate>(),
                DebugCandidates = new List<Candidate>(),
                ConfidenceLevel = ConfidenceLevel.Rejected,
                IsAccepted = false,
                IsRejected = true,
                RejectionReason = "non_alphanumeric_or_symbolic_query",
                LatencyMs = sw.Elapsed.TotalMilliseconds,
                Mode = mode,
                IsEmpty = false,
                IsOutOfDomain = true,
            };
            SaveToCache(cacheKey, res);
            return res;
        }

        bool hasCjk = cleanQuery.Any(c => c >= '\u4e00' && c <= '\u9fff');

        // External CLI tools check
        string[] tokens = cleanQuery.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries);
        string firstToken = tokens.Length > 0 ? tokens[0].ToLowerInvariant() : "";
        if (ExternalCliTools.Contains(firstToken))
        {
            var ruleCheck = RuleMatcher.Match(cleanQuery, topK: 1);
            if (ruleCheck.Count == 0 || ruleCheck[0].Score < 0.95f)
            {
                sw.Stop();
                var res = new QueryResult
                {
                    Query = query ?? "",
                    Candidates = new List<Candidate>(),
                    DebugCandidates = new List<Candidate>(),
                    ConfidenceLevel = ConfidenceLevel.Rejected,
                    IsAccepted = false,
                    IsRejected = true,
                    RejectionReason = "unsupported_external_tool",
                    LatencyMs = sw.Elapsed.TotalMilliseconds,
                    Mode = mode,
                    IsOutOfDomain = true,
                };
                SaveToCache(cacheKey, res);
                return res;
            }
        }

        // Non-shell patterns check
        if (NonShellPatterns.Any(p => p.IsMatch(cleanQuery)))
        {
            sw.Stop();
            var res = new QueryResult
            {
                Query = query ?? "",
                Candidates = new List<Candidate>(),
                DebugCandidates = new List<Candidate>(),
                ConfidenceLevel = ConfidenceLevel.Rejected,
                IsAccepted = false,
                IsRejected = true,
                RejectionReason = "near_domain_code_or_unsupported_system",
                LatencyMs = sw.Elapsed.TotalMilliseconds,
                Mode = mode,
                IsOutOfDomain = true,
            };
            SaveToCache(cacheKey, res);
            return res;
        }

        // Unambiguous exact match short-circuit
        if (mode == "hybrid" || mode == "rule")
        {
            var ruleCandidates = RuleMatcher.Match(cleanQuery, topK: topK);
            if (ruleCandidates.Count == 1 &&
                Math.Abs(ruleCandidates[0].Score - 1.0f) < 1e-4f &&
                ruleCandidates[0].Source == MatchSource.RuleExact)
            {
                var exactCand = ruleCandidates[0];
                var intent = Store.GetById(exactCand.IntentId);
                if (intent != null)
                {
                    var (paramsDict, isComplete) = ParameterExtractor.ExtractParametersFromQuery(intent, cleanQuery);
                    string? rendered = ParameterExtractor.RenderCommandSafely(intent.Command, intent, paramsDict);
                    exactCand.Parameters = paramsDict;
                    if (!string.IsNullOrEmpty(rendered))
                    {
                        exactCand.RenderedCommand = rendered;
                        exactCand.Command = rendered;
                    }
                    exactCand.IsComplete = isComplete && !Regex.IsMatch(exactCand.Command, @"<[^>]+>");
                    var (effRisk, effReason) = RiskEvaluator.EvaluateCommandRisk(intent, exactCand.Command);
                    exactCand.RiskLevel = effRisk.ToSerializedString();
                    if (!string.IsNullOrEmpty(effReason))
                    {
                        exactCand.RiskReason = effReason;
                    }
                }

                sw.Stop();
                var res = new QueryResult
                {
                    Query = query ?? "",
                    Candidates = new List<Candidate> { exactCand },
                    DebugCandidates = new List<Candidate>(),
                    ConfidenceLevel = ConfidenceLevel.High,
                    IsAccepted = true,
                    IsRejected = false,
                    LatencyMs = sw.Elapsed.TotalMilliseconds,
                    Mode = mode,
                };
                SaveToCache(cacheKey, res);
                return res;
            }
        }

        // Single-mode dispatch
        if (mode == "rule")
        {
            var cands = RuleMatcher.Match(cleanQuery, topK: topK);
            EnrichCandidates(cands, cleanQuery);
            sw.Stop();
            var res = new QueryResult
            {
                Query = query ?? "",
                Candidates = cands,
                LatencyMs = sw.Elapsed.TotalMilliseconds,
                Mode = mode,
                ConfidenceLevel = cands.Count > 0 ? ConfidenceLevel.High : ConfidenceLevel.Rejected,
                IsAccepted = cands.Count > 0,
                IsRejected = cands.Count == 0,
                RejectionReason = cands.Count == 0 ? "no_rule_match" : null,
            };
            SaveToCache(cacheKey, res);
            return res;
        }

        if (mode == "fuzzy")
        {
            var cands = FuzzyMatcher.Match(cleanQuery, topK: topK);
            EnrichCandidates(cands, cleanQuery);
            sw.Stop();
            bool isGood = cands.Count > 0 && cands[0].Score >= 0.40f;
            var res = new QueryResult
            {
                Query = query ?? "",
                Candidates = isGood ? cands : new List<Candidate>(),
                DebugCandidates = isGood ? new List<Candidate>() : cands,
                LatencyMs = sw.Elapsed.TotalMilliseconds,
                Mode = mode,
                ConfidenceLevel = isGood ? ConfidenceLevel.Medium : ConfidenceLevel.Rejected,
                IsAccepted = isGood,
                IsRejected = !isGood,
                RejectionReason = !isGood ? "low_fuzzy_similarity" : null,
            };
            SaveToCache(cacheKey, res);
            return res;
        }

        if (mode == "model")
        {
            var cands = GetModelMatcher().Match(cleanQuery, topK: topK);
            EnrichCandidates(cands, cleanQuery);
            sw.Stop();
            bool isGood = cands.Count > 0 && cands[0].Score >= (float)oodThreshold;
            var res = new QueryResult
            {
                Query = query ?? "",
                Candidates = isGood ? cands : new List<Candidate>(),
                DebugCandidates = isGood ? new List<Candidate>() : cands,
                LatencyMs = sw.Elapsed.TotalMilliseconds,
                Mode = mode,
                ConfidenceLevel = isGood ? ConfidenceLevel.Medium : ConfidenceLevel.Rejected,
                IsAccepted = isGood,
                IsRejected = !isGood,
                RejectionReason = !isGood ? "low_semantic_similarity" : null,
                IsOutOfDomain = !isGood,
            };
            SaveToCache(cacheKey, res);
            return res;
        }

        // Hybrid fusion
        var (acceptedCands, debugCands, confLevel, isOod, rejectReason) =
            HybridFusion(cleanQuery, topK, oodThreshold, hasCjk);
        sw.Stop();

        var hybridRes = new QueryResult
        {
            Query = query ?? "",
            Candidates = acceptedCands,
            DebugCandidates = debugCands,
            ConfidenceLevel = confLevel,
            IsAccepted = acceptedCands.Count > 0,
            IsRejected = acceptedCands.Count == 0,
            RejectionReason = rejectReason,
            LatencyMs = sw.Elapsed.TotalMilliseconds,
            Mode = "hybrid",
            IsOutOfDomain = isOod,
        };
        SaveToCache(cacheKey, hybridRes);
        return hybridRes;
    }

    private (List<Candidate> Accepted, List<Candidate> Debug, ConfidenceLevel Conf, bool IsOod, string? RejectionReason)
        HybridFusion(string query, int topK, double oodThreshold, bool hasCjk)
    {
        var ruleCandidates = RuleMatcher.Match(query, topK: 10);
        var fuzzyCandidates = FuzzyMatcher.Match(query, topK: 10);
        var modelCandidates = GetModelMatcher().Match(query, topK: 10);

        var modelMap = modelCandidates.ToDictionary(c => c.IntentId, c => (double)c.Score);
        var fuzzyMap = fuzzyCandidates.ToDictionary(c => c.IntentId, c => (double)c.Score);
        var ruleMap = ruleCandidates.ToDictionary(c => c.IntentId, c => c);

        var allIntentIds = new HashSet<string>(modelMap.Keys);
        allIntentIds.UnionWith(fuzzyMap.Keys);
        allIntentIds.UnionWith(ruleMap.Keys);
        var sortedIntentIds = allIntentIds.OrderBy(x => x, StringComparer.Ordinal).ToList();

        string lowerQ = query.ToLowerInvariant();
        string[] words = lowerQ.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries);
        var qTokens = new HashSet<string>(words, StringComparer.OrdinalIgnoreCase);

        bool hasStop = words.Any(w => StopActions.Contains(w));
        bool hasStart = words.Any(w => StartActions.Contains(w));
        bool hasDelete = words.Any(w => DeleteActions.Contains(w)) || lowerQ.Contains("delete") || lowerQ.Contains("trash");
        bool hasCopy = words.Any(w => CopyActions.Contains(w)) || lowerQ.Contains("clone");
        bool hasUptime = UptimeQueryActions.Any(k => lowerQ.Contains(k));
        bool hasNumericPid = Regex.IsMatch(lowerQ, @"\b(?:pid\s*)?(\d{2,7})\b") &&
                             (lowerQ.Contains("kill") || lowerQ.Contains("process"));

        bool hasFileTarget =
            Regex.IsMatch(lowerQ, @"\b[\w-]+\.(?:tmp|txt|log|json|csv|py|md|ps1|bak|xml|yml|yaml|ini|cfg)\b") ||
            words.Any(w => w is "file" or "temporary" or "temp" or "notes" or "single");

        bool hasDirTarget = words.Any(w => w is "folder" or "directory" or "dir" or "tree" or "subfolder" or "subdirectories");
        bool hasRecycleBin = lowerQ.Contains("recycle") || (lowerQ.Contains("trash") && !hasFileTarget);
        bool hasIcmpOrPing = lowerQ.Contains("icmp") || lowerQ.Contains("ping") || lowerQ.Contains("reachability") ||
                             lowerQ.Contains("packet") || lowerQ.Contains("answers icmp");

        bool hasStatusQuery =
            words.Any(w => w is "is" or "check" or "whether" or "status") &&
            words.Any(w => w is "running" or "open" or "active" or "alive");

        bool hasEnv = lowerQ.Contains("env") || lowerQ.Contains("userprofile") || lowerQ.Contains("variable");

        bool hasRecurseSearch =
            (lowerQ.Contains("everywhere") || lowerQ.Contains("subdirectories") || lowerQ.Contains("recursively")) &&
            (lowerQ.Contains("search") || lowerQ.Contains("find") || lowerQ.Contains("locate"));

        var scoredPool = new List<(double FusedScore, string IntentId, string Source)>();

        foreach (var intentId in sortedIntentIds)
        {
            double sModel = modelMap.TryGetValue(intentId, out double sm) ? sm : 0.0;
            double sFuzzy = fuzzyMap.TryGetValue(intentId, out double sf) ? sf : 0.0;
            double sRule = 0.0;

            if (ruleMap.TryGetValue(intentId, out var rc))
            {
                if (rc.Source == MatchSource.RuleExact)
                    sRule = rc.Score;
                else if (rc.Source == MatchSource.RulePrefix)
                    sRule = rc.Score * 0.90;
            }

            bool isShortCommand = words.Length == 1 || query.Length <= 6;
            double fused;
            string src;

            if (isShortCommand)
            {
                if (sFuzzy >= 0.80)
                {
                    fused = 0.70 * sFuzzy + 0.20 * sModel + 0.10 * sRule;
                    src = MatchSource.Fuzzy;
                }
                else
                {
                    fused = 0.35 * sModel + 0.35 * sFuzzy + 0.30 * sRule;
                    if (sRule >= 0.95)
                        src = MatchSource.RuleExact;
                    else if (sFuzzy >= sModel)
                        src = MatchSource.Fuzzy;
                    else
                        src = MatchSource.Model;
                }
            }
            else
            {
                if (sFuzzy >= 0.85)
                {
                    fused = 0.60 * sFuzzy + 0.30 * sModel + 0.10 * sRule;
                    src = MatchSource.Fuzzy;
                }
                else
                {
                    fused = 0.60 * sModel + 0.30 * sFuzzy + 0.10 * sRule;
                    if (sRule >= 0.98)
                        src = MatchSource.RuleExact;
                    else if (sModel >= sFuzzy)
                        src = MatchSource.Model;
                    else
                        src = MatchSource.Fuzzy;
                }
            }

            // Constraint 1: STOP vs START polarity
            if (hasStop && !hasStart && !hasStatusQuery)
            {
                if (intentId.Contains("sys_service_start") || intentId.Contains("proc_start"))
                    fused *= 0.20;
                else if (intentId.Contains("sys_service_stop") || intentId.Contains("proc_kill"))
                    fused += 0.15;
            }

            if (hasStart && !hasStop && !hasStatusQuery)
            {
                if (intentId.Contains("sys_service_stop") || intentId.Contains("proc_kill"))
                    fused *= 0.20;
                else if (intentId.Contains("sys_service_start") || intentId.Contains("proc_start"))
                    fused += 0.15;
            }

            // Constraint 2: COPY / CLONE vs DELETE
            if (hasCopy && !hasDelete)
            {
                if (intentId.Contains("file_delete") || intentId.Contains("sys_clear_recycle_bin"))
                    fused *= 0.10;
                else if (intentId.Contains("file_copy"))
                    fused += 0.20;
            }

            // Constraint 3: Uptime query vs Reboot / Shutdown
            if (hasUptime)
            {
                if (intentId.Contains("sys_reboot") || intentId.Contains("sys_shutdown"))
                    fused *= 0.10;
                else if (intentId.Contains("sys_uptime"))
                    fused += 0.25;
            }

            // Constraint 4: Numeric PID targeting
            if (hasNumericPid)
            {
                if (intentId == "proc_kill_id")
                    fused += 0.25;
                else if (intentId == "proc_kill_name")
                    fused *= 0.70;
            }

            // Constraint 5: Operation Scope
            if (hasDelete)
            {
                if (hasFileTarget && !hasRecycleBin)
                {
                    if (intentId == "sys_clear_recycle_bin")
                        fused *= 0.05;
                    else if (intentId == "file_delete_single")
                        fused += 0.35;
                    else if (intentId == "file_delete_recursive" && !hasDirTarget)
                        fused *= 0.40;
                }
                else if (hasRecycleBin)
                {
                    if (intentId == "sys_clear_recycle_bin")
                        fused += 0.30;
                }
                else if (hasDirTarget)
                {
                    if (intentId == "file_delete_recursive")
                        fused += 0.30;
                    else if (intentId == "file_delete_single")
                        fused *= 0.50;
                }
            }

            // Constraint 6: Ping / ICMP Reachability
            if (hasIcmpOrPing)
            {
                if (intentId == "net_ping_host")
                    fused += 0.35;
                else if (intentId is "net_test_port" or "net_ip_config")
                    fused *= 0.50;
            }

            // Constraint 7: Status Query vs Mutation
            if (hasStatusQuery && !hasStart && !hasStop)
            {
                if (intentId == "proc_find")
                    fused += 0.30;
                else if (intentId is "sys_service_start" or "sys_service_restart")
                    fused *= 0.30;
            }

            // Constraint 8: Environment Variables
            if (hasEnv)
            {
                if (words.Any(w => w is "set" or "export" or "assign" or "production" or "development"))
                {
                    if (intentId == "env_set_temp")
                        fused += 0.35;
                }
                else if (words.Any(w => w is "what" or "check" or "read" or "value" or "set") || lowerQ.Contains("is set to"))
                {
                    if (intentId == "env_get_value")
                        fused += 0.35;
                }
            }

            // Constraint 9: Recursive Search Everywhere
            if (hasRecurseSearch)
            {
                if (intentId == "file_find_recurse")
                    fused += 0.35;
                else if (intentId == "sys_system_info")
                    fused *= 0.20;
            }

            scoredPool.Add((fused, intentId, src));
        }

        // Sort deterministically by descending score, tie-breaking on intentId
        scoredPool.Sort((a, b) =>
        {
            double rA = Math.Round(a.FusedScore, 4);
            double rB = Math.Round(b.FusedScore, 4);
            int cmp = rB.CompareTo(rA);
            if (cmp != 0) return cmp;
            return string.Compare(a.IntentId, b.IntentId, StringComparison.Ordinal);
        });

        double topScore = scoredPool.Count > 0 ? scoredPool[0].FusedScore : 0.0;
        bool hasExactRule = false;
        if (scoredPool.Count > 0)
        {
            string topIid = scoredPool[0].IntentId;
            if (ruleMap.TryGetValue(topIid, out var topRc) &&
                topRc.Source == MatchSource.RuleExact &&
                topRc.Score >= 0.95f)
            {
                hasExactRule = true;
            }
        }

        bool isOod = false;
        string? rejectionReason = null;

        if (hasCjk && !hasExactRule)
        {
            isOod = true;
            rejectionReason = "unsupported_non_latin_language";
        }
        else if (!hasExactRule && topScore < oodThreshold)
        {
            isOod = true;
            rejectionReason = "low_semantic_confidence_out_of_domain";
        }

        var rawCandidates = new List<Candidate>();
        foreach (var (score, intentId, source) in scoredPool.Take(topK))
        {
            var intent = Store.GetById(intentId);
            if (intent == null) continue;

            bool hasPlaceholders = Regex.IsMatch(intent.Command, @"<[^>]+>");
            bool initComplete = !hasPlaceholders && intent.ParameterSlots.Count == 0;

            rawCandidates.Add(new Candidate
            {
                Command = intent.Command,
                IntentId = intent.Id,
                Description = intent.Description,
                Score = (float)Math.Round(score, 4),
                Source = source,
                RiskLevel = intent.RiskLevel.ToSerializedString(),
                Category = intent.Category,
                RiskReason = intent.RiskReason,
                CommandTemplate = intent.Command,
                IsComplete = initComplete,
            });
        }

        EnrichCandidates(rawCandidates, query);

        List<Candidate> acceptedCandidates;
        List<Candidate> debugCandidates;
        ConfidenceLevel confLevel;

        if (isOod)
        {
            acceptedCandidates = new List<Candidate>();
            debugCandidates = rawCandidates;
            confLevel = ConfidenceLevel.Rejected;
        }
        else
        {
            acceptedCandidates = rawCandidates;
            debugCandidates = new List<Candidate>();
            confLevel = topScore >= 0.70 ? ConfidenceLevel.High : ConfidenceLevel.Medium;
        }

        return (acceptedCandidates, debugCandidates, confLevel, isOod, rejectionReason);
    }

    private void EnrichCandidates(List<Candidate> candidates, string query)
    {
        foreach (var cand in candidates)
        {
            var intent = Store.GetById(cand.IntentId);
            if (intent == null) continue;

            var (paramsDict, isComplete) = ParameterExtractor.ExtractParametersFromQuery(intent, query);
            cand.Parameters = paramsDict;

            string? rendered = ParameterExtractor.RenderCommandSafely(intent.Command, intent, paramsDict);
            if (!string.IsNullOrEmpty(rendered))
            {
                cand.RenderedCommand = rendered;
                cand.Command = rendered;
            }

            cand.IsComplete = isComplete && !Regex.IsMatch(cand.Command, @"<[^>]+>");

            var (effRisk, effReason) = RiskEvaluator.EvaluateCommandRisk(intent, cand.Command);
            cand.RiskLevel = effRisk.ToSerializedString();
            if (!string.IsNullOrEmpty(effReason))
            {
                cand.RiskReason = effReason;
            }
        }
    }

    private void SaveToCache(string key, QueryResult res)
    {
        lock (_cacheLock)
        {
            if (_cache.ContainsKey(key))
            {
                _cache[key] = res;
                return;
            }

            if (_cache.Count >= _maxCacheSize)
            {
                string? oldest = _cacheOrder.First?.Value;
                if (oldest != null)
                {
                    _cacheOrder.RemoveFirst();
                    _cache.Remove(oldest);
                }
            }

            _cache[key] = res;
            _cacheOrder.AddLast(key);
        }
    }
}
