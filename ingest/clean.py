"""Cleaning and preprocessing (Story 7) — runs on every document before chunking.

Steps: Unicode normalisation -> whitespace cleanup -> boilerplate-line removal -> language tagging
-> length filter -> de-duplication. PDFs get an extra pass first (``clean_pdf_pages``): page numbers and
running headers/footers are removed and hard-wrapped lines are joined back into paragraphs.
"""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, replace

from .models import Document

log = logging.getLogger(__name__)

# Invisible characters to delete. ZWJ (U+200D) and ZWNJ (U+200C) are deliberately KEPT:
# Sinhala and Tamil use them to form conjunct letters, so removing them corrupts words.
_INVISIBLE = dict.fromkeys(map(ord, "​⁠﻿­"), None)

# Unicode blocks for scripts langdetect can't tell apart reliably (it has no Sinhala model at all).
_SCRIPT_RANGES = {
    "si": (0x0D80, 0x0DFF),  # Sinhala
    "ta": (0x0B80, 0x0BFF),  # Tamil
    "ar": (0x0600, 0x06FF),  # Arabic
}


# Characters that carry no text: control codes (except \n and \t), the U+FFFD replacement character and
# private-use glyphs (icon fonts in PDFs).
_JUNK_CHARS = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\ufffd\ue000-\uf8ff]")
# Any horizontal whitespace, including no-break and other Unicode spaces.
_SPACES = re.compile(r"[^\S\n]+")
# Form-field / table-of-contents filler such as "______" or ". . . . . ."
_FILLER = re.compile(r"(?:_\s?){4,}|(?:\.\s?){5,}")

# Whole lines that are page furniture rather than content (matched case-insensitively against the full
# line, so a sentence that merely contains these words is never touched).
_BOILERPLATE_LINE = re.compile(
    r"""^(?:
        share | share\s+(?:on|via|this)\b.{0,30} | republish(?:\s+this)?\s+article
      | compartir | compartir\s+(?:en|por)\b.{0,30} | compartir\s+a\b.{0,30}
      | este\s+art[ií]culo\s+se\s+public[oó]\s+hace\b.{0,30}      # "published 2 years ago": goes stale
      | (?:read|leer|llegir)\s+(?:more|m[aá]s|m[eé]s) | click\s+here | advertisement | publicidad | publicitat
    )[\s.:…]*$""",
    re.I | re.X,
)


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text).translate(_INVISIBLE)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _JUNK_CHARS.sub("", text)
    lines = [_SPACES.sub(" ", line).strip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def strip_boilerplate_lines(text: str) -> str:
    """Drop share-button labels, filler rules and lines without a single letter or digit."""
    kept = []
    for line in text.split("\n"):
        line = _SPACES.sub(" ", _FILLER.sub(" ", line)).strip()
        if line and (_BOILERPLATE_LINE.match(line) or not any(ch.isalnum() for ch in line)):
            continue
        kept.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def clean_text(text: str) -> str:
    """Everything applied to a document body before it is chunked."""
    return strip_boilerplate_lines(normalize_text(text))


# --------------------------------------------------------------------------- PDF text

_PAGE_NUMBER = re.compile(r"^(?:page|p[aá]gina|p[aà]g\.?)?\s*#(?:\s*(?:/|of|de)\s*#)?$", re.I)
_SENTENCE_END = ".!?:;؟۔෴।"
_LIST_ITEM = re.compile(r"^(?:[•●▪■◦\-–—*]|\(?\d{1,3}[.)]|\(?[a-zA-Z][.)])\s")


def _furniture_key(line: str) -> str:
    """Line with every number replaced by '#', so "Page 3 / 29" and "Page 4 / 29" compare equal."""
    return re.sub(r"\d+", "#", line.casefold())


def clean_pdf_pages(pages: list[str]) -> str:
    """Text of a PDF's pages -> one clean text.

    - Removes page numbers and running headers/footers: a first or last line that repeats (numbers aside)
      on at least half of the pages. A repeated *text* header is kept once, where it first appears, because
      in tabular reports it is often the column header.
    - Joins hard-wrapped lines back into paragraphs (and re-joins words split by a line-end hyphen), so
      the chunker's sentence boundaries are real sentence ends instead of arbitrary line wraps.
    """
    page_lines = [normalize_text(p).split("\n") for p in pages]
    page_lines = [lines for lines in page_lines if any(lines)]

    threshold = max(3, (len(page_lines) + 1) // 2)
    for pos in (0, -1):
        keys = Counter(_furniture_key(lines[pos]) for lines in page_lines if lines and len(lines[pos]) <= 80)
        seen_once: set[str] = set()
        for lines in page_lines:
            if not lines or len(lines[pos]) > 80:
                continue
            key = _furniture_key(lines[pos])
            if keys[key] < threshold:
                continue
            if _PAGE_NUMBER.match(key) or key in seen_once:
                del lines[pos]
                while lines and not lines[pos]:      # blank line left behind next to the removed one
                    del lines[pos]
            else:
                seen_once.add(key)

    lengths = sorted(len(ln) for lines in page_lines for ln in lines if ln)
    width = lengths[int(len(lengths) * 0.9)] if len(lengths) >= 10 else 0
    return "\n\n".join(_unwrap(lines, width) for lines in page_lines if any(lines)).strip()


def _is_tabular(line: str) -> bool:
    """A table row: at least 40% of its words are numbers or '-' placeholders."""
    words = line.split()
    return len(words) >= 3 and sum(w == "-" or any(c.isdigit() for c in w) for w in words) >= 0.4 * len(words)


def _unwrap(lines: list[str], width: int) -> str:
    """Join a line to the next one when it was clearly cut by the page width, not by the author."""
    if width < 40:                                   # too little text to tell what a full line looks like
        return "\n".join(lines).strip()
    out: list[str] = []
    prev_tabular = False
    for line in lines:
        prev = out[-1] if out else ""
        tabular, was_tabular = _is_tabular(line), prev_tabular
        prev_tabular = tabular
        if tabular or was_tabular:                   # table rows stay one per line
            out.append(line)
            continue
        if prev and line and len(prev) >= 0.7 * width and not _LIST_ITEM.match(line):
            if len(prev) > 1 and prev[-1] == "-" and prev[-2].isalpha() and line[0].islower():
                out[-1] = prev + line                # "decision-\nmaking" -> "decision-making"
                continue
            if prev[-1] not in _SENTENCE_END:
                out[-1] = prev + " " + line
                continue
        out.append(line)
    return "\n".join(out).strip()


def strip_markdown(text: str) -> str:
    """Light Markdown -> plain text (used for .md files in data/manual/)."""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)               # images
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)            # links -> link text
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)       # headings
    text = re.sub(r"^\s*>\s?", "", text, flags=re.M)                # block quotes
    text = re.sub(r"^\s*[-*+]\s+", "- ", text, flags=re.M)          # bullets -> "- "
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text)                 # bold
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", text)  # italics
    text = re.sub(r"^\s*([-*_]\s*){3,}$", "", text, flags=re.M)     # horizontal rules
    return text


