"""Ingestion method #2 (Story 6): polite web scraping of HTML pages and PDFs.

- Checks robots.txt before every request and honours Crawl-delay (minimum 2 s per site).
- HTML: main article text and metadata extracted with trafilatura (drops menus, ads, footers).
- PDF:  text extracted with pypdf; page numbers and running headers/footers removed, wrapped lines re-joined.
- ``follow_links`` in sources.yaml lets one entry pull in the pages/PDFs linked from an index page.
"""

from __future__ import annotations

import io
import json
import logging
import re
import time
from urllib import robotparser
from urllib.parse import urldefrag, urljoin, urlparse

import requests

from .clean import clean_pdf_pages
from .config import Settings, Source
from .errors import IngestError
from .models import Document, make_doc_id

log = logging.getLogger(__name__)

USER_AGENT = "DisasterInfoRAG/0.1 (university student project; non-commercial; low request rate)"
MIN_DELAY_SECONDS = 2.0


class PoliteFetcher:
    """requests wrapper that obeys robots.txt and rate-limits per domain."""

    def __init__(self, session: requests.Session | None = None, timeout: int = 30):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.timeout = timeout
        self._robots: dict[str, robotparser.RobotFileParser | None] = {}
        self._last_request: dict[str, float] = {}

    def _robots_for(self, url: str) -> robotparser.RobotFileParser | None:
        parts = urlparse(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._robots:
            parser = robotparser.RobotFileParser()
            try:
                resp = self.session.get(f"{base}/robots.txt", timeout=self.timeout)
                if resp.status_code >= 500:
                    parser.disallow_all = True            # server trouble: be conservative
                elif resp.ok:
                    parser.parse(resp.text.splitlines())
                else:
                    parser.allow_all = True               # 4xx: no robots.txt, everything allowed
            except requests.RequestException:
                parser.allow_all = True
            self._robots[base] = parser
        return self._robots[base]

    def allowed(self, url: str) -> bool:
        parser = self._robots_for(url)
        return parser is None or parser.can_fetch(USER_AGENT, url)

    def _wait(self, url: str) -> None:
        netloc = urlparse(url).netloc
        parser = self._robots_for(url)
        delay = MIN_DELAY_SECONDS
        crawl_delay = parser.crawl_delay(USER_AGENT) if parser else None
        if crawl_delay:
            delay = max(delay, float(crawl_delay))
        elapsed = time.monotonic() - self._last_request.get(netloc, 0.0)
        if elapsed < delay:
            time.sleep(delay - elapsed)
        self._last_request[netloc] = time.monotonic()

    def get(self, url: str) -> requests.Response:
        if not self.allowed(url):
            raise IngestError(f"robots.txt disallows {url}")
        self._wait(url)
        try:
            resp = self.session.get(url, timeout=self.timeout)
        except requests.RequestException as exc:
            raise IngestError(f"request failed for {url}: {exc}") from exc
        if not resp.ok:
            raise IngestError(f"HTTP {resp.status_code} for {url}")
        return resp


# --------------------------------------------------------------------------- extraction


def extract_html(html: str, url: str) -> dict:
    """Main text + metadata from an HTML page. Returns {} if no article text was found."""
    import trafilatura

    result = trafilatura.extract(
        html,
        url=url,
        output_format="json",
        with_metadata=True,
        include_comments=False,
        include_tables=True,
        favor_precision=True,
    )
    if not result:
        return {}
    data = json.loads(result)
    return {
        "title": data.get("title"),
        "text": data.get("text") or data.get("raw_text") or "",
        "published": (data.get("date") or "")[:10] or None,
        "language": data.get("language"),
        "publisher": data.get("sitename") or data.get("hostname"),
    }


def read_pdf(content: bytes) -> dict:
    """Text plus a best-guess title and date from a PDF.

    Title: the first two short lines of text (e.g. "Disaster Management Center - Situation Report on
    2025.12.03 at 0600 hrs"), falling back to the PDF's metadata title. Date: the PDF creation date.
    """
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    text = clean_pdf_pages([(page.extract_text() or "") for page in reader.pages])

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()][:2]
    title = " - ".join(ln for ln in lines if len(ln) <= 80) or None
    published = None
    try:
        meta = reader.metadata
        if meta is not None:
            title = title or (meta.title or None)
            if meta.creation_date:
                published = meta.creation_date.strftime("%Y-%m-%d")
    except Exception:  # malformed metadata is common and not worth failing over
        pass
    return {"text": text, "title": title, "published": published}


