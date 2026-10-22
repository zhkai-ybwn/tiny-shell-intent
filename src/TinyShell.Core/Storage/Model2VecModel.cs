using TinyShell.Core.Tokenizer;

namespace TinyShell.Core.Storage;

public sealed class Model2VecModel
{
    private readonly float[] _embeddingMatrix;
    private readonly int _vocabSize;
    private readonly int _dim;
    private readonly WordPieceTokenizer _tokenizer;

    public int Dim => _dim;
    public int EmbeddingDim => _dim;
    public int VocabSize => _vocabSize;
    public WordPieceTokenizer Tokenizer => _tokenizer;

    public Model2VecModel(float[] embeddingMatrix, int vocabSize, int dim, WordPieceTokenizer tokenizer)
    {
        _embeddingMatrix = embeddingMatrix;
        _vocabSize = vocabSize;
        _dim = dim;
        _tokenizer = tokenizer;
    }

    public static Model2VecModel Load(string modelDir)
    {
        string safetensorsPath = Path.Combine(modelDir, "model.safetensors");
        string tokenizerJsonPath = Path.Combine(modelDir, "tokenizer.json");

        if (!File.Exists(safetensorsPath))
        {
            throw new FileNotFoundException($"Model weights not found at: {safetensorsPath}");
        }
        if (!File.Exists(tokenizerJsonPath))
        {
            throw new FileNotFoundException($"Tokenizer not found at: {tokenizerJsonPath}");
        }

        var tokenizer = WordPieceTokenizer.FromJsonFile(tokenizerJsonPath);
        var (data, rows, cols) = SafetensorsReader.LoadEmbeddings(safetensorsPath);

        return new Model2VecModel(data, rows, cols, tokenizer);
    }

    public static Model2VecModel LoadFromDirectory(string modelDir) => Load(modelDir);

    public float[] EncodeSingle(string text, bool normalize = true) => Encode(text, normalize);

    public float[][] Encode(IEnumerable<string> texts, bool normalize = true)
    {
        var list = texts.ToList();
        var results = new float[list.Count][];
        for (int i = 0; i < list.Count; i++)
        {
            results[i] = Encode(list[i], normalize);
        }
        return results;
    }

    public float[] Encode(string text, bool normalize = true)
    {
        var tokenIds = _tokenizer.Tokenize(text);
        if (tokenIds.Count == 0)
        {
            return new float[_dim];
        }

        float[] meanVec = new float[_dim];
        int count = tokenIds.Count;

        foreach (int tokenId in tokenIds)
        {
            if (tokenId < 0 || tokenId >= _vocabSize)
            {
                continue;
            }

            int offset = tokenId * _dim;
            for (int d = 0; d < _dim; d++)
            {
                meanVec[d] += _embeddingMatrix[offset + d];
            }
        }

        float invCount = 1.0f / count;
        for (int d = 0; d < _dim; d++)
        {
            meanVec[d] *= invCount;
        }

        if (normalize)
        {
            float sumSq = 0f;
            for (int d = 0; d < _dim; d++)
            {
                sumSq += meanVec[d] * meanVec[d];
            }
            float norm = MathF.Sqrt(sumSq) + 1e-32f;
            float invNorm = 1.0f / norm;
            for (int d = 0; d < _dim; d++)
            {
                meanVec[d] *= invNorm;
            }
        }

        return meanVec;
    }
}
