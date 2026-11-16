"""User Story 4: the web page shows the sources under the answer."""

import os

import pytest

django = pytest.importorskip("django")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "webapp.settings")
django.setup()

from django.test import RequestFactory  # noqa: E402

from chat.sources import Answer, Source  # noqa: E402
from chatbot import views  # noqa: E402

SOURCES = [
    Source(1, "Lost in translation <b>", url="https://tnh.example/a", publisher="The New Humanitarian",
           published="2025-12-18", language="en", passage="The DMC reported 643 deaths.", cited=True),
    Source(2, "Hand-saved note", url="file:///data/manual/note.txt", language="ta", passage="Local text."),
]


def _post(monkeypatch, answer):
    monkeypatch.setattr(views, "generate_answer", lambda question, event: answer)
    request = RequestFactory().post("/", {"question": "How many died?", "event": "cyclone_ditwah"})
    return views.home(request).content.decode("utf-8")


def test_page_lists_sources_with_link_details_and_passage(monkeypatch):
    html = _post(monkeypatch, Answer("643 people died [1].", SOURCES, cited=True))
    assert "643 people died [1]." in html
    assert "Sources used for this answer" in html
    assert '<a href="https://tnh.example/a" target="_blank" rel="noopener noreferrer">' in html
    assert "The New Humanitarian · Published 2025-12-18 · Original language: English" in html
    assert "<blockquote>The DMC reported 643 deaths.</blockquote>" in html
    assert "Lost in translation &lt;b&gt;" in html                 # titles are escaped
    assert "file:///" not in html and "Hand-saved note" in html    # no link for local files
    assert "Original language: Tamil" in html


def test_page_warns_when_sources_were_retrieved_but_not_cited(monkeypatch):
    html = _post(monkeypatch, Answer("The documents do not say.", SOURCES[:1], cited=False))
    assert "Retrieved sources" in html and "did not cite a specific source" in html
    assert "Sources used for this answer" not in html


def test_page_has_no_sources_section_without_sources(monkeypatch):
    html = _post(monkeypatch, Answer("No relevant documents found."))
    assert "No relevant documents found." in html
    assert 'class="sources"' not in html


def test_page_survives_a_backend_failure(monkeypatch):
    def boom(question, event):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(views, "generate_answer", boom)
    request = RequestFactory().post("/", {"question": "How many died?", "event": "cyclone_ditwah"})
    html = views.home(request).content.decode("utf-8")
    assert "Unable to generate an answer" in html and 'class="sources"' not in html
