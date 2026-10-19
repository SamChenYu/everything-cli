"""Setup helper: find the exact Naptan stop_id for a directional bus stop.

  # 1. search by name to get candidate stop ids
  python -m commute_bot.find_stops "Stepney Green"

  # 2. confirm a candidate is the right DIRECTION by dumping its live arrivals
  python -m commute_bot.find_stops --arrivals 490007705E --line 205

The right stop is the one whose 205 arrivals show "towards" your destination
(Marble Arch in the morning, Bow Church in the evening).
"""

from __future__ import annotations

import argparse
import asyncio

from .config import Secrets
from .tfl import TflClient


async def do_search(query: str, modes: str) -> None:
    secrets = _secrets_or_none()
    async with TflClient(app_key=secrets) as tfl:
        matches = await tfl.search_stops(query, modes=modes)
    if not matches:
        print(f"No matches for {query!r}.")
        return
    print(f"{'stop_id':<20} {'modes':<12} name")
    print("-" * 70)
    for m in matches:
        modes_str = ",".join(m.get("modes", []))
        print(f"{m.get('id',''):<20} {modes_str:<12} {m.get('name','')}")
    print("\nNext: confirm direction with --arrivals <stop_id> --line 205")


async def do_arrivals(stop_id: str, line: str | None) -> None:
    secrets = _secrets_or_none()
    async with TflClient(app_key=secrets) as tfl:
        arrivals = await tfl.bus_arrivals(stop_id, line=line, limit=10)
    if not arrivals:
        print("No arrivals right now (try during service hours).")
        return
    print(f"{'line':<6} {'min':>4}  towards / destination   @ {arrivals[0].stop_name}")
    print("-" * 60)
    for a in arrivals:
        dest = a.towards or a.destination
        print(f"{a.line:<6} {a.minutes:>4}  {dest}")


def _secrets_or_none() -> str | None:
    try:
        return Secrets().tfl_app_key
    except Exception:  # noqa: BLE001 - key is optional for lookups
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Find TfL stop ids")
    parser.add_argument("query", nargs="?", help="stop name to search")
    parser.add_argument("--modes", default="bus,tube")
    parser.add_argument("--arrivals", metavar="STOP_ID", help="dump live arrivals")
    parser.add_argument("--line", help="filter arrivals to this line, e.g. 205")
    args = parser.parse_args()

    if args.arrivals:
        asyncio.run(do_arrivals(args.arrivals, args.line))
    elif args.query:
        asyncio.run(do_search(args.query, args.modes))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
