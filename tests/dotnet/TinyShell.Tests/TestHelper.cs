using System;
using System.IO;

namespace TinyShell.Tests;

public static class TestHelper
{
    private static string? _repoRoot;

    public static string RepoRoot
    {
        get
        {
            if (_repoRoot != null) return _repoRoot;

            string current = AppContext.BaseDirectory;
            while (!string.IsNullOrEmpty(current))
            {
                if (File.Exists(Path.Combine(current, "TinyShell.sln")) ||
                    File.Exists(Path.Combine(current, "data", "knowledge_base.json")))
                {
                    _repoRoot = current;
                    return _repoRoot;
                }
                var parent = Directory.GetParent(current);
                if (parent == null) break;
                current = parent.FullName;
            }

            // Fallback to current directory
            _repoRoot = Directory.GetCurrentDirectory();
            return _repoRoot;
        }
    }

    public static string KbPath => Path.Combine(RepoRoot, "data", "knowledge_base.json");
    public static string ModelPath => Path.Combine(RepoRoot, "models", "potion-base-2M");
    public static string CrossLanguageCasesPath => Path.Combine(RepoRoot, "data", "cross_language_test_cases.json");
}
