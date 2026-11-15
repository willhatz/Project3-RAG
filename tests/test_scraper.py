from ingest import scraper
from ingest.errors import IngestError

ARTICLE_HTML = """
<html><head><title>DANA aid | Example</title></head>
<body>
  <nav><a href="/home">Home</a><a href="/va/ajudes-gva">Ajudes GVA</a>
       <a href="/va/ajudes-gva#top">Ajudes GVA again</a>
       <a href="https://other.org/va/ajudes-x">External</a>
       <a href="/docs/report.pdf">PDF</a></nav>
  <article>
    <h1>Help for families affected by the DANA</h1>
    <p>Families whose homes were damaged by the October 2024 floods can apply for direct aid.
       Applications are open until the end of the year at any local council office.</p>
    <p>Migrants without residency papers are also eligible for emergency support and should not
       be asked for documents they cannot provide. Bring proof of address if you have it.</p>
  </article>
  <footer>Cookie policy</footer>
</body></html>
"""


def test_find_links_resolves_filters_and_dedupes():
    links = scraper.find_links(ARTICLE_HTML, "https://recuperacio.gva.es/va/index", r"recuperacio\.gva\.es/va/ajudes-", 10)
    assert links == ["https://recuperacio.gva.es/va/ajudes-gva"]


def test_find_links_respects_limit():
    links = scraper.find_links(ARTICLE_HTML, "https://a.org/", r".", 2)
    assert len(links) == 2


def test_extract_html_gets_article_text():
    data = scraper.extract_html(ARTICLE_HTML, "https://a.org/dana")
    assert "apply for direct aid" in data["text"]
    assert "Cookie policy" not in data["text"]


class FakeResponse:
    def __init__(self, text="", status=200, content_type="text/html"):
        self.text, self.status_code = text, status
        self.ok = status < 400
        self.content = text.encode()
        self.headers = {"Content-Type": content_type}


class FakeSession:
    def __init__(self, pages):
        self.pages, self.headers, self.requested = pages, {}, []

    def get(self, url, timeout=None):
        self.requested.append(url)
        return self.pages.get(url, FakeResponse(status=404))


def test_robots_disallow_blocks_fetch(monkeypatch):
    monkeypatch.setattr(scraper, "MIN_DELAY_SECONDS", 0)
    session = FakeSession({"https://a.org/robots.txt": FakeResponse("User-agent: *\nDisallow: /private/")})
    fetcher = scraper.PoliteFetcher(session=session)
    assert not fetcher.allowed("https://a.org/private/page")
    assert fetcher.allowed("https://a.org/public/page")
    try:
        fetcher.get("https://a.org/private/page")
        raise AssertionError("expected IngestError")
    except IngestError:
        pass
    assert "https://a.org/private/page" not in session.requested


def test_fetch_builds_documents(monkeypatch, make_source):
    monkeypatch.setattr(scraper, "MIN_DELAY_SECONDS", 0)
    session = FakeSession({
        "https://a.org/robots.txt": FakeResponse(status=404),
        "https://a.org/dana": FakeResponse(ARTICLE_HTML),
    })
    docs = scraper.fetch(make_source(url="https://a.org/dana"), settings=None,
                         fetcher=scraper.PoliteFetcher(session=session))
    assert len(docs) == 1
    assert docs[0].method == "scrape" and docs[0].region == "valencia"
    assert "apply for direct aid" in docs[0].text


def test_fetch_urls_list_and_title_override(monkeypatch, make_source):
    monkeypatch.setattr(scraper, "MIN_DELAY_SECONDS", 0)
    session = FakeSession({
        "https://a.org/robots.txt": FakeResponse(status=404),
        "https://a.org/one": FakeResponse(ARTICLE_HTML),
        "https://a.org/two": FakeResponse(ARTICLE_HTML.replace("direct aid", "emergency aid")),
    })
    src = make_source(urls=["https://a.org/one", "https://a.org/two", "https://a.org/missing"], title="DMC report")
    docs = scraper.fetch(src, settings=None, fetcher=scraper.PoliteFetcher(session=session))
    assert [d.url for d in docs] == ["https://a.org/one", "https://a.org/two"]  # 404 skipped, not fatal
    assert all(d.title.startswith("DMC report") for d in docs)
