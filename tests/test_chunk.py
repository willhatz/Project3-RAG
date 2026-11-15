from ingest.chunk import chunk_documents, chunk_text
from ingest.models import Document


def test_short_text_is_one_chunk(tokenizer):
    assert chunk_text("one two three", tokenizer, max_tokens=10, overlap=2) == ["one two three"]


def test_empty_text_has_no_chunks(tokenizer):
    assert chunk_text("   ", tokenizer, max_tokens=10, overlap=2) == []


def test_long_text_is_split_with_overlap(tokenizer):
    words = [f"w{i}" for i in range(25)]
    chunks = chunk_text(" ".join(words), tokenizer, max_tokens=10, overlap=3)
    assert all(len(c.split()) <= 10 for c in chunks)
    # every word appears somewhere, and consecutive chunks share the overlap
    assert set(" ".join(chunks).split()) == set(words)
    assert chunks[0].split()[-3:] == chunks[1].split()[:3]


def test_chunks_prefer_sentence_boundaries(tokenizer):
    text = "a b c d e f g h. i j k l m n o p q r s t"
    first = chunk_text(text, tokenizer, max_tokens=10, overlap=2)[0]
    assert first.endswith("h.")


def test_chunk_documents_metadata(tokenizer):
    doc = Document(doc_id="abc", source_id="src", method="scrape", region="sri_lanka",
                   event="cyclone_ditwah", url="https://x.org", title="T", text="word " * 30,
                   published="2025-11-30", language="ta", publisher=None)
    chunks = chunk_documents([doc], tokenizer, max_tokens=10, overlap=2)
    assert len(chunks) > 1
    assert chunks[0].chunk_id == "abc:0"
    meta = chunks[0].metadata
    assert meta["language"] == "ta" and meta["source_id"] == "src"
    assert "publisher" not in meta  # None values are dropped for Chroma
