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


def _texts(scene: Scene) -> list[str]:
    return [(el.text or "").strip() for el in scene.elements if (el.text or "").strip()]


def looks_like_weather_app_surface(scene: Scene) -> bool:
    """Return True for Weather app search/detail pages, not Home widgets."""
    texts = _texts(scene)
    if not texts:
        return False

    has_city_search = any("Search for a city" in text for text in texts)
    has_location_header = any(text == "MY LOCATION" for text in texts)
    has_forecast = any(text == "10-DAY FORECAST" for text in texts)
    has_weather_sentence = any(
        "conditions will continue" in text or "Wind gusts" in text or "km/h" in text
        for text in texts
    )
    weatherish = sum(
        1
        for text in texts
        if "°" in text
        or text in _WEATHER_CONDITIONS
        or text in _FORECAST_DAYS
        or (text.rstrip("%").isdigit() and "%" in text)
    )

    if has_city_search and (has_forecast or weatherish >= 3):
        return True
    if has_location_header and has_forecast and (weatherish >= 2 or has_weather_sentence):
        return True
    return has_city_search and has_weather_sentence and weatherish >= 2
