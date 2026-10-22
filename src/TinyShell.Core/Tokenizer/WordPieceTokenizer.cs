using System.Globalization;
using System.Text;
using System.Text.Json;

namespace TinyShell.Core.Tokenizer;

public sealed class WordPieceTokenizer
{
    private readonly Dictionary<string, int> _vocab;
    private const int MaxInputCharsPerWord = 100;
    public const int UnkTokenId = 1;

    public int VocabSize => _vocab.Count;

    public WordPieceTokenizer(Dictionary<string, int> vocab)
    {
        _vocab = vocab;
    }

    public static WordPieceTokenizer FromJsonFile(string tokenizerJsonPath)
    {
        using var stream = File.OpenRead(tokenizerJsonPath);
        using var doc = JsonDocument.Parse(stream);
        var vocabElem = doc.RootElement.GetProperty("model").GetProperty("vocab");
        var vocab = new Dictionary<string, int>(vocabElem.EnumerateObject().Count());
        foreach (var prop in vocabElem.EnumerateObject())
        {
            vocab[prop.Name] = prop.Value.GetInt32();
        }
        return new WordPieceTokenizer(vocab);
    }

    public List<int> Tokenize(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return new List<int>();
        }

        // 1. Clean & Normalize
        var sb = new StringBuilder(text.Length * 2);
        for (int i = 0; i < text.Length; i++)
        {
            char ch = text[i];
            int cp = char.ConvertToUtf32(text, i);
            if (char.IsSurrogate(ch))
            {
                i++; // Skip trail surrogate
            }

            if (cp == 0 || cp == 0xFFFD || IsControl(ch))
            {
                continue;
            }

            if (IsWhitespace(ch))
            {
                sb.Append(' ');
            }
            else if (IsCjk(cp))
            {
                sb.Append(' ').Append(char.ConvertFromUtf32(cp)).Append(' ');
            }
            else
            {
                sb.Append(char.ConvertFromUtf32(cp));
            }
        }

        string cleanText = sb.ToString().ToLowerInvariant();

        // 2. Pre-tokenize: whitespace and punctuation split
        var words = new List<string>();
        var currentWord = new StringBuilder();

        for (int i = 0; i < cleanText.Length; i++)
        {
            char ch = cleanText[i];
            if (IsWhitespace(ch))
            {
                if (currentWord.Length > 0)
                {
                    words.Add(currentWord.ToString());
                    currentWord.Clear();
                }
            }
            else if (IsPunctuation(ch))
            {
                if (currentWord.Length > 0)
                {
                    words.Add(currentWord.ToString());
                    currentWord.Clear();
                }
                words.Add(ch.ToString());
            }
            else
            {
                currentWord.Append(ch);
            }
        }

        if (currentWord.Length > 0)
        {
            words.Add(currentWord.ToString());
        }

        // 3. WordPiece greedy longest-match-first
        var tokenIds = new List<int>();
        foreach (var word in words)
        {
            if (word.Length > MaxInputCharsPerWord)
            {
                continue; // [UNK] is filtered out in Model2Vec
            }

            int start = 0;
            var subTokens = new List<int>();
            bool isBad = false;

            while (start < word.Length)
            {
                int end = word.Length;
                string? curSubstr = null;

                while (start < end)
                {
                    string substr = word.Substring(start, end - start);
                    if (start > 0)
                    {
                        substr = "##" + substr;
                    }

                    if (_vocab.TryGetValue(substr, out int id))
                    {
                        curSubstr = substr;
                        subTokens.Add(id);
                        break;
                    }

                    end--;
                }

                if (curSubstr == null)
                {
                    isBad = true;
                    break;
                }

                start = end;
            }

            if (!isBad)
            {
                foreach (int tid in subTokens)
                {
                    if (tid != UnkTokenId)
                    {
                        tokenIds.Add(tid);
                    }
                }
            }
        }

        return tokenIds;
    }

    private static bool IsWhitespace(char ch)
    {
        return ch is ' ' or '\t' or '\n' or '\r' || CharUnicodeInfo.GetUnicodeCategory(ch) == UnicodeCategory.SpaceSeparator;
    }

    private static bool IsControl(char ch)
    {
        if (ch is '\t' or '\n' or '\r')
        {
            return false;
        }
        var cat = CharUnicodeInfo.GetUnicodeCategory(ch);
        return cat is UnicodeCategory.Control or UnicodeCategory.Format;
    }

    private static bool IsPunctuation(char ch)
    {
        int cp = ch;
        if ((cp >= 33 && cp <= 47) || (cp >= 58 && cp <= 64) || (cp >= 91 && cp <= 96) || (cp >= 123 && cp <= 126))
        {
            return true;
        }
        var cat = CharUnicodeInfo.GetUnicodeCategory(ch);
        return cat is UnicodeCategory.ConnectorPunctuation
            or UnicodeCategory.DashPunctuation
            or UnicodeCategory.OpenPunctuation
            or UnicodeCategory.ClosePunctuation
            or UnicodeCategory.InitialQuotePunctuation
            or UnicodeCategory.FinalQuotePunctuation
            or UnicodeCategory.OtherPunctuation;
    }

    private static bool IsCjk(int cp)
    {
        return (cp >= 0x4E00 && cp <= 0x9FFF)
            || (cp >= 0x3400 && cp <= 0x4DBF)
            || (cp >= 0x20000 && cp <= 0x2A6DF)
            || (cp >= 0x2A700 && cp <= 0x2B73F)
            || (cp >= 0x2B740 && cp <= 0x2B81F)
            || (cp >= 0x2B820 && cp <= 0x2CEAF)
            || (cp >= 0xF900 && cp <= 0xFAFF)
            || (cp >= 0x2F800 && cp <= 0x2FA1F);
    }
}
