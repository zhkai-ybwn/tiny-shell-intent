using System.Linq;
using TinyShell.Core.Matchers;
using TinyShell.Core.Models;
using TinyShell.Core.Storage;
using Xunit;

namespace TinyShell.Tests;

public class RuleMatcherTests
{
    private readonly KnowledgeBaseStore _store;
    private readonly RuleMatcher _matcher;

    public RuleMatcherTests()
    {
        _store = new KnowledgeBaseStore(TestHelper.KbPath);
        _matcher = new RuleMatcher(_store);
    }

    [Fact]
    public void TestExactAliasMatches()
    {
        var cands = _matcher.Match("pwd", topK: 1);
        Assert.Single(cands);
        Assert.Equal("file_print_working_dir", cands[0].IntentId);
        Assert.Equal(1.0f, cands[0].Score);
        Assert.Equal(MatchSource.RuleExact, cands[0].Source);

        var candsCls = _matcher.Match("cls", topK: 1);
        Assert.Single(candsCls);
        Assert.Equal("sys_clear_screen", candsCls[0].IntentId);
        Assert.Equal(1.0f, candsCls[0].Score);
    }

    [Fact]
    public void TestMultiMappingAliasDoesNotShortCircuit()
    {
        // "kill" maps to both proc_kill_name and proc_kill_id
        var cands = _matcher.Match("kill", topK: 3);
        // It has multiple rule matches, so it does NOT short-circuit as a single unambiguous exact match
        Assert.True(cands.Count >= 2);
    }

    [Fact]
    public void TestNaturalLanguageDoesNotExactMatch()
    {
        // "kill process 12480 immediately" must NOT match proc_kill_name as exact rule
        var cands = _matcher.Match("kill process 12480 immediately", topK: 3);
        Assert.True(cands.Count == 0 || cands.All(c => c.Score < 0.90f));
    }
}
