using System.Collections.Generic;
using TinyShell.Core.Models;
using TinyShell.Core.Parameters;
using TinyShell.Core.Risk;
using TinyShell.Core.Storage;
using Xunit;

namespace TinyShell.Tests;

public class RiskAndParameterTests
{
    private readonly KnowledgeBaseStore _store;

    public RiskAndParameterTests()
    {
        _store = new KnowledgeBaseStore(TestHelper.KbPath);
    }

    [Fact]
    public void TestPortParameterExtractionSafelyIgnoresIpv4()
    {
        var intent = _store.GetById("net_test_port");
        Assert.NotNull(intent);

        string query = "test if gateway 192.168.1.1 answers icmp packets";
        var (parameters, _) = ParameterExtractor.ExtractParametersFromQuery(intent!, query);

        // Crucial bug fix: 192 or 168 must NOT be extracted as port!
        Assert.False(parameters.ContainsKey("port"), "IPv4 octets should not be extracted as port");
    }

    [Fact]
    public void TestPortParameterExtractionFromExplicitPort()
    {
        var intent = _store.GetById("net_test_port");
        Assert.NotNull(intent);

        string query = "test port 8080 on 192.168.1.1";
        var (parameters, isComplete) = ParameterExtractor.ExtractParametersFromQuery(intent!, query);

        Assert.True(parameters.ContainsKey("port"));
        Assert.Equal(8080, parameters["port"]);
        Assert.True(parameters.ContainsKey("host"));
        Assert.Equal("192.168.1.1", parameters["host"]);
        Assert.True(isComplete);
    }

    [Fact]
    public void TestCommandWithPlaceholdersIsNotComplete()
    {
        var intent = _store.GetById("file_copy");
        Assert.NotNull(intent);

        // When source/dest are missing, command template contains <source>
        var (parameters, isComplete) = ParameterExtractor.ExtractParametersFromQuery(intent!, "clone directory tree over to d drive");
        Assert.False(isComplete, "Command with missing placeholders must not be marked complete");
    }

    [Fact]
    public void TestInjectionPreventionInEscaping()
    {
        Assert.Throws<System.ArgumentException>(() =>
        {
            ParameterExtractor.EscapePowerShellLiteral("test; Remove-Item C:\\ -Recurse");
        });

        Assert.Throws<System.ArgumentException>(() =>
        {
            ParameterExtractor.EscapePowerShellLiteral("$(whoami)");
        });

        Assert.Throws<System.ArgumentException>(() =>
        {
            ParameterExtractor.EscapePowerShellLiteral("`$evil");
        });

        string safe = ParameterExtractor.EscapePowerShellLiteral("simple_file.txt");
        Assert.Equal("'simple_file.txt'", safe);
    }

    [Fact]
    public void TestRiskNonDowngrading()
    {
        var rebootIntent = _store.GetById("sys_reboot_machine");
        Assert.NotNull(rebootIntent);

        // Base intent is dangerous
        var (effRisk, _) = RiskEvaluator.EvaluateCommandRisk(rebootIntent!, "Restart-Computer");
        Assert.Equal(RiskLevel.Dangerous, effRisk);

        // Cannot be downgraded to safe even if clean
        var (effRisk2, _) = RiskEvaluator.EvaluateCommandRisk(rebootIntent!, "Restart-Computer -WhatIf");
        Assert.Equal(RiskLevel.Dangerous, effRisk2);
    }
}
