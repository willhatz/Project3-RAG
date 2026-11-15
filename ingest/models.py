"""Data shapes shared by every stage of the pipeline."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass


def make_doc_id(url: str) -> str:
    """Stable id for a document, so re-ingesting the same URL updates it instead of duplicating it."""
    return hashlib.sha1(url.strip().encode("utf-8")).hexdigest()[:16]


@dataclass
class Document:
    """One article, report or page, before chunking."""

    doc_id: str
    source_id: str      # which sources.yaml entry produced it
    method: str         # "ifrc_go" | "scrape" | "file"
    region: str         # "sri_lanka" | "valencia"
    event: str          # "cyclone_ditwah" | "valencia_dana" | "general"
    url: str
    title: str
    text: str
    published: str | None = None   # ISO date YYYY-MM-DD, when known
    language: str | None = None    # ISO 639-1 code, e.g. "ta", "si", "es", "ca"
    publisher: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Chunk:
    """A piece of a document small enough to embed and retrieve."""

    chunk_id: str
    text: str
    metadata: dict
