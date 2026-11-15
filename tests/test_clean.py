from ingest.clean import (clean_documents, content_hash, detect_language, html_to_text, normalize_text,
                          strip_markdown)
from ingest.models import Document


def _doc(text, url="https://example.org/a", language=None):
    return Document(doc_id=url, source_id="s", method="scrape", region="valencia", event="valencia_dana",
                    url=url, title="  Title  ", text=text, language=language)


def test_normalize_collapses_whitespace_and_blank_lines():
    assert normalize_text("a   b\t c\r\n\n\n\nd ") == "a b c\n\nd"


def test_normalize_keeps_zwj_needed_by_sinhala_but_drops_zero_width_space():
    sinhala = "ශ්‍රී"  # "Sri" with a zero-width joiner
    assert normalize_text(sinhala + "​") == sinhala


def test_strip_markdown():
    md = "## Heading\n**Bold** and [a link](https://x.org) ![img](i.png)\n* item"
    assert strip_markdown(md) == "Heading\nBold and a link \n- item"


def test_detect_language_by_script():
    assert detect_language("ශ්‍රී ලංකාවේ ගංවතුර අනතුරු ඇඟවීම") == "si"
    assert detect_language("இலங்கையில் வெள்ள எச்சரிக்கை") == "ta"
    assert detect_language("تحذير من الفيضانات في فالنسيا") == "ar"


def test_detect_language_latin():
    assert detect_language("Las familias afectadas por la DANA pueden solicitar ayudas del Gobierno.") == "es"


def test_clean_drops_short_and_duplicate_documents():
    long_text = "Flood warning for the Kalu Ganga basin. " * 10
    docs = [
        _doc(long_text, "https://a.org/1"),
        _doc(long_text.upper(), "https://a.org/2"),  # same text, different case -> duplicate
        _doc("too short", "https://a.org/3"),
    ]
    kept, stats = clean_documents(docs, min_chars=100)
    assert [d.url for d in kept] == ["https://a.org/1"]
    assert (stats.received, stats.kept, stats.duplicates, stats.too_short) == (3, 1, 1, 1)
    assert kept[0].title == "Title"
    assert kept[0].language == "en"


def test_clean_dedupes_across_batches_with_shared_hashes():
    text = "Shelter locations in Paiporta and Catarroja are listed below. " * 5
    seen = set()
    clean_documents([_doc(text, "https://a.org/1")], 50, seen)
    kept, stats = clean_documents([_doc(text, "https://b.org/1")], 50, seen)
    assert kept == [] and stats.duplicates == 1


def test_content_hash_ignores_case_and_spacing():
    assert content_hash("Hello   World") == content_hash("hello world")


def test_html_to_text_keeps_structure():
    html = "<p>First&nbsp;paragraph.</p><p>Second<br>line</p><ul><li>one</li><li>two</li></ul>"
    assert html_to_text(html) == "First paragraph.\n\nSecond\nline\n\n- one\n- two"
    assert html_to_text("") == ""
