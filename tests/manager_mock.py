from __future__ import annotations

from types import SimpleNamespace


async def ready_for_profile(*_args, **_kwargs) -> bool:
    return True


async def noop(*_args, **_kwargs):
    return None


def loop_manager(
    provider,
    *,
    loaded: bool = True,
    profile: str = "fast",
    thinking_at_process: bool = False,
    record_timings=noop,
    load=noop,
    ready=ready_for_profile,
    **extra,
) -> SimpleNamespace:
    return SimpleNamespace(
        provider=provider,
        state=SimpleNamespace(loaded=loaded, profile=profile, thinking_at_process=thinking_at_process),
        record_timings=record_timings,
        load=load,
        ready_for_profile=ready,
        **extra,
    )
