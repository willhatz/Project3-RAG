import pytest

from ingest.config import DEFAULT_SOURCES_PATH, ConfigError, load_config


def _write(tmp_path, body):
    path = tmp_path / "sources.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_project_sources_yaml_is_valid():
    settings, sources = load_config(DEFAULT_SOURCES_PATH)
    assert settings.chunk_tokens > settings.chunk_overlap
    methods = {s.method for s in sources if s.enabled}
    assert {"ifrc_go", "scrape"} <= methods, "Story 6 needs two distinct ingestion methods enabled"


def test_duplicate_ids_rejected(tmp_path):
    body = """
sources:
  - {id: a, method: scrape, region: valencia, event: valencia_dana, url: "https://x.org"}
  - {id: a, method: scrape, region: valencia, event: valencia_dana, url: "https://y.org"}
"""
    with pytest.raises(ConfigError, match="duplicate"):
        load_config(_write(tmp_path, body))


def test_method_specific_keys_required(tmp_path):
    body = "sources:\n  - {id: a, method: ifrc_go, region: sri_lanka, event: cyclone_ditwah}\n"
    with pytest.raises(ConfigError, match="requires 'event_id'"):
        load_config(_write(tmp_path, body))


def test_invalid_region_rejected(tmp_path):
    body = "sources:\n  - {id: a, method: scrape, region: mars, event: valencia_dana, url: x}\n"
    with pytest.raises(ConfigError, match="region"):
        load_config(_write(tmp_path, body))


def test_scrape_needs_url_or_urls(tmp_path):
    body = "sources:\n  - {id: a, method: scrape, region: valencia, event: valencia_dana}\n"
    with pytest.raises(ConfigError, match="'url' or 'urls'"):
        load_config(_write(tmp_path, body))
