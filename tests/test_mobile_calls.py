from app.mobile import calls


def test_call_offer_generations_are_replayable_and_ordered():
    call = {"id": "call-one", "generation": -1}
    decision, record = calls.offer_decision(call, 0, "first offer")
    assert decision == "replace"
    record["answer"] = "first answer"
    calls.OFFERS[call["id"]] = record
    call["generation"] = 0
    decision, replay = calls.offer_decision(call, 0, "first offer")
    assert decision == "replay" and replay["answer"] == "first answer"
    assert calls.offer_decision(call, 0, "different offer")[0] == "stale"
    assert calls.offer_decision(call, 2, "skipped generation")[0] == "stale"
    assert calls.offer_decision(call, 1, "reconnect offer")[0] == "replace"
    calls.OFFERS.clear()


def test_reconnecting_call_remains_active_for_new_offer():
    assert "reconnecting" in calls.ACTIVE_STATES
