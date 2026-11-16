"""User Story 4: answers come back with the sources they were generated from (no Ollama, no model)."""

import pytest

from chat import answer as answer_module
from chat.answer import answer_question, generate_answer

MATCHES = [
    {"text": "As of 17 December the DMC reported 643 deaths from Cyclone Ditwah.",
     "metadata": {"url": "https://tnh.example/a", "title": "Lost in translation",
                  "publisher": "The New Humanitarian", "published": "2025-12-18", "language": "en"}},
    {"text": "Kandy recorded 118 deaths.",
     "metadata": {"url": "https://dmc.example/1", "title": "DMC situation report", "published": "2025-12-03"}},
]


@pytest.fixture
def fake_llm(monkeypatch):
    """Replaces retrieval and the Ollama call; returns the list of prompts the 'model' received."""
    prompts = []
    state = {"reply": "643 people died [1].", "matches": MATCHES}

    def ask(system, message):
        prompts.append((system, message))
        return state["reply"]

    monkeypatch.setattr(answer_module, "ask", ask)
    monkeypatch.setattr(answer_module, "retrieve", lambda question, event, limit: state["matches"])
    return prompts, state


def test_answer_carries_the_cited_source(fake_llm):
    prompts, _ = fake_llm
    result = generate_answer("How many people died in the cyclone?")
    assert result.text == "643 people died [1]." and result.cited is True
    (source,) = result.sources
    assert (source.number, source.title, source.url) == (1, "Lost in translation", "https://tnh.example/a")
    assert (source.publisher, source.published) == ("The New Humanitarian", "2025-12-18")
    assert "643 deaths" in source.passage
    # the model was shown the same numbered passages the user can inspect
    assert "SOURCE [1]: Lost in translation" in prompts[0][1] and "SOURCE [2]: DMC situation report" in prompts[0][1]


def test_model_written_bibliography_and_bogus_numbers_are_dropped(fake_llm):
    _, state = fake_llm
    state["reply"] = "643 died [1]. 118 in Kandy [2]. More [5].\nSources:\n[1] http://made-up.example"
    result = generate_answer("How many people died in the cyclone?")
    assert result.text == "643 died [1]. 118 in Kandy [2]. More ."
    assert [s.url for s in result.sources] == ["https://tnh.example/a", "https://dmc.example/1"]


def test_uncited_answer_still_shows_retrieved_sources_flagged_as_uncited(fake_llm):
    _, state = fake_llm
    state["reply"] = "The documents do not say."
    result = generate_answer("What happened during the flood?")
    assert result.cited is False and len(result.sources) == 2
    assert "Retrieved sources (not verified citations):" in result.render()


def test_no_documents_means_no_sources(fake_llm):
    _, state = fake_llm
    state["matches"] = []
    result = generate_answer("What happened during the flood?")
    assert (result.text, result.sources) == ("No relevant documents found.", [])


def test_command_line_text_lists_the_sources(fake_llm):
    text = answer_question("How many people died in the cyclone?", show_evidence=True)
    assert text.splitlines()[:3] == ["643 people died [1].", "", "Sources cited:"]
    assert "[1] Lost in translation - The New Humanitarian, 2025-12-18 - https://tnh.example/a" in text
    assert "Evidence: As of 17 December the DMC reported 643 deaths" in text


def test_validation_messages_have_no_sources(fake_llm):
    assert generate_answer("   ").sources == []
    assert generate_answer("flood?", event="nope").text == "Invalid disaster selected."
