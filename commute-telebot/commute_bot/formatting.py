"""Build the Telegram message text for a window from live TfL data."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .config import BusWatch, TubeWatch, Watch
from .tfl import TflClient


def _fmt_minutes(minutes: int) -> str:
    return "due" if minutes == 0 else f"{minutes} min"


async def render_watch(client: TflClient, watch: Watch) -> str:
    if isinstance(watch, BusWatch):
        try:
            arrivals = await client.bus_arrivals(
                watch.stop_id,
                line=watch.line,
                destination_contains=watch.destination_contains,
                limit=watch.max_results,
            )
        except Exception as exc:  # noqa: BLE001 - surface, don't crash the whole ping
            return f"🚌 {watch.label}: ⚠️ error ({exc.__class__.__name__})"
        if not arrivals:
            return f"🚌 {watch.label}: no arrivals predicted"
        times = ", ".join(_fmt_minutes(a.minutes) for a in arrivals)
        return f"🚌 {watch.label}: {times}"

    if isinstance(watch, TubeWatch):
        try:
            status = await client.line_status(watch.line)
        except Exception as exc:  # noqa: BLE001
            return f"🚇 {watch.label}: ⚠️ error ({exc.__class__.__name__})"

        icon = "✅" if status.is_good else "⚠️"

        # If a station is configured, lead with next-train times.
        if watch.stop_id:
            try:
                arrivals = await client.tube_arrivals(
                    watch.stop_id,
                    line_id=watch.line,
                    direction=watch.direction,
                    limit=watch.max_results,
                )
            except Exception as exc:  # noqa: BLE001
                arrivals = None
            if arrivals:
                times = ", ".join(_fmt_minutes(a.minutes) for a in arrivals)
                line = f"🚇 {watch.label}: {times}  ({icon} {status.description})"
            elif arrivals is None:
                line = f"🚇 {watch.label}: ⚠️ arrivals unavailable ({icon} {status.description})"
            else:
                line = f"🚇 {watch.label}: no trains predicted  ({icon} {status.description})"
        else:
            line = f"🚇 {watch.label}: {icon} {status.description}"

        if status.reason and not status.is_good:
            line += f"\n   ↳ {status.reason}"
        return line

    return f"❓ {watch.label}: unsupported watch"


async def build_message(
    client: TflClient, title: str, watches: list[Watch], tz: str
) -> str:
    now = datetime.now(ZoneInfo(tz)).strftime("%H:%M")
    header = f"{title}  ·  {now}"
    lines = [await render_watch(client, w) for w in watches]
    return "\n".join([header, *lines])
