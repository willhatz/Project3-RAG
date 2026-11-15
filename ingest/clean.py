"""Cleaning and preprocessing (Story 7) — runs on every document before chunking.

Steps: Unicode normalisation -> whitespace cleanup -> language tagging -> length filter -> de-duplication.
Extend this module (e.g. boilerplate-line removal) as Story 7 grows.
"""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
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


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text).translate(_INVISIBLE)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


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
        text = normalize_text(doc.text)
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

        language = doc.language or detect_language(text)
        kept.append(
            replace(
                doc,
                text=text,
                title=normalize_text(doc.title),
                language=(language or "").lower() or None,
            )
        )

    stats.kept = len(kept)
    return kept, stats
