from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class TtsRuntimeState:
    engine_id: str
    package_ready: bool
    assets_ready: bool
    pipeline_ready: bool
    synthesis_verified: bool
    model_id: str = ""
    speaker_ref: str = ""
    device: str = ""
    last_error: str = ""

    @property
    def ready(self) -> bool:
        return (
            self.package_ready
            and self.assets_ready
            and self.pipeline_ready
            and self.synthesis_verified
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ready"] = self.ready
        return payload
