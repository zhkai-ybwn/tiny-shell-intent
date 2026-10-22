using System;
using System.IO;
using System.Text.Json;
using TinyShell.Core.Storage;
using Xunit;

namespace TinyShell.Tests;

public class VectorConsistencyTests
{
    private readonly Model2VecModel _model;

    public VectorConsistencyTests()
    {
        _model = Model2VecModel.Load(TestHelper.ModelPath);
    }

    [Fact]
    public void TestEmbeddingDimensions()
    {
        Assert.Equal(64, _model.Dim);
        Assert.Equal(29528, _model.VocabSize);
    }

    [Fact]
    public void TestCrossLanguageEmbeddingVectors()
    {
        string json = File.ReadAllText(TestHelper.CrossLanguageCasesPath);
        using var doc = JsonDocument.Parse(json);
        var vectorCases = doc.RootElement.GetProperty("vector_cases");

        foreach (var element in vectorCases.EnumerateArray())
        {
            string query = element.GetProperty("query").GetString()!;
            float expectedNorm = (float)element.GetProperty("norm").GetDouble();
            var expectedEmb = new float[64];
            int i = 0;
            foreach (var val in element.GetProperty("embedding").EnumerateArray())
            {
                expectedEmb[i++] = (float)val.GetDouble();
            }

            float[] actualEmb = _model.Encode(query, normalize: true);
            Assert.Equal(64, actualEmb.Length);

            if (expectedNorm == 0.0f)
            {
                foreach (float v in actualEmb)
                {
                    Assert.Equal(0.0f, v);
                }
                continue;
            }

            // Compute cosine dot product and max absolute difference
            float dot = 0.0f;
            float maxDiff = 0.0f;
            for (int d = 0; d < 64; d++)
            {
                dot += actualEmb[d] * expectedEmb[d];
                float diff = Math.Abs(actualEmb[d] - expectedEmb[d]);
                if (diff > maxDiff) maxDiff = diff;
            }

            // Assert high precision match with python output:
            // Max diff must be < 1e-4, cosine dot product must be > 0.9999
            Assert.True(maxDiff < 1e-4f, $"Query '{query}' max float diff is {maxDiff}, expected < 1e-4");
            Assert.True(dot > 0.9999f, $"Query '{query}' cosine dot is {dot}, expected > 0.9999");
        }
    }
}
