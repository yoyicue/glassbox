"""Heuristics for iOS Weather app surfaces."""

from __future__ import annotations

from glassbox.cognition.base import Scene

_WEATHER_CONDITIONS = {
    "Sunny",
    "Cloudy",
    "Drizzle",
    "Rain",
    "Showers",
    "Windy",
    "Now",
}
_FORECAST_DAYS = {"Today", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}
_WEATHER_CONDITIONS_NORMALIZED = {item.casefold() for item in _WEATHER_CONDITIONS}
_FORECAST_DAYS_NORMALIZED = {item.casefold() for item in _FORECAST_DAYS}


def _texts(scene: Scene) -> list[str]:
    return [(el.text or "").strip() for el in scene.elements if (el.text or "").strip()]


def _normalized(text: str) -> str:
    return text.strip().lstrip("•·-–— ").casefold()


def looks_like_weather_app_surface(scene: Scene) -> bool:
    """Return True for Weather app search/detail pages, not Home widgets."""
    texts = _texts(scene)
    if not texts:
        return False
    normalized = [_normalized(text) for text in texts]

    has_city_search = any("search for a city" in text for text in normalized)
    has_location_header = any(text == "my location" for text in normalized)
    has_forecast = any("10-day forecast" in text for text in normalized)
    has_hourly_forecast = any("hourly forecast" in text for text in normalized)
    has_weather_sentence = any(
        "conditions will continue" in text or "wind gusts" in text or "km/h" in text
        for text in normalized
    )
    weatherish = sum(
        1
        for text, normalized_text in zip(texts, normalized, strict=True)
        if "°" in text
        or normalized_text in _WEATHER_CONDITIONS_NORMALIZED
        or normalized_text in _FORECAST_DAYS_NORMALIZED
        or (text.rstrip("%").isdigit() and "%" in text)
    )

    if has_city_search and (has_forecast or has_hourly_forecast or weatherish >= 3):
        return True
    if has_location_header and has_forecast and (weatherish >= 2 or has_weather_sentence):
        return True
    return has_city_search and has_weather_sentence and weatherish >= 2
