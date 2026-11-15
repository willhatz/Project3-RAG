import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.config import Source  # noqa: E402


class WhitespaceTokenizer:
    """Stand-in for the bge-m3 tokenizer: one token per whitespace-separated word."""

    def __call__(self, text, add_special_tokens=False, return_offsets_mapping=True):
        return {"offset_mapping": [m.span() for m in re.finditer(r"\S+", text)]}


@pytest.fixture
def tokenizer():
    return WhitespaceTokenizer()


@pytest.fixture
def make_source():
    def _make(method="scrape", **options):
        return Source(id="test_src", method=method, region="valencia", event="valencia_dana", options=options)

    return _make
