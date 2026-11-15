"""Embedding (bge-m3) and storage (Chroma).

The chat backend (Story 2) should import ``Embedder`` and ``VectorStore`` from here so that
questions are embedded with exactly the same model as the documents.
"""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path

from .models import Chunk

log = logging.getLogger(__name__)

BATCH_SIZE = 64


class Embedder:
    """Lazy-loads the sentence-transformers model on first use (first run downloads ~2.3 GB for bge-m3)."""

    def __init__(self, model_name: str):
        self.model_name = model_name
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            log.info("Loading embedding model %s (first run downloads it)...", self.model_name)
            self._model = SentenceTransformer(self.model_name)
        return self._model

    @property
    def tokenizer(self):
        return self.model.tokenizer

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self.model.encode(
            texts,
            batch_size=16,
            normalize_embeddings=True,
            show_progress_bar=len(texts) > 32,
        )
        return vectors.tolist()


class VectorStore:
    def __init__(self, path: Path, collection: str, embedder: Embedder | None = None):
        import chromadb

        path.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(path))
        self.collection_name = collection
        self.embedder = embedder
        self.collection = self._get_collection()

    def _get_collection(self):
        # embedding_function=None: we always pass our own bge-m3 vectors.
        return self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
            embedding_function=None,
        )

    def replace_source(self, source_id: str, chunks: list[Chunk]) -> None:
        """Delete every chunk from ``source_id`` and insert the new ones (keeps re-runs idempotent)."""
        if self.embedder is None:
            raise RuntimeError("VectorStore needs an Embedder to add chunks")
        self.delete_source(source_id)
        for i in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[i:i + BATCH_SIZE]
            # Prefix the title so short chunks still carry their document's topic into the vector.
            texts = [f"{c.metadata.get('title', '')}\n\n{c.text}" for c in batch]
            self.collection.add(
                ids=[c.chunk_id for c in batch],
                documents=[c.text for c in batch],
                metadatas=[c.metadata for c in batch],
                embeddings=self.embedder.embed(texts),
            )

    def delete_source(self, source_id: str) -> None:
        self.collection.delete(where={"source_id": source_id})

    def prune(self, keep_source_ids: set[str]) -> list[str]:
        """Remove chunks from sources that are no longer enabled in sources.yaml."""
        removed = [sid for sid in self.counts_by_source() if sid not in keep_source_ids]
        for sid in removed:
            self.delete_source(sid)
        return removed

    def reset(self) -> None:
        """Delete everything (used by --rebuild)."""
        try:
            self.client.delete_collection(self.collection_name)
        except Exception:  # collection did not exist
            pass
        self.collection = self._get_collection()

    def counts_by_source(self) -> dict[str, int]:
        result = self.collection.get(include=["metadatas"])
        return dict(Counter(m.get("source_id", "?") for m in result["metadatas"] or []))
