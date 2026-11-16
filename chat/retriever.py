
from functools import lru_cache
from ingest.config import load_config
from ingest.store import Embedder, VectorStore
@lru_cache(maxsize=1)
def get_store():
    settings, _ = load_config()
    embedder = Embedder(settings.embed_model)
    return VectorStore(
        settings.chroma_path,
        settings.collection,
        embedder
    )
def retrieve(question, event="cyclone_ditwah", limit=5):
    store = get_store()

    results = store.collection.query(
        query_embeddings=store.embedder.embed([question]),
        n_results=limit,
        where={"event": event},
        include=["documents", "metadatas"]
    )
    return [
        {"text": text, "metadata": metadata}
        for text, metadata in zip(
            results["documents"][0],
            results["metadatas"][0]
        )
    ]
if __name__ == "__main__":
    matches = retrieve("What happened during Cyclone Ditwah?")
    for i, match in enumerate(matches, 1):
        print(f"\nResult {i}")
        print("Source:", match["metadata"].get("title"))
        print("Text:", match["text"][:400])
