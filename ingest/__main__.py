"""Command line entry point:  python -m ingest --help"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import DEFAULT_SOURCES_PATH, ConfigError, load_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ingest",
        description="Build or update the chatbot's knowledge base from sources.yaml.",
    )
    parser.add_argument("--sources", default=str(DEFAULT_SOURCES_PATH), help="path to sources.yaml")
    parser.add_argument("--source", action="append", metavar="ID",
                        help="only ingest this source id (repeatable)")
    parser.add_argument("--rebuild", action="store_true",
                        help="delete the whole knowledge base first, then ingest")
    parser.add_argument("--dry-run", action="store_true",
                        help="fetch and clean only; write data/processed/*.jsonl, skip embedding and storage")
    parser.add_argument("--list", action="store_true",
                        help="list configured sources and how many chunks each has stored")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("urllib3", "httpx", "chromadb", "trafilatura", "sentence_transformers"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    try:
        if args.list:
            return _list_sources(args.sources)
        if args.rebuild and args.source:
            parser.error("--rebuild clears everything; don't combine it with --source")

        from .pipeline import run

        reports = run(args.sources, only=args.source, rebuild=args.rebuild, dry_run=args.dry_run)
    except (ConfigError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ModuleNotFoundError as exc:
        print(
            f"error: missing package '{exc.name}'. Activate the project's virtual environment first:\n"
            "  Windows:      .venv\\Scripts\\activate\n"
            "  macOS/Linux:  source .venv/bin/activate\n"
            "or install everything with:  pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 2

    _print_summary(reports, args.dry_run)
    return 1 if any(r.status == "failed" for r in reports) else 0


def _list_sources(sources_path: str) -> int:
    settings, sources = load_config(sources_path)
    counts: dict[str, int] = {}
    if settings.chroma_path.exists():
        from .store import VectorStore

        counts = VectorStore(settings.chroma_path, settings.collection).counts_by_source()

    print(f"{'id':<28} {'method':<10} {'region':<10} {'enabled':<8} chunks")
    for s in sources:
        print(f"{s.id:<28} {s.method:<10} {s.region:<10} {str(s.enabled):<8} {counts.get(s.id, 0)}")
    print(f"\nTotal chunks stored: {sum(counts.values())}")
    return 0


def _print_summary(reports, dry_run: bool) -> None:
    print("\nSummary" + (" (dry run - nothing stored)" if dry_run else ""))
    print(f"{'source':<28} {'status':<8} {'fetched':>7} {'kept':>5} {'dupes':>6} {'short':>6} {'chunks':>7}")
    for r in reports:
        print(f"{r.source_id:<28} {r.status:<8} {r.fetched:>7} {r.kept:>5} "
              f"{r.duplicates:>6} {r.too_short:>6} {r.chunks:>7}")
        if r.message:
            print(f"    -> {r.message}")


if __name__ == "__main__":
    sys.exit(main())
