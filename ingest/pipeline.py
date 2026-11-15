"""Runs the full pipeline: fetch -> clean -> save processed JSONL -> chunk -> embed -> store."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from . import ifrc, local_files, scraper
from .chunk import chunk_documents
from .clean import clean_documents
from .config import DEFAULT_SOURCES_PATH, Settings, Source, load_config
from .errors import IngestError, IngestSkipped
from .models import Document

log = logging.getLogger(__name__)

INGESTERS = {
    "ifrc_go": ifrc.fetch,
    "file": local_files.fetch,
    "scrape": scraper.fetch,
}


@dataclass
class SourceReport:
    source_id: str
    status: str            # "ok" | "skipped" | "failed" | "empty"
    fetched: int = 0
    kept: int = 0
    duplicates: int = 0
    too_short: int = 0
    chunks: int = 0
    message: str = ""


def run(
    sources_path: Path | str = DEFAULT_SOURCES_PATH,
    only: list[str] | None = None,
    rebuild: bool = False,
    dry_run: bool = False,
) -> list[SourceReport]:
    settings, sources = load_config(sources_path)
    enabled = [s for s in sources if s.enabled]

    if only:
        unknown = set(only) - {s.id for s in sources}
        if unknown:
            raise ValueError(f"unknown source id(s): {', '.join(sorted(unknown))}")
        selected = [s for s in enabled if s.id in only]
        for sid in set(only) - {s.id for s in selected}:
            log.warning("%s is disabled in sources.yaml - skipping", sid)
    else:
        selected = enabled

    store = embedder = None
    if not dry_run:
        from .store import Embedder, VectorStore

        embedder = Embedder(settings.embed_model)
        store = VectorStore(settings.chroma_path, settings.collection, embedder)
        if rebuild:
            log.info("Rebuild requested: clearing the knowledge base")
            store.reset()

    seen_hashes: set[str] = set()
    reports = [_ingest_source(src, settings, seen_hashes, store, embedder) for src in selected]

    # A full run also removes sources that were disabled or deleted from sources.yaml.
    if store is not None and not only:
        removed = store.prune({s.id for s in enabled})
        if removed:
            log.info("Removed chunks from sources no longer in sources.yaml: %s", ", ".join(removed))

    return reports


def _ingest_source(source: Source, settings: Settings, seen_hashes, store, embedder) -> SourceReport:
    log.info("== %s (%s)", source.id, source.method)
    try:
        raw_docs = INGESTERS[source.method](source, settings)
    except IngestSkipped as exc:
        log.warning("%s skipped: %s", source.id, exc)
        return SourceReport(source.id, "skipped", message=str(exc))
    except IngestError as exc:
        log.error("%s failed: %s (existing chunks left untouched)", source.id, exc)
        return SourceReport(source.id, "failed", message=str(exc))

    docs, stats = clean_documents(raw_docs, settings.min_chars, seen_hashes)
    report = SourceReport(
        source.id, "ok", fetched=stats.received, kept=stats.kept,
        duplicates=stats.duplicates, too_short=stats.too_short,
    )
    _write_processed(settings.processed_dir, source.id, docs)

    if not docs:
        report.status = "empty"
        report.message = "nothing left after cleaning (existing chunks left untouched)"
        return report

    if store is not None:
        chunks = chunk_documents(docs, embedder.tokenizer, settings.chunk_tokens, settings.chunk_overlap)
        store.replace_source(source.id, chunks)
        report.chunks = len(chunks)
    return report


def _write_processed(directory: Path, source_id: str, docs: list[Document]) -> None:
    """Saves cleaned documents as JSONL so teammates can inspect exactly what went in."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{source_id}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for doc in docs:
            f.write(json.dumps(doc.to_dict(), ensure_ascii=False) + "\n")