def html_to_text(html: str) -> str:
    """HTML fragment (e.g. an API's rich-text field) -> plain text, keeping paragraph and list breaks."""
    if not html or not html.strip():
        return ""
    from lxml import html as lxml_html

    html = re.sub(r"(?i)<br\s*/?>", "\n", html)
    html = re.sub(r"(?i)</(p|div|h[1-6]|tr|table|ul|ol)>", "\n\n", html)
    html = re.sub(r"(?i)<li[^>]*>", "\n- ", html)
    try:
        text = lxml_html.fromstring(f"<div>{html}</div>").text_content()
    except Exception:  # malformed markup: fall back to stripping tags
        text = re.sub(r"<[^>]+>", " ", html)
    return normalize_text(text)


def detect_language(text: str) -> str | None:
    """ISO 639-1 code. Script check first (Sinhala/Tamil/Arabic), then langdetect.

    Note: langdetect reports Valencian as "ca" (Catalan) — they are the same language code.
    """
    sample = text[:5000]
    letters = [ch for ch in sample if ch.isalpha()]
    if letters:
        for code, (lo, hi) in _SCRIPT_RANGES.items():
            share = sum(lo <= ord(ch) <= hi for ch in letters) / len(letters)
            if share > 0.3:
                return code
    try:
        from langdetect import DetectorFactory, detect

        DetectorFactory.seed = 0  # deterministic results
        return detect(sample)
    except Exception:  # langdetect raises on empty / symbol-only text
        return None


def normalize_language(code: str | None) -> str | None:
    """"es-ES" / "ES" / "zh-cn" -> "es" / "es" / "zh", so the language filter has one value per language."""
    code = re.split(r"[-_]", (code or "").strip().lower())[0]
    return code or None


def content_hash(text: str) -> str:
    """Hash of the text with case and whitespace ignored, to catch near-identical copies."""
    key = re.sub(r"\s+", " ", text.casefold()).strip()
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


@dataclass
class CleanStats:
    received: int = 0
    kept: int = 0
    too_short: int = 0
    duplicates: int = 0


def clean_documents(
    docs: list[Document], min_chars: int, seen_hashes: set[str] | None = None
) -> tuple[list[Document], CleanStats]:
    """Clean a batch of documents. Pass the same ``seen_hashes`` across sources to de-duplicate globally."""
    seen = seen_hashes if seen_hashes is not None else set()
    stats = CleanStats(received=len(docs))
    kept: list[Document] = []

    for doc in docs:
        text = clean_text(doc.text)
        if len(text) < min_chars:
            stats.too_short += 1
            log.debug("dropped (too short): %s", doc.url)
            continue

        digest = content_hash(text)
        if digest in seen:
            stats.duplicates += 1
            log.debug("dropped (duplicate): %s", doc.url)
            continue
        seen.add(digest)

        language = normalize_language(doc.language) or normalize_language(detect_language(text))
        kept.append(
            replace(
                doc,
                text=text,
                title=normalize_text(doc.title),
                language=language,
            )
        )

    stats.kept = len(kept)
    return kept, stats
