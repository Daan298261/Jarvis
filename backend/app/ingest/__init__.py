"""External content ingestion pipeline for social and web URLs."""

from .orchestrator import ingest_url
from .schema import ExternalContentArtifact

__all__ = ["ExternalContentArtifact", "ingest_url"]
