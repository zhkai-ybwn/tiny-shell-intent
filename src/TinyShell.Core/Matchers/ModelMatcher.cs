using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using TinyShell.Core.Models;
using TinyShell.Core.Storage;

namespace TinyShell.Core.Matchers;

/// <summary>
/// Semantic intent matcher using Model2Vec static embeddings (potion-base-2M).
/// Pre-computes exemplar vectors for fast cosine similarity dot products in memory.
/// </summary>
public class ModelMatcher : IMatcher
{
    private readonly KnowledgeBaseStore _store;
    private readonly string _modelPath;
    private readonly bool _offlineMode;
    private Model2VecModel? _model;
    private readonly List<CommandIntent> _intentsList = new();
    private float[][]? _exemplarMatrix;
    private int[]? _exemplarToIntentIdx;

    public ModelMatcher(
        KnowledgeBaseStore store,
        string modelPath = "models/potion-base-2M",
        bool offlineMode = true)
    {
        _store = store ?? throw new ArgumentNullException(nameof(store));
        _modelPath = modelPath;
        _offlineMode = offlineMode;

        LoadAndIndex();
    }

    /// <summary>
    /// Loads the Model2Vec model and pre-computes normalized exemplar embeddings.
    /// </summary>
    private void LoadAndIndex()
    {
        string safetensorsPath = Path.Combine(_modelPath, "model.safetensors");
        string tokenizerPath = Path.Combine(_modelPath, "tokenizer.json");

        if (!File.Exists(safetensorsPath) || !File.Exists(tokenizerPath))
        {
            if (_offlineMode)
            {
                throw new FileNotFoundException(
                    $"Model not found at '{_modelPath}' and offline_mode=true. " +
                    $"Please ensure model.safetensors and tokenizer.json are present.");
            }
            throw new NotSupportedException("Online model downloading is not supported in the native runtime.");
        }

        _model = Model2VecModel.Load(_modelPath);
        BuildIndex();
    }

    private void BuildIndex()
    {
        if (_model == null) return;

        _intentsList.Clear();
        _intentsList.AddRange(_store.AllIntents);

        var exemplarTexts = new List<string>();
        var exemplarIndices = new List<int>();

        for (int idx = 0; idx < _intentsList.Count; idx++)
        {
            var intent = _intentsList[idx];

            // Exemplar 1: Description
            if (!string.IsNullOrWhiteSpace(intent.Description))
            {
                exemplarTexts.Add(intent.Description);
                exemplarIndices.Add(idx);
            }

            // Exemplar 2: Intent phrases
            foreach (var phrase in intent.IntentPhrases)
            {
                string cleanP = phrase.Trim();
                if (!string.IsNullOrEmpty(cleanP))
                {
                    exemplarTexts.Add(cleanP);
                    exemplarIndices.Add(idx);
                }
            }
        }

        _exemplarMatrix = _model.Encode(exemplarTexts);
        _exemplarToIntentIdx = exemplarIndices.ToArray();
    }

    public List<Candidate> Match(string query, int topK = 3)
    {
        if (string.IsNullOrWhiteSpace(query) || _exemplarMatrix == null || _model == null || _exemplarToIntentIdx == null)
            return new List<Candidate>();

        string cleanQ = query.Trim();
        float[] qEmb = _model.EncodeSingle(cleanQ);

        int numIntents = _intentsList.Count;
        float[] bestScores = new float[numIntents];
        Array.Fill(bestScores, -1.0f);

        int numExemplars = _exemplarMatrix.Length;
        int dim = _model.EmbeddingDim;

        for (int i = 0; i < numExemplars; i++)
        {
            float[] exEmb = _exemplarMatrix[i];
            float dot = 0.0f;
            for (int d = 0; d < dim; d++)
            {
                dot += exEmb[d] * qEmb[d];
            }

            int intentIdx = _exemplarToIntentIdx[i];
            if (dot > bestScores[intentIdx])
            {
                bestScores[intentIdx] = dot;
            }
        }

        // Rank intents descending by score
        var ranked = new List<(float Score, int Index)>();
        for (int idx = 0; idx < numIntents; idx++)
        {
            ranked.Add((bestScores[idx], idx));
        }

        ranked.Sort((a, b) => b.Score.CompareTo(a.Score));

        var candidates = new List<Candidate>();
        foreach (var (score, idx) in ranked.Take(topK))
        {
            var intent = _intentsList[idx];
            candidates.Add(new Candidate
            {
                Command = intent.Command,
                IntentId = intent.Id,
                Description = intent.Description,
                Score = (float)Math.Round(score, 4),
                Source = MatchSource.Model,
                RiskLevel = intent.RiskLevel.ToSerializedString(),
                Category = intent.Category,
                RiskReason = intent.RiskReason,
                CommandTemplate = intent.Command,
                IsComplete = intent.ParameterSlots.Count == 0,
            });
        }

        return candidates;
    }
}
