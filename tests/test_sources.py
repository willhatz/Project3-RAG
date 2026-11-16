"""User Story 4: the sources shown with an answer."""

from chat.sources import (Answer, Source, build_context, build_sources, cited_numbers, select_sources,
                          strip_invalid_citations)


def _match(text, url, title="Report", **meta):
    return {"text": text, "metadata": {"url": url, "title": title, **meta}}


MATCHES = [
    _match("Deaths rose  to 643.\nMany are missing.", "https://dmc.example/1", "DMC situation report",
           publisher="dmc.gov.lk", published="2025-12-10", language="en", source_id="dmc"),
    _match("A second passage of the same report.", "https://dmc.example/1", "DMC situation report"),
    _match("Warnings were not issued in Tamil.", "https://tnh.example/a", "Lost in translation",
           publisher="The New Humanitarian", published="2025-12-18", language="en"),
]


def test_sources_are_numbered_one_per_document_with_metadata():
    sources = build_sources(MATCHES)
    assert [(s.number, s.title) for s in sources] == [(1, "DMC situation report"), (2, "Lost in translation")]
    first = sources[0]
    assert first.passage == "Deaths rose to 643. Many are missing."     # best-ranked chunk, whitespace tidied
    assert (first.publisher, first.published, first.language, first.source_id) == \
        ("dmc.gov.lk", "2025-12-10", "en", "dmc")
    assert first.language_name == "English"


def test_sources_are_capped_and_empty_chunks_skipped():
    matches = [_match("   ", "https://x.example/empty")]
    matches += [_match(f"text {i}", f"https://x.example/{i}") for i in range(8)]
    sources = build_sources(matches)
    assert [s.number for s in sources] == [1, 2, 3, 4, 5]
    assert sources[0].url == "https://x.example/0"


def test_missing_metadata_does_not_break_a_source():
    (source,) = build_sources([{"text": "Some text", "metadata": {"source_id": "manual"}}])
    assert (source.title, source.url, source.link, source.published) == ("Unknown", "", "", "")


def test_only_web_addresses_become_links():
    assert Source(1, "t", url="https://a.org/x").link == "https://a.org/x"
    assert Source(1, "t", url="file:///Users/me/data/manual/a.txt").link == ""
    assert Source(1, "t", url="javascript:alert(1)").link == ""


def test_context_numbers_match_source_numbers():
    context = build_context(build_sources(MATCHES))
    assert context.startswith("SOURCE [1]: DMC situation report\nDeaths rose to 643.")
    assert "SOURCE [2]: Lost in translation\nWarnings were not issued in Tamil." in context


def test_invalid_citation_numbers_are_removed():
    assert strip_invalid_citations("643 died [1]. Aid arrived [7][0].", 2) == "643 died [1]. Aid arrived ."
    assert cited_numbers("b [2], a [1], again [2], bogus [9]", 2) == [1, 2]


def test_only_cited_sources_are_shown_when_the_answer_cites():
    sources = build_sources(MATCHES)
    shown, cited = select_sources("Warnings were only in Sinhala and English [2].", sources)
    assert cited is True
    assert [(s.number, s.cited) for s in shown] == [(2, True)]


def test_uncited_answer_falls_back_to_top_retrieved_sources():
    sources = build_sources([_match(f"text {i}", f"https://x.example/{i}") for i in range(5)])
    shown, cited = select_sources("An answer with no markers.", sources)
    assert cited is False
    assert [(s.number, s.cited) for s in shown] == [(1, False), (2, False), (3, False)]


def test_answer_renders_sources_as_text_and_as_json():
    shown, cited = select_sources("643 people died [1].", build_sources(MATCHES))
    answer = Answer("643 people died [1].", shown, cited)
    assert answer.render() == (
        "643 people died [1].\n\nSources cited:\n"
        "[1] DMC situation report - dmc.gov.lk, 2025-12-10 - https://dmc.example/1"
    )
    assert answer.render(show_evidence=True).endswith("Evidence: Deaths rose to 643. Many are missing.")
    data = answer.to_dict()
    assert data["cited"] is True and data["sources"][0]["url"] == "https://dmc.example/1"
    assert Answer("Please enter a question.").render() == "Please enter a question."
