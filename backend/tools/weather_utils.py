"""Pure helpers for weather forecast request normalization."""

from __future__ import annotations


SUPPORTED_FORECAST_DAYS = (3, 7)


def normalize_forecast_days(days: int) -> int:
    """Map an arbitrary trip duration to a supported QWeather endpoint slot."""

    requested = max(int(days), 1)
    for supported in SUPPORTED_FORECAST_DAYS:
        if requested <= supported:
            return supported
    return SUPPORTED_FORECAST_DAYS[-1]
