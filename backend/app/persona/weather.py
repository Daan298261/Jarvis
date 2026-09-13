"""Live forecast briefing for conversational weather asks (RFC-0084).

Fetched on the no-tools chat path so Jarvis can speak a short answer instead of
writing a retrieval script. Open-Meteo is public and needs no API key.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from ..agent.planning import is_weather_query, latest_user_utterance

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_USER_AGENT = "JarvisLocal/1.0"

_PLACE_AFTER = re.compile(
    r"\b(?:weather|forecast|temperature|rain)\b.{0,48}?\b(?:in|for|at)\s+"
    r"([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ .'-]{0,47}?)"
    r"(?=\s*[,?]|\s+(?:today|tomorrow|tonight|this\s+week|next\s+week)|$)",
    re.IGNORECASE,
)
_PLACE_BEFORE = re.compile(
    r"\b([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ .'-]{1,40})\s+(?:weather|forecast)\b",
    re.IGNORECASE,
)
_STOP_PLACE = {
    "the",
    "a",
    "an",
    "my",
    "our",
    "this",
    "that",
    "today",
    "tomorrow",
    "tonight",
    "morning",
    "afternoon",
    "evening",
    "week",
}
_PLACE_PREFIX = re.compile(
    r"^(?:what|what's|whats|how|how's|when|when's|tell|is|are|the|a|an)\b",
    re.IGNORECASE,
)

_WMO = {
    0: "clear",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "depositing rime fog",
    51: "light drizzle",
    53: "drizzle",
    55: "dense drizzle",
    56: "freezing drizzle",
    57: "dense freezing drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    66: "freezing rain",
    67: "heavy freezing rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    77: "snow grains",
    80: "light rain showers",
    81: "rain showers",
    82: "heavy rain showers",
    85: "snow showers",
    86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with hail",
    99: "thunderstorm with heavy hail",
}

SPEAK_RULES = (
    "Live meteorological briefing (Open-Meteo). Answer in one or two spoken sentences. "
    "Use these numbers. Do not write code, scripts, files, URLs, or fetch steps. "
    "Do not invent extra days. If lookup failed, say so plainly and stop."
)


def extract_place(prompt: str) -> str:
    text = latest_user_utterance(prompt)
    match = _PLACE_AFTER.search(text)
    if not match:
        match = _PLACE_BEFORE.search(text)
    if not match:
        return ""
    place = re.sub(r"\s+", " ", match.group(1)).strip(" .,!?")
    lowered = place.lower()
    if not place or lowered in _STOP_PLACE or _PLACE_PREFIX.search(lowered):
        return ""
    if len(place.split()) > 4:
        return ""
    return place


def requested_day_offset(prompt: str) -> int:
    lowered = latest_user_utterance(prompt).lower()
    if re.search(r"\btomorrow\b", lowered):
        return 1
    if re.search(r"\b(?:in\s+two\s+days|day\s+after\s+tomorrow)\b", lowered):
        return 2
    return 0


def day_label(offset: int) -> str:
    if offset == 1:
        return "tomorrow"
    if offset == 2:
        return "the day after tomorrow"
    return "today"


async def _get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}
    async with httpx.AsyncClient(follow_redirects=True, timeout=8.0, headers=headers) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Unexpected weather payload")
    return payload


def _daily_value(daily: dict[str, Any], key: str, index: int) -> Any:
    values = daily.get(key) or []
    if not isinstance(values, list) or index >= len(values):
        return None
    return values[index]


def format_briefing(
    *,
    place_name: str,
    country: str,
    day: str,
    date_iso: str,
    weather_code: Any,
    temp_max: Any,
    temp_min: Any,
    precipitation: Any,
    precip_chance: Any,
    wind: Any,
    timezone_name: str,
) -> str:
    condition = _WMO.get(int(weather_code), "mixed conditions") if weather_code is not None else "conditions unavailable"
    where = place_name if not country else f"{place_name}, {country}"
    lines = [
        SPEAK_RULES,
        f"Place: {where}",
        f"Day: {day} ({date_iso})",
        f"Conditions: {condition}",
    ]
    if temp_max is not None and temp_min is not None:
        lines.append(f"High: {temp_max}°C  Low: {temp_min}°C")
    elif temp_max is not None:
        lines.append(f"High: {temp_max}°C")
    if precipitation is not None:
        chance = f", {precip_chance}% chance" if precip_chance is not None else ""
        lines.append(f"Precipitation: {precipitation} mm{chance}")
    if wind is not None:
        lines.append(f"Wind: {wind} km/h")
    lines.append(f"Timezone: {timezone_name}")
    lines.append("Source: Open-Meteo")
    return "\n".join(lines)


async def fetch_weather_briefing(prompt: str) -> str | None:
    """Return a system briefing for weather asks, or None when the prompt is unrelated."""
    if not is_weather_query(prompt):
        return None
    place = extract_place(prompt)
    if not place:
        return (
            f"{SPEAK_RULES}\n"
            "Lookup: no town was named. Ask which place, then stop. Do not invent a forecast."
        )
    offset = requested_day_offset(prompt)
    label = day_label(offset)
    try:
        geo = await _get_json(GEOCODE_URL, {"name": place, "count": 1, "language": "en"})
        results = geo.get("results") or []
        if not results:
            return (
                f"{SPEAK_RULES}\n"
                f"Lookup failed: Open-Meteo has no match for {place}. Say you could not find that town."
            )
        hit = results[0]
        latitude = hit.get("latitude")
        longitude = hit.get("longitude")
        forecast = await _get_json(
            FORECAST_URL,
            {
                "latitude": latitude,
                "longitude": longitude,
                "daily": ",".join(
                    [
                        "weather_code",
                        "temperature_2m_max",
                        "temperature_2m_min",
                        "precipitation_sum",
                        "precipitation_probability_max",
                        "wind_speed_10m_max",
                    ]
                ),
                "timezone": "auto",
                "forecast_days": 3,
            },
        )
        tz_name = str(forecast.get("timezone") or "UTC")
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("UTC")
            tz_name = "UTC"
        target = (datetime.now(tz) + timedelta(days=offset)).date().isoformat()
        daily = forecast.get("daily") or {}
        dates = daily.get("time") or []
        if target in dates:
            index = dates.index(target)
        else:
            index = min(offset, max(len(dates) - 1, 0))
            target = dates[index] if dates else target
        return format_briefing(
            place_name=str(hit.get("name") or place),
            country=str(hit.get("country") or ""),
            day=label,
            date_iso=str(target),
            weather_code=_daily_value(daily, "weather_code", index),
            temp_max=_daily_value(daily, "temperature_2m_max", index),
            temp_min=_daily_value(daily, "temperature_2m_min", index),
            precipitation=_daily_value(daily, "precipitation_sum", index),
            precip_chance=_daily_value(daily, "precipitation_probability_max", index),
            wind=_daily_value(daily, "wind_speed_10m_max", index),
            timezone_name=tz_name,
        )
    except Exception as exc:
        return (
            f"{SPEAK_RULES}\n"
            f"Lookup failed: {type(exc).__name__}. Say the forecast service was unreachable. "
            "Do not invent temperatures."
        )


async def weather_system_message(prompt: str) -> str | None:
    return await fetch_weather_briefing(prompt)
