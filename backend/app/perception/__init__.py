"""Privacy-safe social perception primitives.

This package intentionally operates on structured observations only. Camera capture,
raw image handling, semantic VLM inference, identity recognition, dialogue generation,
and TTS live in separate layers/RFCs.
"""

from .models import ObservationCandidate, StructuredObservation
from .policy import PerceptionPolicy, PolicyResult
from .store import PerceptionStateStore

__all__ = [
    "ObservationCandidate",
    "PerceptionPolicy",
    "PerceptionStateStore",
    "PolicyResult",
    "StructuredObservation",
]
