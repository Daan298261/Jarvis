"""Separate-process durable worker for the RFC-0243 lease tests.

argv: mode db_path step_id worker start_at [run_id]
  claim  wait until start_at, then claim the step for inputs "h-<worker>"; print {"ok": id} or {"err": name}
  hold   run a durable model step whose operation never returns (heartbeat 0.2 s, lease 2 s)
"""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))


async def main() -> None:
    mode, db, step_id, worker, start_at = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4], float(sys.argv[5])
    from app.db import session

    await session.configure_database(path=Path(db))
    from app.agent.durable_execution import repository, runner
    from app.agent.durable_execution.types import EffectClass, OperationType, ReplayPolicy

    if mode == "claim":
        while time.time() < start_at:
            await asyncio.sleep(0.001)
        try:
            attempt = await repository.claim_attempt(step_id, worker, input_hash=f"h-{worker}", idempotency_key=f"k-{worker}")
            print(json.dumps({"ok": attempt.id}))
        except Exception as exc:  # reported to the parent test
            print(json.dumps({"err": type(exc).__name__}))
    elif mode == "hold":
        runner.HEARTBEAT_INTERVAL_S = 0.2
        repository.DEFAULT_LEASE_SECONDS = 2

        async def never_returns():
            print("STARTED", flush=True)
            await asyncio.sleep(3600)

        await runner.run_durable_step(
            run_id=sys.argv[6], step_key="model:1:0:0", predecessor_keys=[], operation_type=OperationType.MODEL_CALL,
            effect_class=EffectClass.NONE, replay_policy=ReplayPolicy.IDEMPOTENT, input_fingerprint={"m": "v1"},
            operation=never_returns, result_encoder=lambda value: {"_value": value}, worker_id=worker,
        )
    await session.dispose_database_engine()


asyncio.run(main())
