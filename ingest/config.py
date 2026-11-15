"""Loads sources.yaml (Story 5) and environment settings."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCES_PATH = ROOT / "sources.yaml"

load_dotenv(ROOT / ".env")

VALID_METHODS = {"ifrc_go", "scrape", "file"}
VALID_REGIONS = {"sri_lanka", "valencia"}
VALID_EVENTS = {"cyclone_ditwah", "valencia_dana", "general"}  # general = evergreen preparedness info
REQUIRED_KEYS = ("id", "method", "region", "event")
METHOD_REQUIRED_KEYS = {
    "ifrc_go": ("event_id",),
    "scrape": (),            # needs url and/or urls, checked below
    "file": ("path", "title"),
}


class ConfigError(ValueError):
    """sources.yaml is missing something or has an invalid value."""


@dataclass
class Source:
    id: str
    method: str
    region: str
    event: str
    enabled: bool = True
    description: str = ""
    options: dict = field(default_factory=dict)  # every other key from the yaml entry


@dataclass
class Settings:
    chunk_tokens: int = 500
    chunk_overlap: int = 50
    min_chars: int = 200
    embed_model: str = "BAAI/bge-m3"
    chroma_path: Path = ROOT / "data" / "chroma"
    collection: str = "disaster_docs"
    processed_dir: Path = ROOT / "data" / "processed"


def _resolve(path_str: str) -> Path:
    path = Path(path_str)
    return path if path.is_absolute() else ROOT / path


def load_config(path: Path | str = DEFAULT_SOURCES_PATH) -> tuple[Settings, list[Source]]:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"{path} not found")

    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    yaml_settings = raw.get("settings") or {}
    settings = Settings(
        chunk_tokens=int(yaml_settings.get("chunk_tokens", 500)),
        chunk_overlap=int(yaml_settings.get("chunk_overlap", 50)),
        min_chars=int(yaml_settings.get("min_chars", 200)),
        embed_model=os.getenv("EMBED_MODEL") or "BAAI/bge-m3",
        chroma_path=_resolve(os.getenv("CHROMA_PATH") or "data/chroma"),
        collection=os.getenv("CHROMA_COLLECTION") or "disaster_docs",
    )
    if settings.chunk_overlap >= settings.chunk_tokens:
        raise ConfigError("chunk_overlap must be smaller than chunk_tokens")

    sources = [_parse_source(entry, i) for i, entry in enumerate(raw.get("sources") or [])]

    seen: set[str] = set()
    for src in sources:
        if src.id in seen:
            raise ConfigError(f"duplicate source id '{src.id}'")
        seen.add(src.id)

    return settings, sources


def _parse_source(entry: dict, index: int) -> Source:
    if not isinstance(entry, dict):
        raise ConfigError(f"source #{index + 1} is not a mapping")

    missing = [k for k in REQUIRED_KEYS if not entry.get(k)]
    if missing:
        label = entry.get("id", f"#{index + 1}")
        raise ConfigError(f"source {label} is missing: {', '.join(missing)}")

    src_id, method = str(entry["id"]), entry["method"]
    if method not in VALID_METHODS:
        raise ConfigError(f"source {src_id}: method must be one of {sorted(VALID_METHODS)}")
    if entry["region"] not in VALID_REGIONS:
        raise ConfigError(f"source {src_id}: region must be one of {sorted(VALID_REGIONS)}")
    if entry["event"] not in VALID_EVENTS:
        raise ConfigError(f"source {src_id}: event must be one of {sorted(VALID_EVENTS)}")
    for key in METHOD_REQUIRED_KEYS[method]:
        if not entry.get(key):
            raise ConfigError(f"source {src_id}: method '{method}' requires '{key}'")
    if method == "scrape" and not (entry.get("url") or entry.get("urls")):
        raise ConfigError(f"source {src_id}: method 'scrape' requires 'url' or 'urls'")

    known = {"id", "method", "region", "event", "enabled", "description"}
    return Source(
        id=src_id,
        method=method,
        region=entry["region"],
        event=entry["event"],
        enabled=bool(entry.get("enabled", True)),
        description=str(entry.get("description", "")),
        options={k: v for k, v in entry.items() if k not in known},
    )
