"""Tests the Chroma store with a fake embedder (no model download needed)."""

import pytest

chromadb = pytest.importorskip("chromadb")

from ingest.models import Chunk  # noqa: E402
from ingest.store import VectorStore  # noqa: E402


class FakeEmbedder:
    def embed(self, texts):
        return [[float(len(t) % 7), 1.0, 0.5] for t in texts]


def _chunks(source_id, n):
    return [Chunk(f"{source_id}:{i}", f"text {i}", {"source_id": source_id, "title": "t"}) for i in range(n)]


def test_replace_prune_and_reset(tmp_path):
    store = VectorStore(tmp_path / "chroma", "test", FakeEmbedder())
    store.replace_source("a", _chunks("a", 3))
    store.replace_source("b", _chunks("b", 2))
    assert store.counts_by_source() == {"a": 3, "b": 2}

    store.replace_source("a", _chunks("a", 1))  # re-ingesting replaces, never duplicates
    assert store.counts_by_source() == {"a": 1, "b": 2}

    assert store.prune({"a"}) == ["b"]
    assert store.counts_by_source() == {"a": 1}

    store.reset()
    assert store.counts_by_source() == {}
