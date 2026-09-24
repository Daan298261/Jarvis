from backend.app.persona.session_personality import auto_route_from_owner_message, classify_specialist, manual_lock, reset_session_personality_for_tests, set_active_mode, set_manual_lock

def setup_function(): reset_session_personality_for_tests()

def test_argus_intelligence_route():
    target,confidence,_=classify_specialist("Create an OSINT threat assessment with source provenance")
    assert target=="argus" and confidence>=.8

def test_coding_route_preserved():
    assert classify_specialist("debug this Python API and add unit tests")[0]=="coding"

def test_ambiguous_stays_core():
    assert classify_specialist("hello, how are you?")[0]=="core"

def test_manual_lock_blocks_auto_handoff():
    set_active_mode("research",persist_dialogue=False); set_manual_lock(True)
    mode,meta=auto_route_from_owner_message("OSINT intelligence brief")
    assert mode is None and meta["blocked_by_manual_lock"] and manual_lock()

def test_auto_handoff_to_argus():
    mode,meta=auto_route_from_owner_message("Use Crucix for an intelligence brief")
    assert mode and mode.id=="argus" and meta["automatic"]
