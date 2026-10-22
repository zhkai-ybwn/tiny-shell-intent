using System;
using System.IO;
using TinyShell.Core;

namespace TinyShell.PowerShell;

public static class TinyShellSession
{
    private static IntentEngine? _engine;
    private static readonly object _lock = new();

    public static string DefaultKbPath { get; set; } = string.Empty;
    public static string DefaultModelPath { get; set; } = string.Empty;

    public static IntentEngine GetOrCreateEngine(string? customKbPath = null, string? customModelPath = null)
    {
        if (_engine != null && string.IsNullOrEmpty(customKbPath) && string.IsNullOrEmpty(customModelPath))
        {
            return _engine;
        }

        lock (_lock)
        {
            if (_engine != null && string.IsNullOrEmpty(customKbPath) && string.IsNullOrEmpty(customModelPath))
            {
                return _engine;
            }

            string kbPath = customKbPath ?? ResolveKbPath();
            string modelPath = customModelPath ?? ResolveModelPath();

            _engine = new IntentEngine(kbPath, modelPath, offlineMode: true);
            return _engine;
        }
    }

    private static string ResolveKbPath()
    {
        if (!string.IsNullOrEmpty(DefaultKbPath) && File.Exists(DefaultKbPath))
        {
            return DefaultKbPath;
        }

        string asmDir = AppContext.BaseDirectory;
        string[] candidates = new[]
        {
            Path.Combine(asmDir, "data", "knowledge_base.json"),
            Path.Combine(asmDir, "knowledge_base.json"),
            Path.Combine(asmDir, "..", "data", "knowledge_base.json"),
            Path.Combine(asmDir, "..", "..", "..", "..", "..", "data", "knowledge_base.json"),
            Path.Combine(Directory.GetCurrentDirectory(), "data", "knowledge_base.json"),
        };

        foreach (var c in candidates)
        {
            try
            {
                string full = Path.GetFullPath(c);
                if (File.Exists(full))
                {
                    DefaultKbPath = full;
                    return full;
                }
            }
            catch { }
        }

        return "data/knowledge_base.json";
    }

    private static string ResolveModelPath()
    {
        if (!string.IsNullOrEmpty(DefaultModelPath) && Directory.Exists(DefaultModelPath))
        {
            return DefaultModelPath;
        }

        string asmDir = AppContext.BaseDirectory;
        string[] candidates = new[]
        {
            Path.Combine(asmDir, "models", "potion-base-2M"),
            Path.Combine(asmDir, "potion-base-2M"),
            Path.Combine(asmDir, "..", "models", "potion-base-2M"),
            Path.Combine(asmDir, "..", "..", "..", "..", "..", "models", "potion-base-2M"),
            Path.Combine(Directory.GetCurrentDirectory(), "models", "potion-base-2M"),
        };

        foreach (var c in candidates)
        {
            try
            {
                string full = Path.GetFullPath(c);
                if (Directory.Exists(full) && File.Exists(Path.Combine(full, "model.safetensors")))
                {
                    DefaultModelPath = full;
                    return full;
                }
            }
            catch { }
        }

        return "models/potion-base-2M";
    }
}