def extract_pdf(content: bytes) -> str:
    return read_pdf(content)["text"]


def find_links(html: str, base_url: str, pattern: str, limit: int) -> list[str]:
    """Absolute links on the page whose URL matches ``pattern`` (regex), in page order, de-duplicated."""
    from lxml import html as lxml_html

    tree = lxml_html.fromstring(html)
    regex = re.compile(pattern)
    found: list[str] = []
    for href in tree.xpath("//a/@href"):
        link = urldefrag(urljoin(base_url, href.strip()))[0]
        if regex.search(link) and link not in found and link != base_url:
            found.append(link)
        if len(found) >= limit:
            break
    return found


# --------------------------------------------------------------------------- ingester


def fetch(source: Source, settings: Settings, fetcher: PoliteFetcher | None = None) -> list[Document]:
    fetcher = fetcher or PoliteFetcher()
    opts = source.options
    targets: list[tuple[str, requests.Response | None]] = []

    start_url = opts.get("url")
    if start_url:
        start = fetcher.get(start_url)
        if opts.get("include_start_page", True):
            targets.append((start_url, start))
        follow = opts.get("follow_links")
        if follow:
            links = find_links(start.text, start_url, follow["pattern"], int(follow.get("max", 10)))
            log.info("%s: following %d linked page(s)", source.id, len(links))
            targets.extend((link, None) for link in links)

    # `urls:` — an explicit list of pages/PDFs, each fetched on its own.
    targets.extend((u, None) for u in opts.get("urls") or [] if u not in {t[0] for t in targets})

    docs: list[Document] = []
    for url, resp in targets:
        try:
            resp = resp or fetcher.get(url)
            doc = _to_document(url, resp, source)
        except IngestError as exc:
            log.warning("%s: skipped %s (%s)", source.id, url, exc)
            continue
        if doc:
            docs.append(doc)
        else:
            log.warning("%s: no readable text found at %s", source.id, url)

    if not docs:
        raise IngestError("no documents could be extracted")
    return docs


def _to_document(url: str, resp: requests.Response, source: Source) -> Document | None:
    content_type = resp.headers.get("Content-Type", "").lower()
    is_pdf = "application/pdf" in content_type or url.lower().endswith(".pdf")

    if is_pdf:
        try:
            meta = read_pdf(resp.content)
        except Exception as exc:  # pypdf raises many different error types on broken files
            raise IngestError(f"could not read PDF: {exc}") from exc
        text = meta["text"]
        meta["title"] = meta["title"] or urlparse(url).path.rsplit("/", 1)[-1]
        meta["publisher"] = urlparse(url).netloc
        meta["language"] = None
    else:
        meta = extract_html(resp.text, url)
        text = meta.get("text", "")

    if not text.strip():
        return None

    # Optional `title:` in sources.yaml overrides the extracted one (date appended when known).
    if source.options.get("title"):
        published = meta.get("published")
        meta["title"] = f"{source.options['title']} ({published})" if published else source.options["title"]

    return Document(
        doc_id=make_doc_id(url),
        source_id=source.id,
        method="scrape",
        region=source.region,
        event=source.event,
        url=url,
        title=(meta.get("title") or "").strip() or url,
        text=text,
        published=meta.get("published"),
        language=meta.get("language"),
        publisher=meta.get("publisher"),
    )
