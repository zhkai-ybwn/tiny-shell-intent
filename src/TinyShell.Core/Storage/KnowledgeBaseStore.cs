using System.Text.Json;
using TinyShell.Core.Models;

namespace TinyShell.Core.Storage;

public sealed class KnowledgeBaseStore
{
    private readonly Dictionary<string, CommandIntent> _intentsById = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, List<string>> _aliasToIntents = new(StringComparer.OrdinalIgnoreCase);
    private readonly List<CommandIntent> _allIntents = new();

    public int Count => _allIntents.Count;
    public IReadOnlyList<CommandIntent> AllIntents => _allIntents;

    public KnowledgeBaseStore(string kbPath)
    {
        Load(kbPath);
    }

    private void Load(string kbPath)
    {
        if (!File.Exists(kbPath))
        {
            throw new FileNotFoundException($"Knowledge base JSON not found at: {kbPath}");
        }

        using var stream = File.OpenRead(kbPath);
        var intents = JsonSerializer.Deserialize<List<CommandIntent>>(stream);
        if (intents == null)
        {
            throw new InvalidDataException("Failed to deserialize knowledge base JSON");
        }

        foreach (var intent in intents)
        {
            _intentsById[intent.Id] = intent;
            _allIntents.Add(intent);

            // Index command primary name if available
            string primaryCmd = intent.Command.Split(' ')[0];
            AddAliasMapping(primaryCmd, intent.Id);

            // Index all configured aliases
            foreach (var alias in intent.Aliases)
            {
                AddAliasMapping(alias, intent.Id);
            }
        }
    }

    private void AddAliasMapping(string alias, string intentId)
    {
        string key = alias.Trim();
        if (string.IsNullOrEmpty(key)) return;

        if (!_aliasToIntents.TryGetValue(key, out var list))
        {
            list = new List<string>();
            _aliasToIntents[key] = list;
        }

        if (!list.Contains(intentId))
        {
            list.Add(intentId);
        }
    }

    public CommandIntent? GetById(string id)
    {
        _intentsById.TryGetValue(id, out var intent);
        return intent;
    }

    public IReadOnlyList<CommandIntent> GetByAlias(string alias)
    {
        string key = alias.Trim();
        if (_aliasToIntents.TryGetValue(key, out var ids))
        {
            var result = new List<CommandIntent>(ids.Count);
            foreach (var id in ids)
            {
                if (_intentsById.TryGetValue(id, out var it))
                {
                    result.Add(it);
                }
            }
            return result;
        }
        return Array.Empty<CommandIntent>();
    }
}
