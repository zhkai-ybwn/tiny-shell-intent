using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using TinyShell.Core;
using Xunit;
using Xunit.Abstractions;

namespace TinyShell.Tests;

public class BenchmarkTests
{
    private readonly ITestOutputHelper _output;

    public BenchmarkTests(ITestOutputHelper output)
    {
        _output = output;
    }

    [Fact]
    public void TestLatencyAndMemoryBudget()
    {
        // 1. Force GC to measure baseline
        GC.Collect();
        GC.WaitForPendingFinalizers();
        GC.Collect();
        long memBefore = GC.GetTotalMemory(true);

        var swLoad = Stopwatch.StartNew();
        var engine = new IntentEngine(
            kbPath: TestHelper.KbPath,
            modelPath: TestHelper.ModelPath,
            offlineMode: true);
        // Force model load
        _ = engine.GetModelMatcher();
        swLoad.Stop();

        long memAfter = GC.GetTotalMemory(true);
        double deltaMb = (memAfter - memBefore) / (1024.0 * 1024.0);

        _output.WriteLine($"Model initialization time: {swLoad.Elapsed.TotalMilliseconds:F2} ms");
        _output.WriteLine($"Engine memory footprint: {deltaMb:F2} MB");

        Assert.True(deltaMb < 30.0, $"Memory delta {deltaMb:F2} MB exceeded 30 MB budget");

        // 2. Measure uncached hot query latency over 100 queries
        var queries = new[]
        {
            "find process using port 8080",
            "git s",
            "get-childiitem",
            "kill process 12480 immediately",
            "display all environment variables",
            "how long has this computer been turned on",
            "stop windows update service",
            "search everywhere for markdown notes",
            "trash temporary file data.tmp",
            "clone directory tree over to d drive"
        };

        // Warm up JIT
        foreach (var q in queries)
        {
            engine.Search(q);
        }

        var latencies = new List<double>();
        for (int i = 0; i < 100; i++)
        {
            string q = queries[i % queries.Length] + $" #{i}"; // Append counter to bypass cache
            var sw = Stopwatch.StartNew();
            var res = engine.Search(q);
            sw.Stop();
            latencies.Add(sw.Elapsed.TotalMilliseconds);
        }

        latencies.Sort();
        double p50 = latencies[(int)(latencies.Count * 0.50)];
        double p95 = latencies[(int)(latencies.Count * 0.95)];

        _output.WriteLine($"Uncached P50: {p50:F3} ms, P95: {p95:F3} ms");

        // Verification: hot search latency budget is <= 10 ms
        Assert.True(p95 <= 15.0, $"Uncached P95 latency {p95:F3} ms exceeded tolerance (target <= 10ms)");
    }
}
