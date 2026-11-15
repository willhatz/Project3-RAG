"""Ingestion method #3: local files saved by hand (.txt, .md, .html, .pdf).

For sources that block automated access (e.g. The New Humanitarian returns HTTP 403 to scripts).
A teammate saves the content into data/manual/ and records the original URL, title and date in
sources.yaml, so the chatbot can still cite the real source.
"""

from __future__ import annotations

from pathlib import Path

from .clean import strip_markdown
from .config import ROOT, Settings, Source
from .errors import IngestError, IngestSkipped
from .models import Document, make_doc_id
from .scraper import extract_html, extract_pdf


def fetch(source: Source, settings: Settings) -> list[Document]:
    opts = source.options
    path = Path(opts["path"])
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        raise IngestSkipped(f"file not found: {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}"
                            " - save the content there first")

    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            text = extract_pdf(path.read_bytes())
        elif suffix in {".html", ".htm"}:
            text = extract_html(path.read_text(encoding="utf-8"), opts.get("url", "")).get("text", "")
        elif suffix == ".md":
            text = strip_markdown(path.read_text(encoding="utf-8"))
        else:
            text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise IngestError(f"could not read {path}: {exc}") from exc

    url = opts.get("url") or path.as_uri()
    return [Document(
        doc_id=make_doc_id(url),
        source_id=source.id,
        method="file",
        region=source.region,
        event=source.event,
        url=url,
        title=str(opts["title"]),
        text=text,
        published=str(opts["published"]) if opts.get("published") else None,
        language=opts.get("language"),
        publisher=opts.get("publisher"),
    )]
