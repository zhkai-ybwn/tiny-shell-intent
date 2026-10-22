using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using TinyShell.Core.Tokenizer;
using Xunit;

namespace TinyShell.Tests;

public class TokenizerTests
{
    private readonly WordPieceTokenizer _tokenizer;

    public TokenizerTests()
    {
        string tokenizerJsonPath = Path.Combine(TestHelper.ModelPath, "tokenizer.json");
        _tokenizer = WordPieceTokenizer.FromJsonFile(tokenizerJsonPath);
    }

    [Fact]
    public void TestSpecialTokensAndVocabSize()
    {
        Assert.True(_tokenizer.VocabSize > 20000, $"Vocab size should be > 20000, got {_tokenizer.VocabSize}");
        Assert.Equal(1, WordPieceTokenizer.UnkTokenId);
    }

    [Fact]
    public void TestCrossLanguageTokenizationParity()
    {
        string json = File.ReadAllText(TestHelper.CrossLanguageCasesPath);
        using var doc = JsonDocument.Parse(json);
        var vectorCases = doc.RootElement.GetProperty("vector_cases");

        foreach (var element in vectorCases.EnumerateArray())
        {
            string query = element.GetProperty("query").GetString()!;
            var expectedTokenIds = new List<int>();
            foreach (var id in element.GetProperty("token_ids").EnumerateArray())
            {
                expectedTokenIds.Add(id.GetInt32());
            }

            var actualTokenIds = _tokenizer.Tokenize(query);
            Assert.Equal(expectedTokenIds, actualTokenIds);
        }
    }
}
