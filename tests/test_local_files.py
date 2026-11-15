import pytest

from ingest import local_files
from ingest.config import Settings, Source
from ingest.errors import IngestSkipped


def _source(path, **extra):
    options = {"path": str(path), "title": "Lost in translation", "url": "https://example.org/article",
               "published": "2025-12-18", "language": "en", **extra}
    return Source(id="tnh", method="file", region="sri_lanka", event="cyclone_ditwah", options=options)


def test_reads_text_file_with_yaml_metadata(tmp_path):
    path = tmp_path / "article.txt"
    path.write_text("Tamil warnings arrived hours late.", encoding="utf-8")
    [doc] = local_files.fetch(_source(path), Settings())
    assert doc.text == "Tamil warnings arrived hours late."
    assert doc.url == "https://example.org/article"  # cites the original page, not the file
    assert doc.published == "2025-12-18" and doc.method == "file"


def test_missing_file_is_skipped_not_failed(tmp_path):
    with pytest.raises(IngestSkipped):
        local_files.fetch(_source(tmp_path / "nope.txt"), Settings())
