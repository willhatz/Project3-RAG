from ingest.clean import (clean_documents, clean_pdf_pages, clean_text, content_hash, detect_language,
                          html_to_text, normalize_language, normalize_text, strip_boilerplate_lines,
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


def test_normalize_removes_control_and_private_use_characters_and_unicode_spaces():
    assert normalize_text("a\x0cb\uf0e6c\ufffd") == "abc"
    assert normalize_text("1\u00a0200\u2009km\u3000east") == "1 200 km east"


def test_boilerplate_lines_are_dropped_but_sentences_are_kept():
    text = "Share\nShare on Bluesky\nRepublish article\n_______\n* * *\nShare this warning with your neighbours now."
    assert strip_boilerplate_lines(text) == "Share this warning with your neighbours now."
    assert strip_boilerplate_lines("Este artículo se publicó hace 2 años.\nLa DANA dejó 229 muertos.") == \
        "La DANA dejó 229 muertos."
    assert strip_boilerplate_lines("Name: ________ Date: . . . . . . .") == "Name: Date:"


def test_clean_text_is_idempotent():
    once = clean_text("Share\n\nFlood  warning\u200b issued.\n\n\n\n____\nMove to higher ground.")
    assert once == "Flood warning issued.\n\nMove to higher ground." and clean_text(once) == once


def _pdf_page(number, body):
    return f"Situation Report 2025.12.03\n{body}\nPage {number} / 4"


def test_pdf_page_numbers_and_running_headers_are_removed():
    pages = [_pdf_page(i, f"District {i} reported {i * 10} families affected.") for i in range(1, 5)]
    text = clean_pdf_pages(pages)
    assert "Page" not in text
    assert text.count("Situation Report 2025.12.03") == 1          # kept once, on the first page
    assert all(f"District {i} reported {i * 10} families affected." in text for i in range(1, 5))


def test_pdf_bare_page_numbers_removed_but_numbers_in_tables_kept():
    pages = [f"{i}\nColombo\n{i * 111}\nfamilies were moved to safety centres." for i in range(1, 5)]
    text = clean_pdf_pages(pages)
    assert [ln for ln in text.split("\n") if ln.isdigit()] == ["111", "222", "333", "444"]


def test_pdf_wrapped_lines_are_joined_into_paragraphs():
    wrapped = (
        "The cyclone brought exceptionally heavy rainfall, with several districts recording\n"
        "more than 200 mm within 24 hours. People are taking part in community decision-\n"
        "making about relocation.\n"
        "Key figures\n"
        "- 643 deaths\n"
        "- 2.2 million people affected\n"
    ) * 3
    text = clean_pdf_pages([wrapped])
    assert "districts recording more than 200 mm within 24 hours." in text
    assert "community decision-making about relocation." in text
    assert "Key figures\n- 643 deaths\n- 2.2 million people affected" in text   # short lines stay separate


def test_pdf_short_documents_and_empty_pages_are_left_alone():
    assert clean_pdf_pages(["1\nFlood warning", "", "   "]) == "1\nFlood warning"
    assert clean_pdf_pages([]) == ""


def test_language_codes_are_reduced_to_two_letters():
    assert normalize_language("es-ES") == "es" and normalize_language("ZH_cn") == "zh"
    assert normalize_language("") is None and normalize_language(None) is None
    kept, _ = clean_documents([_doc("Las ayudas se pueden pedir. " * 10, language="es-ES")], min_chars=50)
    assert kept[0].language == "es"


def test_pdf_table_rows_are_not_merged():
    prose = "Heavy rain continued across the island and several rivers reached major flood level today\n" * 6
    table = ("No. Districts Families Persons Deaths Missing Safety centers Families Persons in centers\n"
             "1 Puttalam 73,313 271,206 27 8 142 10,558 40,821 and more columns follow here\n"
             "2 Badulla 12,274 45,187 83 28 178 6,246 21,002 and more columns follow here\n")
    text = clean_pdf_pages([prose + table])
    assert "\n1 Puttalam 73,313" in text and "\n2 Badulla 12,274" in text
