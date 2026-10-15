from __future__ import annotations

import time
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI
from app.mobile import quick_route
from app.decision.types import Answer, DecisionResult


@pytest.fixture(autouse=True)
def local_audit(monkeypatch):
    sink = Mock()
    monkeypatch.setattr(quick_route.audit, "record_event", sink)
    return sink


def result(provider="laya", mode="quick", confidence=.95, fixture=False):
    return DecisionResult(answers={"answer_mode": Answer("answer_mode", "choice", mode, confidence)}, source=provider, provider=provider, decision_class="mobile_answer_mode", fixture=fixture)


@pytest.mark.asyncio
async def test_jev_requires_both_phone_consent_and_desktop_availability(monkeypatch):
    probe = Mock(return_value=(False, "owner disabled"))
    call = Mock(side_effect=AssertionError("must not contact cloud"))
    monkeypatch.setattr(quick_route.jev_adapter, "available", probe)
    monkeypatch.setattr(quick_route.jev_adapter, "decide", call)
    out = await quick_route.route_question("question", "jev", False)
    assert out["source"] == "local_fallback"
    probe.assert_not_called()
    out = await quick_route.route_question("question", "jev", True)
    assert out["fallback_used"]
    assert probe.call_args.kwargs["privacy"] == "allow_cloud"
    call.assert_not_called()


@pytest.mark.asyncio
async def test_laya_route_is_bounded_and_reports_real_provider(monkeypatch):
    monkeypatch.setattr(quick_route.laya_adapter, "available", lambda **kw: (True, ""))
    call = Mock(return_value=result(mode="detailed"))
    monkeypatch.setattr(quick_route.laya_adapter, "decide", call)
    out = await quick_route.route_question("a" * 800, "laya")
    assert out == {"mode": "detailed", "source": "laya", "fallback_used": False}
    assert len(call.call_args.kwargs["state"]["text"]) == 512
    assert call.call_args.kwargs["deadline_ms"] == 150
    assert set(call.call_args.kwargs["state"]) == {"text"}


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", [result(fixture=True), result(mode="invented"), result(confidence=.2), result(confidence=float("nan")), result(provider="rules")])
async def test_fixtures_low_confidence_and_fake_sources_never_claim_laya(monkeypatch, answer):
    monkeypatch.setattr(quick_route.laya_adapter, "available", lambda **kw: (True, ""))
    monkeypatch.setattr(quick_route.laya_adapter, "decide", lambda **kw: answer)
    assert (await quick_route.route_question("question", "laya"))["source"] == "local_fallback"


@pytest.mark.asyncio
async def test_slow_decider_does_not_hold_the_answer(monkeypatch):
    monkeypatch.setattr(quick_route.laya_adapter, "available", lambda **kw: (True, ""))
    def slow(**kwargs):
        time.sleep(.4)
        return result()
    monkeypatch.setattr(quick_route.laya_adapter, "decide", slow)
    started = time.monotonic()
    assert (await quick_route.route_question("question", "laya"))["fallback_used"]
    assert time.monotonic() - started < .35


@pytest.mark.asyncio
async def test_companion_endpoint_requires_device_and_rejects_oversized_input(monkeypatch):
    from app.api.companion import router
    from app.mobile.identity import require_device
    app = FastAPI(); app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post("/api/companion/quick-route", json={"text": "hello", "engine": "laya"})).status_code == 401
        app.dependency_overrides[require_device] = lambda: {"id": "phone"}
        assert (await client.post("/api/companion/quick-route", json={"text": "x" * 513, "engine": "laya"})).status_code == 422
        assert (await client.post("/api/companion/quick-route", json={"text": "hello", "engine": "fake"})).status_code == 422
