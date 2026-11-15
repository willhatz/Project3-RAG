# Multilingual Flood-Information RAG Chatbot

A retrieval-augmented chatbot that answers questions about flood emergencies in **Sri Lanka (Cyclone Ditwah)**
and **Valencia (2024 DANA)** in the user's own language, using only official and verified sources, and showing
those sources with every answer.

This repository currently contains the **knowledge-base pipeline** (Sprint 1, stories 5–7).

```
fetch (IFRC GO API / web scraping / local files) -> clean -> save data/processed/*.jsonl -> chunk -> embed (bge-m3) -> Chroma
```

## Setup

Requires Python 3.10+.

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate      macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # optional: only to override defaults
```

No API keys are required: the IFRC GO API is public.

**Embedding model:** the first non-dry run downloads `BAAI/bge-m3` (~2.3 GB) into the Hugging Face cache.

## Usage

| Command | What it does |
|---|---|
| `python -m ingest` | Ingest every enabled source; prune chunks from sources removed/disabled in `sources.yaml` |
| `python -m ingest --source gva_dana_aid` | Ingest/refresh one source (repeatable) |
| `python -m ingest --dry-run` | Fetch + clean only; inspect results in `data/processed/<source>.jsonl` |
| `python -m ingest --rebuild` | Wipe the knowledge base and rebuild it from scratch |
| `python -m ingest --list` | Show configured sources and how many chunks each has stored |
| `pytest` | Run the tests (no network or model download needed) |

The command exits with code 1 if any source failed, so it can be used in CI later.

## Defining the dataset (Story 5)

Everything the chatbot knows is listed in [`sources.yaml`](sources.yaml). Each entry has an `id`, a `method`
(`ifrc_go` | `scrape` | `file`), a `region` (`sri_lanka` | `valencia`) and an `event`
(`cyclone_ditwah` | `valencia_dana` | `general`).

- **Add** a source: add an entry, run `python -m ingest --source <id>`.
- **Update** a source: re-run the same command. Its old chunks are replaced, never duplicated.
- **Remove** a source: set `enabled: false` (or delete it) and run `python -m ingest`.
- If a source fails to fetch, its previously stored chunks are left in place rather than deleted.

## Ingestion methods (Story 6)

| Method | Module | Sources |
|---|---|---|
| **API**: IFRC GO (no key) | `ingest/ifrc.py` | IFRC emergency overview, dated field reports (with casualty and displacement figures) and appeal PDFs for Cyclone Ditwah (event 7713) and the Valencia DANA (event 7200) |
| **Web scraping**: HTML + PDF | `ingest/scraper.py` | DMC Sri Lanka situation-report PDFs (25 Nov–10 Dec 2025), DMC Early Warning page in Tamil, Público article, Generalitat Valenciana DANA aid pages (`follow_links` crawls the sub-pages) |
| **Local files** | `ingest/local_files.py` | Content saved by hand in `data/manual/` for sites that block scripts (The New Humanitarian article) |

The scraper checks `robots.txt` before each request, honours `Crawl-delay` (at least 2 s per site), and
identifies itself as a non-commercial student project.

## Cleaning and preprocessing (Story 7)

`ingest/clean.py` and `ingest/chunk.py`:

- Unicode NFC normalisation; removes invisible characters but **keeps ZWJ/ZWNJ** (Sinhala and Tamil need them)
- HTML/Markdown stripping for API text fields and `.md` files; trafilatura removes menus, ads and footers from web pages
- Language tagging: script detection for Sinhala/Tamil/Arabic, `langdetect` for the rest
  (Valencian is tagged `ca`, the shared ISO code for Catalan/Valencian)
- Drops documents under `min_chars` and exact/near-exact duplicates across all sources
- ~500-token chunks with 50-token overlap, counted with the bge-m3 tokenizer, ending on sentence boundaries
- Metadata on every chunk: `source_id, url, title, published, language, publisher, region, event, method, chunk_index, ingested_at`

## Using the knowledge base from the chat backend (Story 2)

```python
from ingest.config import load_config
from ingest.store import Embedder, VectorStore

settings, _ = load_config()
embedder = Embedder(settings.embed_model)
store = VectorStore(settings.chroma_path, settings.collection, embedder)

results = store.collection.query(
    query_embeddings=embedder.embed(["¿Qué ayudas hay para familias afectadas por la DANA?"]),
    n_results=5,
)
# results["documents"][0] -> chunk texts, results["metadatas"][0] -> title/url/published/... for citations
```

## Project layout

```
sources.yaml          dataset definition (Story 5)
ingest/
  config.py           loads + validates sources.yaml and .env
  ifrc.py             ingestion method 1: IFRC GO API
  scraper.py          ingestion method 2: polite web scraping (HTML/PDF)
  local_files.py      ingestion method 3: files saved by hand in data/manual/
  clean.py            normalisation, language tagging, de-duplication
  chunk.py            token-based chunking with overlap
  store.py            bge-m3 embedder + Chroma vector store
  pipeline.py         runs the stages for each source
  __main__.py         CLI (python -m ingest)
tests/                unit tests (offline)
data/manual/          hand-saved source files (committed)
data/processed/       cleaned documents as JSONL (generated, git-ignored)
data/chroma/          vector database (generated, git-ignored)
```
