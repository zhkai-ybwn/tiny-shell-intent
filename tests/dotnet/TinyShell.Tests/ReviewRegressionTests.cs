using TinyShell.Core;
using TinyShell.Core.Models;
using TinyShell.Core.Parameters;
using TinyShell.Core.Storage;

namespace TinyShell.Tests;

public class ReviewRegressionTests
{
    private readonly KnowledgeBaseStore _store = new(TestHelper.KbPath);

    [Theory]
    [InlineData('\u2018')]
    [InlineData('\u2019')]
    [InlineData('\u201a')]
    [InlineData('\u201b')]
    public void SmartQuotesCannotEscapeLiteral(char quote)
    {
        string value = $"C:\\review{quote} -Recurse -ErrorAction {quote}SilentlyContinue";
        Assert.Throws<ArgumentException>(() => ParameterExtractor.EscapePowerShellLiteral(value));
        var slot = new ParameterSlot { Name = "path", Type = "path" };
        Assert.False(ParameterExtractor.ValidateParameterValue(slot, value, out _, out _));
    }

    [Theory]
    [InlineData("delete file C:\\logs\\data.tmp", "C:\\logs\\data.tmp")]
    [InlineData("delete file \"C:\\My Documents\\report.txt\"", "C:\\My Documents\\report.txt")]
    [InlineData("delete file 'C:\\My Documents\\report.txt'", "C:\\My Documents\\report.txt")]
    [InlineData("delete file .\\logs\\data.tmp", ".\\logs\\data.tmp")]
    [InlineData("delete file \\\\server\\share\\data.tmp", "\\\\server\\share\\data.tmp")]
    [InlineData("delete file logs/data.tmp", "logs/data.tmp")]
    [InlineData("delete file data.tmp", "data.tmp")]
    public void FileTargetsKeepTheirFullPath(string query, string expected)
    {
        var intent = _store.GetById("file_delete_single")!;
        var (parameters, complete) = ParameterExtractor.ExtractParameters(intent, query);
        Assert.True(complete);
        Assert.Equal(expected, parameters["path"]);
        Assert.Equal($"Remove-Item -Path '{expected}' -Force",
            ParameterExtractor.RenderCommandSafely(intent.Command, intent, parameters));
    }

    [Theory]
    [InlineData("delete file C:\\My Documents\\report.txt")]
    [InlineData("delete file a.tmp b.tmp")]
    [InlineData("delete file 'a.tmp' 'b.tmp'")]
    public void AmbiguousFileTargetsStayIncomplete(string query)
    {
        var intent = _store.GetById("file_delete_single")!;
        var (parameters, complete) = ParameterExtractor.ExtractParameters(intent, query);
        Assert.False(complete);
        Assert.Null(ParameterExtractor.RenderCommandSafely(intent.Command, intent, parameters));
    }

    [Theory]
    [InlineData("env_get_value", "check env PATH", "$env:PATH")]
    [InlineData("env_get_value", "check env NODE_ENV", "$env:NODE_ENV")]
    [InlineData("env_set_temp", "set NODE_ENV to production", "$env:NODE_ENV = 'production'")]
    public void EnvironmentNamesRenderAsIdentifiers(string id, string query, string expected)
    {
        var intent = _store.GetById(id)!;
        var (parameters, complete) = ParameterExtractor.ExtractParameters(intent, query);
        Assert.True(complete);
        Assert.Equal(expected, ParameterExtractor.RenderCommandSafely(intent.Command, intent, parameters));
    }

    [Fact]
    public void InvalidEnvironmentIdentifierCannotBeRendered()
    {
        var intent = _store.GetById("env_get_value")!;
        var slot = intent.ParameterSlots[0];
        Assert.False(ParameterExtractor.ValidateParameterValue(slot, "FOO-BAR", out _, out _));
        Assert.Null(ParameterExtractor.RenderCommandSafely(intent.Command, intent,
            new Dictionary<string, object> { ["variable_name"] = "FOO-BAR" }));
    }

    [Fact]
    public void CacheIsolatesBothInitialAndCachedResults()
    {
        var engine = new IntentEngine(TestHelper.KbPath, TestHelper.ModelPath);
        const string query = "stop-process 12480";
        var first = engine.Search(query, mode: "rule");
        Assert.NotEmpty(first.Candidates);
        var originalCommand = first.Candidates[0].Command;
        var originalParameters = new Dictionary<string, object>(first.Candidates[0].Parameters);
        Assert.NotEmpty(originalParameters);
        first.Candidates[0].Command = "mutated";
        first.Candidates[0].Parameters.Clear();
        first.DebugCandidates.Add(new Candidate { Command = "mutated" });
        var second = engine.Search(query, mode: "rule");
        Assert.NotSame(first, second);
        Assert.Equal(originalCommand, second.Candidates[0].Command);
        Assert.Equal(originalParameters, second.Candidates[0].Parameters);
        Assert.Empty(second.DebugCandidates);
        second.Candidates[0].Parameters.Clear();
        second.Candidates.Clear();
        var third = engine.Search(query, mode: "rule");
        Assert.NotEmpty(third.Candidates);
        Assert.Equal(originalParameters, third.Candidates[0].Parameters);
    }

    [Fact]
    public void CacheIsolatesRejectedDebugCandidates()
    {
        var engine = new IntentEngine(TestHelper.KbPath, TestHelper.ModelPath);
        var first = engine.Search("inspect something", mode: "model", oodThreshold: 2.0);
        Assert.True(first.IsRejected);
        Assert.NotEmpty(first.DebugCandidates);
        var expected = first.DebugCandidates[0].Command;
        first.DebugCandidates[0].Command = "mutated";
        var second = engine.Search("inspect something", mode: "model", oodThreshold: 2.0);
        Assert.Equal(expected, second.DebugCandidates[0].Command);
    }
}
