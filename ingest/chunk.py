"""Splits documents into overlapping, token-limited chunks (Story 7).

Token counts use the embedding model's own tokenizer, so a "500-token chunk" means the same thing
for Tamil, Sinhala, Spanish or English text. Chunk ends are moved back to a sentence or paragraph
boundary when one is close, so chunks rarely cut a sentence in half.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from .models import Chunk, Document

# Characters that end a sentence in the supported languages (Latin, Tamil, Sinhala, Arabic).
_SENTENCE_END = set(".!?;:\n؟۔෴")


class Tokenizer(Protocol):
    """Any Hugging Face *fast* tokenizer satisfies this."""

    def __call__(self, text: str, **kwargs) -> dict: ...


def chunk_text(text: str, tokenizer: Tokenizer, max_tokens: int = 500, overlap: int = 50) -> list[str]:
    enc = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)
    offsets: list[tuple[int, int]] = list(enc["offset_mapping"])
    n = len(offsets)
    if n == 0:
        return []
    if n <= max_tokens:
        return [text.strip()]

    chunks: list[str] = []
    start = 0
    while start < n:
        end = min(start + max_tokens, n)
        if end < n:
            end = _snap_to_boundary(text, offsets, start, end, max_tokens)
        piece = text[offsets[start][0]:offsets[end - 1][1]].strip()
        if piece:
            chunks.append(piece)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return chunks


def _snap_to_boundary(text: str, offsets, start: int, end: int, max_tokens: int) -> int:
    """Move ``end`` back to just after a sentence end, but never below 70% of a full chunk."""
    floor = start + int(max_tokens * 0.7)
    for i in range(end - 1, floor - 1, -1):
        tok_end = offsets[i][1]
        if text[tok_end - 1:tok_end] in _SENTENCE_END or text[tok_end:tok_end + 1] == "\n":
            return i + 1
    return end


def chunk_documents(
    docs: list[Document], tokenizer: Tokenizer, max_tokens: int, overlap: int
) -> list[Chunk]:
    ingested_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    chunks: list[Chunk] = []
    for doc in docs:
        for i, piece in enumerate(chunk_text(doc.text, tokenizer, max_tokens, overlap)):
            metadata = {
                "source_id": doc.source_id,
                "doc_id": doc.doc_id,
                "method": doc.method,
                "region": doc.region,
                "event": doc.event,
                "url": doc.url,
                "title": doc.title,
                "published": doc.published,
                "language": doc.language,
                "publisher": doc.publisher,
                "chunk_index": i,
                "ingested_at": ingested_at,
            }
            # Chroma only accepts str/int/float/bool metadata values, so drop the unknowns.
            metadata = {k: v for k, v in metadata.items() if v is not None}
            chunks.append(Chunk(chunk_id=f"{doc.doc_id}:{i}", text=piece, metadata=metadata))
    return chunks
