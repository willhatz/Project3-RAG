"""Errors an ingester can raise. The pipeline logs them and moves on to the next source."""


class IngestError(RuntimeError):
    """The source could not be fetched (network error, HTTP error, blocked by robots.txt...)."""


class IngestSkipped(RuntimeError):
    """The source was deliberately skipped (e.g. a required API key is not configured yet)."""
