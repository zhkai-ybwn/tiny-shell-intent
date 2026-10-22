using System.Management.Automation;
using TinyShell.Core;
using TinyShell.Core.Models;

namespace TinyShell.PowerShell;

[Cmdlet(VerbsCommon.Get, "TinyIntent")]
[OutputType(typeof(QueryResult))]
public sealed class GetTinyIntentCmdlet : PSCmdlet
{
    [Parameter(Position = 0, Mandatory = true, ValueFromPipeline = true)]
    public string Query { get; set; } = string.Empty;

    [Parameter]
    public int Top { get; set; } = 3;

    [Parameter]
    [ValidateSet("hybrid", "rule", "fuzzy", "model")]
    public string Mode { get; set; } = "hybrid";

    [Parameter]
    public double OodThreshold { get; set; } = 0.42;

    [Parameter]
    public string? KnowledgeBasePath { get; set; }

    [Parameter]
    public string? ModelPath { get; set; }

    protected override void ProcessRecord()
    {
        var engine = TinyShellSession.GetOrCreateEngine(KnowledgeBasePath, ModelPath);
        var result = engine.Search(Query, Top, Mode, OodThreshold);
        WriteObject(result);
    }
}
