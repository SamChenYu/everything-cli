"""Thin async client for the TfL Unified API (https://api.tfl.gov.uk)."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

BASE_URL = "https://api.tfl.gov.uk"


@dataclass
class Arrival:
    line: str        # human name, e.g. "205" or "Hammersmith & City"
    line_id: str     # TfL id, e.g. "205" or "hammersmith-city"
    destination: str
    towards: str
    seconds: int
    stop_name: str
    platform: str = ""

    @property
    def minutes(self) -> int:
        # TfL counts down to arrival; round to nearest minute, floor at 0.
        return max(0, round(self.seconds / 60))


# Backwards-compatible alias (arrivals are the same shape for bus and rail).
BusArrival = Arrival


@dataclass
class LineStatus:
    line: str
    description: str  # e.g. "Good Service", "Minor Delays"
    reason: str | None
    is_good: bool


class TflClient:
    def __init__(self, app_key: str | None = None, timeout: float = 10.0):
        self._app_key = app_key
        self._client = httpx.AsyncClient(
            base_url=BASE_URL, timeout=timeout, headers={"User-Agent": "commute-bot"}
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "TflClient":
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.aclose()

    def _params(self, extra: dict | None = None) -> dict:
        params = dict(extra or {})
        if self._app_key:
            params["app_key"] = self._app_key
        return params

    async def _get(self, path: str, params: dict | None = None):
        resp = await self._client.get(path, params=self._params(params))
        resp.raise_for_status()
        return resp.json()

    async def bus_arrivals(
        self,
        stop_id: str,
        line: str | None = None,
        destination_contains: str | None = None,
        limit: int = 3,
    ) -> list[BusArrival]:
        """Live predicted arrivals at a stop, soonest first, optionally filtered."""
        arrivals = await self._arrivals(stop_id)
        if line:
            arrivals = [a for a in arrivals if a.line == line]
        if destination_contains:
            needle = destination_contains.lower()
            arrivals = [
                a
                for a in arrivals
                if needle in a.destination.lower() or needle in a.towards.lower()
            ]
        arrivals.sort(key=lambda a: a.seconds)
        return arrivals[:limit]

    async def tube_arrivals(
        self,
        stop_id: str,
        line_id: str,
        direction: str | None = None,
        limit: int = 3,
    ) -> list[Arrival]:
        """Live tube arrivals at a station, filtered by line and direction.

        `direction` is matched against the platform name (e.g. "Westbound"),
        which TfL populates reliably even when the direction/destination
        fields are missing.
        """
        arrivals = [a for a in await self._arrivals(stop_id) if a.line_id == line_id]
        if direction:
            needle = direction.lower()
            arrivals = [a for a in arrivals if needle in a.platform.lower()]
        arrivals.sort(key=lambda a: a.seconds)
        return arrivals[:limit]

    async def _arrivals(self, stop_id: str) -> list[Arrival]:
        data = await self._get(f"/StopPoint/{stop_id}/Arrivals")
        return [
            Arrival(
                line=a.get("lineName") or a.get("lineId") or "?",
                line_id=a.get("lineId") or "",
                destination=a.get("destinationName") or "",
                towards=a.get("towards") or "",
                seconds=int(a.get("timeToStation", 0)),
                stop_name=a.get("stationName") or "",
                platform=a.get("platformName") or "",
            )
            for a in data
        ]

    async def line_status(self, line_id: str) -> LineStatus:
        """Current disruption status for a tube/rail line."""
        data = await self._get(f"/Line/{line_id}/Status")
        name = data[0].get("name", line_id) if data else line_id
        statuses = data[0].get("lineStatuses", []) if data else []
        if not statuses:
            return LineStatus(name, "Unknown", None, is_good=False)
        # Report the most severe status (lowest severity number = worst).
        worst = min(statuses, key=lambda s: s.get("statusSeverity", 10))
        desc = worst.get("statusSeverityDescription", "Unknown")
        return LineStatus(
            line=name,
            description=desc,
            reason=worst.get("reason"),
            is_good=(desc == "Good Service"),
        )

    async def search_stops(self, query: str, modes: str = "bus,tube") -> list[dict]:
        """Search stop points by name; returns raw matches for setup helper."""
        data = await self._get(
            "/StopPoint/Search", {"query": query, "modes": modes}
        )
        return data.get("matches", [])
