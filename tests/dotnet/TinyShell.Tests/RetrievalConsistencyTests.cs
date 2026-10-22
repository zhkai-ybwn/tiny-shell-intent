using System;
using System.IO;
using System.Linq;
using System.Text.Json;
using TinyShell.Core;
using TinyShell.Core.Models;
using Xunit;

namespace TinyShell.Tests;

public class RetrievalConsistencyTests
{
    private readonly IntentEngine _engine;

    public RetrievalConsistencyTests()
    {
        _engine = new IntentEngine(
            kbPath: TestHelper.KbPath,
            modelPath: TestHelper.ModelPath,
            offlineMode: true);
    }

    [Fact]
    public void TestCrossLanguageRetrievalParity()
    {
        string json = File.ReadAllText(TestHelper.CrossLanguageCasesPath);
        using var doc = JsonDocument.Parse(json);
        var retrievalCases = doc.RootElement.GetProperty("retrieval_cases");

        foreach (var element in retrievalCases.EnumerateArray())
        {
            string query = element.GetProperty("query").GetString()!;
            string mode = element.GetProperty("mode").GetString()!;
            bool expectedAccepted = element.GetProperty("is_accepted").GetBoolean();
            bool expectedRejected = element.GetProperty("is_rejected").GetBoolean();
            bool expectedOod = element.GetProperty("is_out_of_domain").GetBoolean();
            string? expectedTopIntent = element.TryGetProperty("top_intent_id", out var topProp) ? topProp.GetString() : null;

            var res = _engine.Search(query, topK: 3, mode: mode);

            Assert.Equal(expectedAccepted, res.IsAccepted);
            Assert.Equal(expectedRejected, res.IsRejected);
            Assert.Equal(expectedOod, res.IsOutOfDomain);

            if (expectedAccepted && expectedTopIntent != null)
            {
                Assert.NotEmpty(res.Candidates);
                Assert.Equal(expectedTopIntent, res.Candidates[0].IntentId);
            }
            else if (expectedRejected)
            {
                Assert.Empty(res.Candidates);
            }
        }
    }

    [Fact]
    public void TestAllAmbiguousCasesHandledSafely()
    {
        // 1. kill process 12480 immediately -> proc_kill_id (NOT proc_kill_name)
        var res1 = _engine.Search("kill process 12480 immediately");
        Assert.True(res1.IsAccepted);
        Assert.Equal("proc_kill_id", res1.Candidates[0].IntentId);
        Assert.Equal(RiskLevel.Dangerous.ToSerializedString(), res1.Candidates[0].RiskLevel);

        // 2. stop windows update service immediately -> sys_service_stop (NOT start)
        var res2 = _engine.Search("stop windows update service immediately");
        Assert.True(res2.IsAccepted);
        Assert.Equal("sys_service_stop", res2.Candidates[0].IntentId);

        // 3. how long has this computer been turned on without restarting -> sys_uptime (NOT reboot)
        var res3 = _engine.Search("how long has this computer been turned on without restarting");
        Assert.True(res3.IsAccepted);
        Assert.Equal("sys_uptime", res3.Candidates[0].IntentId);
        Assert.Equal(RiskLevel.Safe.ToSerializedString(), res3.Candidates[0].RiskLevel);

        // 4. clone directory tree over to d drive -> file_copy (NOT delete)
        var res4 = _engine.Search("clone directory tree over to d drive");
        Assert.True(res4.IsAccepted);
        Assert.Equal("file_copy", res4.Candidates[0].IntentId);

        // 5. trash temporary file data.tmp -> file_delete_single (NOT sys_clear_recycle_bin)
        var res5 = _engine.Search("trash temporary file data.tmp");
        Assert.True(res5.IsAccepted);
        Assert.Equal("file_delete_single", res5.Candidates[0].IntentId);

        // 6. test if gateway 192.168.1.1 answers icmp packets -> net_ping_host (NOT test port)
        var res6 = _engine.Search("test if gateway 192.168.1.1 answers icmp packets");
        Assert.True(res6.IsAccepted);
        Assert.Equal("net_ping_host", res6.Candidates[0].IntentId);
    }
}
