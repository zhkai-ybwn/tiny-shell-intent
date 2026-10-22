using System;
using System.IO;
using System.Linq;
using System.Text.Json;
using TinyShell.Core;
using Xunit;
using Xunit.Abstractions;

namespace TinyShell.Tests;

public class FullDatasetEvaluationTests
{
    private readonly ITestOutputHelper _output;
    private readonly IntentEngine _engine;

    public FullDatasetEvaluationTests(ITestOutputHelper output)
    {
        _output = output;
        _engine = new IntentEngine(TestHelper.KbPath, TestHelper.ModelPath);
    }

    [Fact]
    public void EvaluateEntireTestSet()
    {
        string testQueriesPath = Path.Combine(TestHelper.RepoRoot, "data", "test_queries.json");
        string json = File.ReadAllText(testQueriesPath);
        using var doc = JsonDocument.Parse(json);

        int totalInDomain = 0;
        int top1Hits = 0;
        int top3Hits = 0;

        int totalNegative = 0;
        int negativeRejected = 0;

        foreach (var item in doc.RootElement.EnumerateArray())
        {
            string query = item.GetProperty("query").GetString()!;
            string? expectedIntent = item.GetProperty("expected_intent_id").ValueKind == JsonValueKind.Null
                ? null
                : item.GetProperty("expected_intent_id").GetString();
            string qType = item.GetProperty("type").GetString()!;

            var res = _engine.Search(query, topK: 3, mode: "hybrid");

            if (expectedIntent == null || qType is "out_of_domain" or "edge_case")
            {
                totalNegative++;
                if (res.IsRejected || res.IsOutOfDomain || res.Candidates.Count == 0)
                {
                    negativeRejected++;
                }
            }
            else
            {
                totalInDomain++;
                if (res.Candidates.Count > 0)
                {
                    if (res.Candidates[0].IntentId == expectedIntent)
                    {
                        top1Hits++;
                        top3Hits++;
                    }
                    else if (res.Candidates.Any(c => c.IntentId == expectedIntent))
                    {
                        top3Hits++;
                    }
                    else
                    {
                        _output.WriteLine($"Missed query: '{query}', expected: {expectedIntent}, got top 3: {string.Join(", ", res.Candidates.Select(c => c.IntentId))}");
                    }
                }
            }
        }

        double top1Rate = (double)top1Hits / totalInDomain * 100.0;
        double top3Rate = (double)top3Hits / totalInDomain * 100.0;
        double negRate = (double)negativeRejected / totalNegative * 100.0;

        _output.WriteLine($"Evaluated {totalInDomain} in-domain queries:");
        _output.WriteLine($"  Hybrid Top-1: {top1Hits}/{totalInDomain} ({top1Rate:F1}%)");
        _output.WriteLine($"  Hybrid Top-3: {top3Hits}/{totalInDomain} ({top3Rate:F1}%)");
        _output.WriteLine($"Evaluated {totalNegative} negative/edge queries (13 OOD + 4 empty/symbol):");
        _output.WriteLine($"  Rejection rate: {negativeRejected}/{totalNegative} ({negRate:F1}%)");

        // Parity with Python benchmark: 88.0% Top-1, 100.0% Top-3, 100% negative rejection
        Assert.True(top1Rate >= 88.0, $"Top-1 rate {top1Rate:F1}% is below 88.0%");
        Assert.True(top3Rate >= 99.0, $"Top-3 rate {top3Rate:F1}% is below 99.0%");
        Assert.Equal(totalNegative, negativeRejected);
    }
}
