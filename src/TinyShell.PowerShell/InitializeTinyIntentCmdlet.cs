using System.Management.Automation;
using TinyShell.Core;

namespace TinyShell.PowerShell;

[Cmdlet(VerbsData.Initialize, "TinyIntent")]
public sealed class InitializeTinyIntentCmdlet : PSCmdlet
{
    [Parameter]
    public string? KnowledgeBasePath { get; set; }

    [Parameter]
    public string? ModelPath { get; set; }

    [Parameter]
    public SwitchParameter PreloadModel { get; set; }

    protected override void ProcessRecord()
    {
        var engine = TinyShellSession.GetOrCreateEngine(KnowledgeBasePath, ModelPath);
        if (PreloadModel.IsPresent)
        {
            _ = engine.GetModelMatcher();
            WriteVerbose("TinyShell Model2Vec model pre-loaded into memory.");
        }
        WriteObject(new
        {
            Status = "Initialized",
            KnowledgeBasePath = TinyShellSession.DefaultKbPath,
            ModelPath = TinyShellSession.DefaultModelPath,
            IsModelLoaded = engine.IsModelLoaded
        });
    }
}
