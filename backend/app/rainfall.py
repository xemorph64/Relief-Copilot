"""Rainfall around the incident date for the evidence pack.

Uses the Open-Meteo archive (reanalysis, no key) as supporting context, clearly labelled as
non-IMD. ponytail: swap in IMD district rainfall via data.gov.in once DATA_GOV_IN_API_KEY is set.
"""
import datetime as dt

import httpx

URL = "https://archive-api.open-meteo.com/v1/archive"


async def around(lat: float, lon: float, date: str, days: int = 3) -> dict:
    d = dt.date.fromisoformat(date)
    params = {"latitude": lat, "longitude": lon, "daily": "precipitation_sum", "timezone": "Asia/Kolkata",
              "start_date": (d - dt.timedelta(days=days)).isoformat(),
              "end_date": (d + dt.timedelta(days=days)).isoformat()}
    async with httpx.AsyncClient(timeout=30) as c:
        r = (await c.get(URL, params=params)).raise_for_status().json()
    series = dict(zip(r["daily"]["time"], r["daily"]["precipitation_sum"]))
    return {"source": "Open-Meteo archive (reanalysis; not IMD)", "url": URL, "query": params,
            "fetched_at": dt.datetime.now().isoformat(timespec="seconds"), "mm_by_day": series,
            "max_3day_mm": max(sum(v or 0 for v in list(series.values())[i:i + 3]) for i in range(len(series) - 2))}
