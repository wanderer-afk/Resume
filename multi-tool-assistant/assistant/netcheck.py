"""Check which of the websites the app uses can be reached from this computer."""

from __future__ import annotations

import requests

TIMEOUT_SECONDS = 10

# (plain-English name, website, small test request)
CHECKS = [
    ("weather forecast", "https://api.open-meteo.com/v1/forecast",
     {"latitude": 48.85, "longitude": 2.35, "current": "temperature_2m"}),
    ("weather city lookup", "https://geocoding-api.open-meteo.com/v1/search",
     {"name": "Paris", "count": 1}),
    ("country facts", "https://restcountries.com/v3.1/name/france",
     {"fullText": "true"}),
]


def _explain(exc: Exception) -> str:
    if isinstance(exc, requests.Timeout):
        return "timed out"
    if isinstance(exc, requests.ConnectionError):
        return "could not connect (check your internet connection, firewall or proxy)"
    if isinstance(exc, requests.HTTPError):
        return f"the website answered with HTTP {exc.response.status_code}"
    return f"unexpected problem ({type(exc).__name__})"


def check_network(session: requests.Session | None = None) -> list[tuple[str, bool, str]]:
    """Return (name, ok, detail) for each website. Never raises."""
    client = session or requests.Session()
    rows = []
    for name, url, params in CHECKS:
        host = url.split("/")[2]
        try:
            resp = client.get(url, params=params, timeout=TIMEOUT_SECONDS)
            resp.raise_for_status()
            rows.append((name, True, host))
        except requests.RequestException as exc:
            rows.append((name, False, f"{host}: {_explain(exc)}"))
    return rows


def format_report(rows: list[tuple[str, bool, str]]) -> str:
    lines = ["Checking the websites the app uses:", ""]
    for name, ok, detail in rows:
        status = "OK    " if ok else "FAILED"
        lines.append(f"  {status}  {name} ({detail})" if ok else f"  {status}  {name}: {detail}")
    working = sum(1 for _, ok, _ in rows if ok)
    lines.append("")
    if working == len(rows):
        lines.append(f"All {working} of {len(rows)} websites work. The app can use live data.")
    else:
        lines.append(f"{working} of {len(rows)} websites work.")
        lines.append("For the websites that failed, the app will say so. You can still use it with")
        lines.append("  python main.py --web --sample-data")
        lines.append("which uses made-up data and is labelled that way.")
    return "\n".join(lines)
