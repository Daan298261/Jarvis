from __future__ import annotations

from .checkpoint import last_known_good_checkpoint
from .journal import last_committed_seq, prune_through_seq
from .store import connect


def prune_config() -> dict[str, int]:
    conn = connect()
    row = conn.execute("SELECT detail_json FROM prune_audit ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    return {"default_retain_journal_entries": 5000}


def prune_journal(
    *,
    actor: str = "operator",
    retain_through_seq: int | None = None,
) -> dict[str, object]:
    good = last_known_good_checkpoint()
    if not good:
        raise ValueError("cannot prune without a retained KNOWN_GOOD checkpoint")
    head = last_committed_seq()
    target = retain_through_seq if retain_through_seq is not None else int(good["journal_seq"])
    if target >= head:
        return {"pruned": 0, "reason": "nothing_to_prune", "retained_checkpoint_id": good["id"]}
    deleted = prune_through_seq(target, retained_checkpoint_id=good["id"], actor=actor)
    return {
        "pruned": deleted,
        "pruned_through_seq": target,
        "retained_checkpoint_id": good["id"],
        "journal_head_seq": last_committed_seq(),
    }
