import json

from ingest import pipeline
from ingest.models import Document

TEXT = "Shelter locations in Paiporta and Catarroja are listed below. " * 5

SOURCES_YAML = """
settings: {min_chars: 50}
sources:
  - {id: first, method: file, region: valencia, event: valencia_dana, path: a.txt, title: A}
  - {id: second, method: file, region: valencia, event: valencia_dana, path: b.txt, title: B}
"""


def _fake_fetch(source, settings):
    return [Document(doc_id=source.id, source_id=source.id, method="file", region=source.region,
                     event=source.event, url=f"https://example.org/{source.id}", title=source.id, text=TEXT)]


def _setup(tmp_path, monkeypatch):
    sources = tmp_path / "sources.yaml"
    sources.write_text(SOURCES_YAML, encoding="utf-8")
    monkeypatch.setitem(pipeline.INGESTERS, "file", _fake_fetch)
    real_load = pipeline.load_config

    def load(path):
        settings, srcs = real_load(path)
        settings.processed_dir = tmp_path / "processed"
        return settings, srcs

    monkeypatch.setattr(pipeline, "load_config", load)
    return sources


def test_full_run_dedupes_across_sources_and_writes_processed_files(tmp_path, monkeypatch):
    sources = _setup(tmp_path, monkeypatch)
    first, second = pipeline.run(sources, dry_run=True)
    assert (first.status, first.kept) == ("ok", 1)
    assert (second.status, second.duplicates) == ("empty", 1)
    saved = json.loads((tmp_path / "processed" / "first.jsonl").read_text(encoding="utf-8"))
    assert saved["language"] == "en" and saved["text"].startswith("Shelter locations")


def test_single_source_run_still_dedupes_against_other_sources(tmp_path, monkeypatch):
    sources = _setup(tmp_path, monkeypatch)
    pipeline.run(sources, only=["first"], dry_run=True)
    (report,) = pipeline.run(sources, only=["second"], dry_run=True)
    assert report.duplicates == 1 and report.kept == 0
    # refreshing a source never counts its own previous copy as a duplicate
    (report,) = pipeline.run(sources, only=["first"], dry_run=True)
    assert report.kept == 1
