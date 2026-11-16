"""Sources behind an answer (User Story 4).

Every answer carries the documents it was generated from, so the end user can open the original
page and check the claim. A ``Source`` is one document: its citation number (the ``[1]`` used in
the answer text), title, publisher, date, link and the exact passage the model was given.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, replace

MAX_SOURCES = 5
MAX_PASSAGE_CHARS = 1100

LANGUAGE_NAMES = {
    "en": "English", "es": "Spanish", "ca": "Valencian/Catalan", "ta": "Tamil", "si": "Sinhala",
}

_CITATION = re.compile(r"\[(\d+)\]")


@dataclass(frozen=True)
class Source:
    number: int                 # the [n] used in the answer text
    title: str
    url: str = ""
    publisher: str = ""
    published: str = ""         # ISO date, when known
    language: str = ""          # ISO 639-1 code of the source document
    source_id: str = ""         # sources.yaml entry it came from
    passage: str = ""           # the text that was given to the model
    cited: bool = False         # True when the answer text refers to this source

    @property
    def link(self) -> str:
        """URL safe to render as a hyperlink (hand-saved files without a web address have none)."""
        return self.url if self.url.startswith(("http://", "https://")) else ""

    @property
    def language_name(self) -> str:
        return LANGUAGE_NAMES.get(self.language, self.language)

    def to_dict(self) -> dict:
        return asdict(self)

    def describe(self) -> str:
        """One line for plain-text output: ``[1] Title - Publisher, 2025-12-18 - https://...``"""
        details = ", ".join(part for part in (self.publisher, self.published) if part)
        return " - ".join(part for part in (f"[{self.number}] {self.title}", details, self.url) if part)


@dataclass
class Answer:
    text: str
    sources: list[Source] = field(default_factory=list)   # the sources to show with the answer
    cited: bool = False                                    # False: sources were retrieved but not cited

    @property
    def sources_label(self) -> str:
        return "Sources cited:" if self.cited else "Retrieved sources (not verified citations):"

    def to_dict(self) -> dict:
        return {"text": self.text, "cited": self.cited, "sources": [s.to_dict() for s in self.sources]}

    def render(self, show_evidence: bool = False) -> str:
        """Plain-text form used by the command line."""
        if not self.sources:
            return self.text
        lines = [self.text, "", self.sources_label]
        for source in self.sources:
            lines.append(source.describe())
            if show_evidence:
                lines.append("Evidence: " + source.passage)
        return "\n".join(lines)


def build_sources(matches: list[dict], max_sources: int = MAX_SOURCES) -> list[Source]:
    """Retrieved chunks -> numbered sources, one per document, best match first.

    Several chunks of the same document count as one source; its passage is the best-ranked chunk.
    """
    sources: dict[str, Source] = {}
    for match in matches:
        meta = match.get("metadata") or {}
        passage = " ".join((match.get("text") or "").split())[:MAX_PASSAGE_CHARS]
        key = meta.get("url") or meta.get("doc_id") or meta.get("source_id") or meta.get("title")
        if not passage or key in sources or len(sources) >= max_sources:
            continue
        sources[key] = Source(
            number=len(sources) + 1,
            title=str(meta.get("title") or "Unknown"),
            url=str(meta.get("url") or ""),
            publisher=str(meta.get("publisher") or ""),
            published=str(meta.get("published") or ""),
            language=str(meta.get("language") or ""),
            source_id=str(meta.get("source_id") or ""),
            passage=passage,
        )
    return list(sources.values())


def build_context(sources: list[Source]) -> str:
    """The numbered documents handed to the model; the numbers are what it cites."""
    return "\n\n".join(f"SOURCE [{s.number}]: {s.title}\n{s.passage}" for s in sources)


def strip_invalid_citations(text: str, count: int) -> str:
    """Remove ``[n]`` markers that do not correspond to one of the ``count`` supplied sources."""
    return _CITATION.sub(lambda m: m.group() if 1 <= int(m.group(1)) <= count else "", text)


def cited_numbers(text: str, count: int) -> list[int]:
    return sorted({int(n) for n in _CITATION.findall(text) if 1 <= int(n) <= count})


def select_sources(text: str, sources: list[Source], fallback: int = 3) -> tuple[list[Source], bool]:
    """The sources to show with an answer, and whether the answer actually cites them.

    Cited sources are shown when there are any. If the model cited nothing, the top retrieved
    sources are shown instead, flagged as not cited, so the user is never left without a way to check.
    """
    numbers = cited_numbers(text, len(sources))
    if numbers:
        return [replace(sources[n - 1], cited=True) for n in numbers], True
    return sources[:fallback], False
