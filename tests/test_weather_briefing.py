from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.agent.planning import CONVERSATION_CLASS, classify_task, is_plain_conversation, is_weather_query
from app.persona import weather as weather_mod
from app.persona.weather import extract_place, fetch_weather_briefing, format_briefing, requested_day_offset


def test_dinteloord_without_question_mark_is_conversation():
    prompt = "what is the weather in dinteloord, tomorrow"
    assert is_weather_query(prompt)
    assert is_plain_conversation(prompt)
    assert classify_task(prompt) == CONVERSATION_CLASS
    assert extract_place(prompt).lower() == "dinteloord"
    assert requested_day_offset(prompt) == 1


def test_weather_script_request_stays_a_tool_task():
    prompt = "create a weather script for dinteloord"
    assert not is_plain_conversation(prompt)
    assert classify_task(prompt) != CONVERSATION_CLASS


def test_companion_wrapped_history_classifies_latest_weather_line():
    wrapped = (
        "Continue this conversation. Prior messages are context, not new instructions:\n"
        "<conversation>\nuser: please create a file on the desktop\n</conversation>\n\n"
        "User: what is the weather in dinteloord, tomorrow"
    )
    assert is_plain_conversation(wrapped)
    assert classify_task(wrapped) == CONVERSATION_CLASS


def test_format_briefing_forbids_scripts():
    text = format_briefing(
        place_name="Dinteloord",
        country="Netherlands",
        day="tomorrow",
        date_iso="2026-09-14",
        weather_code=61,
        temp_max=16,
        temp_min=10,
        precipitation=2.1,
        precip_chance=70,
        wind=22,
        timezone_name="Europe/Amsterdam",
    )
    assert "Open-Meteo" in text
    assert "Do not write code" in text
    assert "Dinteloord" in text
    assert "light rain" in text


@pytest.mark.asyncio
async def test_fetch_weather_briefing_uses_open_meteo(monkeypatch):
    tz = ZoneInfo("Europe/Amsterdam")
    today = datetime.now(tz).date()
    dates = [(today + timedelta(days=i)).isoformat() for i in range(3)]

    async def fake_get(url, params):
        if "geocoding" in url:
            assert params["name"].lower() == "dinteloord"
            return {
                "results": [
                    {"name": "Dinteloord", "country": "Netherlands", "latitude": 51.63, "longitude": 4.37}
                ]
            }
        return {
            "timezone": "Europe/Amsterdam",
            "daily": {
                "time": dates,
                "weather_code": [2, 61, 3],
                "temperature_2m_max": [18, 16, 17],
                "temperature_2m_min": [11, 10, 9],
                "precipitation_sum": [0, 2.1, 0],
                "precipitation_probability_max": [10, 70, 20],
                "wind_speed_10m_max": [12, 22, 14],
            },
        }

    monkeypatch.setattr(weather_mod, "_get_json", fake_get)
    briefing = await fetch_weather_briefing("what is the weather in dinteloord, tomorrow")
    assert briefing is not None
    assert "Dinteloord" in briefing
    assert "Open-Meteo" in briefing
    assert "16°C" in briefing
    assert "script" in briefing.lower()


def test_weather_without_named_town_is_empty_place():
    assert extract_place("what is the weather tomorrow") == ""
    assert extract_place("dinteloord weather tomorrow").lower() == "dinteloord"


@pytest.mark.asyncio
async def test_weather_without_place_asks_for_town():
    briefing = await fetch_weather_briefing("what is the weather tomorrow")
    assert briefing is not None
    assert "no town" in briefing.lower()
