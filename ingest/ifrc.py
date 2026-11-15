"""Ingestion method #1 (Story 6): the IFRC GO API — public, no API key required.

Docs/browse: https://go.ifrc.org   API root: https://goadmin.ifrc.org/api/v2/

For one IFRC "emergency" (event) this produces:
  - the event summary (situation overview written by IFRC),
  - every field report attached to the event (dated updates with casualty/displacement figures),
  - optionally, the appeal documents (Emergency Appeal, DREF operation, operations updates — PDFs).

Find an event id by searching, e.g. https://goadmin.ifrc.org/api/v2/event/?search=Ditwah
"""

from __future__ import annotations

import logging
import time

import requests

from .clean import html_to_text
from .config import Settings, Source
from .errors import IngestError
from .models import Document, make_doc_id
from .scraper import USER_AGENT, extract_pdf

log = logging.getLogger(__name__)

API_ROOT = "https://goadmin.ifrc.org/api/v2"
PUBLIC_ROOT = "https://go.ifrc.org"
PUBLISHER = "IFRC GO (International Federation of Red Cross and Red Crescent Societies)"
REQUEST_DELAY_SECONDS = 1.0

# Field-report numbers worth stating explicitly in the text, so they can be retrieved and cited.
_FIGURES = [
    ("num_dead", "Dead"), ("num_missing", "Missing"), ("num_injured", "Injured"),
    ("num_affected", "Affected"), ("num_displaced", "Displaced"),
    ("gov_num_dead", "Dead (government figure)"), ("gov_num_missing", "Missing (government figure)"),
    ("gov_num_affected", "Affected (government figure)"), ("gov_num_displaced", "Displaced (government figure)"),
    ("other_num_dead", "Dead (other sources)"), ("other_num_missing", "Missing (other sources)"),
    ("other_num_affected", "Affected (other sources)"), ("other_num_displaced", "Displaced (other sources)"),
]


class _Client:
    def __init__(self, session: requests.Session | None = None):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self._last = 0.0

    def get(self, url: str, **params) -> requests.Response:
        wait = REQUEST_DELAY_SECONDS - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        try:
            resp = self.session.get(url, params=params or None, timeout=60)
        except requests.RequestException as exc:
            raise IngestError(f"IFRC GO request failed: {exc}") from exc
        if not resp.ok:
            raise IngestError(f"IFRC GO returned HTTP {resp.status_code} for {resp.url}")
        return resp


def fetch(source: Source, settings: Settings, session: requests.Session | None = None) -> list[Document]:
    client = _Client(session)
    opts = source.options
    event_id = int(opts["event_id"])

    event = client.get(f"{API_ROOT}/event/{event_id}/").json()
    docs = parse_event(event, source)

    max_docs = int(opts.get("appeal_documents", 0))
    if max_docs > 0:
        for appeal in event.get("appeals") or []:
            docs.extend(_appeal_documents(client, appeal, source, max_docs))

    log.info("%s: %d document(s) from IFRC event %d", source.id, len(docs), event_id)
    if not docs:
        raise IngestError(f"IFRC event {event_id} had no text content")
    return docs


def parse_event(event: dict, source: Source) -> list[Document]:
    """Event summary + embedded field reports -> Documents (no network access; unit-testable)."""
    event_id = event["id"]
    name = (event.get("name") or f"IFRC event {event_id}").strip()
    event_url = f"{PUBLIC_ROOT}/emergencies/{event_id}"
    docs: list[Document] = []

    summary = html_to_text(event.get("summary") or "")
    if summary:
        docs.append(_doc(
            source, url=event_url, title=f"{name} - IFRC emergency overview", text=summary,
            published=_date(event.get("updated_at") or event.get("created_at")),
        ))

    for report in event.get("field_reports") or []:
        parts = [
            html_to_text(report.get("summary") or ""),
            _figures_line(report),
            html_to_text(report.get("description") or ""),
        ]
        text = "\n\n".join(p for p in parts if p)
        if not text:
            continue
        report_date = _date(report.get("report_date") or report.get("created_at"))
        docs.append(_doc(
            source,
            url=f"{PUBLIC_ROOT}/field-reports/{report['id']}",
            title=f"{name} - IFRC field report {report_date or report['id']}",
            text=text,
            published=report_date,
        ))
    return docs


def _appeal_documents(client: _Client, appeal: dict, source: Source, max_docs: int) -> list[Document]:
    results = client.get(f"{API_ROOT}/appeal_document/", appeal=appeal["id"], limit=50).json()
    # Guard: only keep documents that really belong to this appeal.
    items = [d for d in results.get("results", []) if (d.get("appeal") or {}).get("id") == appeal["id"]]
    items.sort(key=lambda d: d.get("created_at") or "", reverse=True)

    docs: list[Document] = []
    for item in items[:max_docs]:
        url = item.get("document_url") or item.get("document")
        if not url:
            continue
        try:
            resp = client.get(url)
            text = extract_pdf(resp.content)
        except IngestError as exc:
            log.warning("%s: skipped appeal document %s (%s)", source.id, url, exc)
            continue
        except Exception as exc:  # not a readable PDF
            log.warning("%s: could not read appeal document %s (%s)", source.id, url, exc)
            continue
        if not text.strip():
            continue
        doc_type = item.get("type") or "Appeal document"
        docs.append(_doc(
            source, url=url, text=text,
            title=f"{(item.get('name') or appeal.get('code') or '').strip()} - {doc_type}",
            published=_date(item.get("created_at")),
        ))
    return docs


def _figures_line(report: dict) -> str:
    figures = [f"{label}: {report[key]:,}" for key, label in _FIGURES if report.get(key)]
    return ("Reported figures - " + "; ".join(figures)) if figures else ""


def _date(value: str | None) -> str | None:
    return value[:10] if value else None


def _doc(source: Source, *, url: str, title: str, text: str, published: str | None) -> Document:
    return Document(
        doc_id=make_doc_id(url),
        source_id=source.id,
        method="ifrc_go",
        region=source.region,
        event=source.event,
        url=url,
        title=title,
        text=text,
        published=published,
        language="en",
        publisher=PUBLISHER,
    )
