"""Model2Vec static embedding matcher."""

import os
from pathlib import Path
from typing import List, Optional
import numpy as np
from model2vec import StaticModel

from ..schema import Candidate, MatchSource, CommandIntent
from ..store import KnowledgeBaseStore
from .base import BaseMatcher


class ModelMatcher(BaseMatcher):
    """Semantic intent matcher using Model2Vec static embeddings (potion-base-2M)."""

    def __init__(
        self,
        store: KnowledgeBaseStore,
        model_name_or_path: str = "./models/potion-base-2M",
        offline_mode: bool = True,
    ):
        self.store = store
        self.model_path = Path(model_name_or_path)
        self.offline_mode = offline_mode
        self.model: Optional[StaticModel] = None
        self._intents_list: List[CommandIntent] = []
        self._exemplar_matrix: Optional[np.ndarray] = None
        self._exemplar_to_intent_idx: Optional[np.ndarray] = None

        self._load_and_index()

    def _load_and_index(self) -> None:
        """Load Model2Vec model and pre-compute intent embeddings."""
        if self.model_path.exists():
            self.model = StaticModel.from_pretrained(str(self.model_path))
        else:
            if self.offline_mode:
                raise FileNotFoundError(
                    f"Model not found at '{self.model_path}' and offline_mode=True. "
                    f"Please download the model first or disable offline mode."
                )
            # Online fallback: download and cache locally
            self.model = StaticModel.from_pretrained("minishlab/potion-base-2M")
            self.model_path.mkdir(parents=True, exist_ok=True)
            self.model.save_pretrained(str(self.model_path))

        self._build_index()

    def _build_index(self) -> None:
        """Pre-compute normalized embedding vectors for all knowledge base exemplars."""
        self._intents_list = self.store.all_intents()
        exemplar_texts: List[str] = []
        exemplar_indices: List[int] = []

        for idx, intent in enumerate(self._intents_list):
            # Exemplar 1: Description
            exemplar_texts.append(intent.description)
            exemplar_indices.append(idx)

            # Exemplar 2: Intent phrases (canonical semantic expressions)
            for phrase in intent.intent_phrases:
                clean_p = phrase.strip()
                if clean_p:
                    exemplar_texts.append(clean_p)
                    exemplar_indices.append(idx)

        # Batch encode all exemplars
        raw_embs = self.model.encode(exemplar_texts)
        norms = np.linalg.norm(raw_embs, axis=1, keepdims=True)
        # Prevent division by zero
        norms[norms == 0] = 1e-9
        self._exemplar_matrix = raw_embs / norms
        self._exemplar_to_intent_idx = np.array(exemplar_indices, dtype=np.int32)

    def match(self, query: str, top_k: int = 3) -> List[Candidate]:
        clean_q = query.strip()
        if not clean_q or self._exemplar_matrix is None or self.model is None:
            return []

        # Encode query
        q_emb = self.model.encode([clean_q])[0]
        q_norm = np.linalg.norm(q_emb)
        if q_norm == 0:
            return []
        q_emb = q_emb / q_norm

        # Cosine similarity matrix dot product
        similarities = np.dot(self._exemplar_matrix, q_emb)

        # Aggregate max similarity per intent
        num_intents = len(self._intents_list)
        best_scores = np.full(num_intents, -1.0, dtype=np.float32)
        np.maximum.at(best_scores, self._exemplar_to_intent_idx, similarities)

        # Rank intents
        top_indices = np.argsort(best_scores)[::-1][:top_k]

        candidates: List[Candidate] = []
        for idx in top_indices:
            score = float(best_scores[idx])
            intent = self._intents_list[idx]
            candidates.append(
                Candidate(
                    command=intent.command,
                    intent_id=intent.id,
                    description=intent.description,
                    score=round(score, 4),
                    source=MatchSource.MODEL.value,
                    risk_level=intent.risk_level.value,
                    category=intent.category,
                    risk_reason=intent.risk_reason,
                    command_template=intent.command,
                    is_complete=len(intent.parameter_slots) == 0,
                )
            )

        return candidates
