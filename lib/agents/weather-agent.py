"""Simple weather helper used by MERID demo agents."""

from __future__ import annotations

import json
import os
import sys
from typing import Dict, Optional

import requests


class WeatherAgentError(RuntimeError):
    """Raised when the agent cannot fulfill the request."""


def get_weather(location: str, *, units: str = "metric") -> Dict[str, object]:
    """Fetch current weather from OpenWeather using an env-provided API key."""

    api_key = os.getenv("OPENWEATHER_API_KEY")
    if not api_key:
        raise WeatherAgentError("OPENWEATHER_API_KEY not set")
    if not location:
        raise WeatherAgentError("location is required")

    params = {
        "q": location,
        "appid": api_key,
        "units": units,
    }
    response = requests.get("https://api.openweathermap.org/data/2.5/weather", params=params, timeout=10)
    response.raise_for_status()
    return response.json()


def _run_cli(raw_input: str) -> Dict[str, object]:
    if not raw_input:
        raise WeatherAgentError("No input provided")

    params = json.loads(raw_input)
    location = params.get("location", "")
    units = params.get("units", "metric")
    return get_weather(str(location), units=str(units))


def main(stdin: Optional[str] = None) -> None:
    try:
        payload = _run_cli((stdin if stdin is not None else sys.stdin.read()).strip())
        print(json.dumps(payload))
    except WeatherAgentError as exc:
        print(json.dumps({"error": str(exc)}))
    except json.JSONDecodeError:
        print(json.dumps({"error": "Invalid JSON input"}))
    except Exception as exc:  # pragma: no cover - protects agent shell
        print(json.dumps({"error": f"Weather agent failed: {exc}"}))


if __name__ == "__main__":
    main()
