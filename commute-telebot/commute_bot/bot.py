"""Entry point: long-polling Telegram bot with scheduled commute pings.

Usage:
  python -m commute_bot.bot                 # run the bot (scheduled + commands)
  python -m commute_bot.bot --window morning --dry-run   # print one snapshot
  python -m commute_bot.bot --window evening             # send one snapshot now
  python -m commute_bot.bot --whoami        # discover your CHAT_ID
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

from telegram import Bot, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from .config import Config, Secrets, Window, load_config
from .formatting import build_message
from .tfl import TflClient

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
)
log = logging.getLogger("commute_bot")


async def _snapshot(secrets: Secrets, config: Config, window: Window) -> str:
    async with TflClient(app_key=secrets.tfl_app_key) as tfl:
        return await build_message(tfl, window.title, window.watches, config.timezone)


# ---- Scheduled job & command callbacks -------------------------------------

async def _send_window(context: ContextTypes.DEFAULT_TYPE, window_name: str) -> None:
    config: Config = context.application.bot_data["config"]
    secrets: Secrets = context.application.bot_data["secrets"]
    window = config.windows[window_name]
    text = await _snapshot(secrets, config, window)
    await context.bot.send_message(
        chat_id=secrets.chat_id, text=text, parse_mode=ParseMode.HTML
    )


async def scheduled_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_window(context, context.job.data)


def _make_command(window_name: str):
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await _send_window(context, window_name)
    return handler


async def cmd_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config: Config = context.application.bot_data["config"]
    for name in config.windows:
        await _send_window(context, name)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config: Config = context.application.bot_data["config"]
    cmds = " ".join(f"/{n}" for n in config.windows)
    await update.message.reply_text(
        "Commute bot is running.\n"
        f"On-demand: /now  ·  {cmds}\n"
        "/status — next scheduled pings\n"
        "Scheduled pings fire automatically in your configured windows."
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config: Config = context.application.bot_data["config"]
    tz = ZoneInfo(config.timezone)
    now = datetime.now(tz)
    upcoming = sorted(
        (
            (job.next_t.astimezone(tz), job.name)
            for job in context.application.job_queue.jobs()
            if job.next_t is not None
        ),
        key=lambda x: x[0],
    )

    lines = ["🤖 Commute bot status", f"Now: {now:%a %H:%M %Z}"]
    windows = ", ".join(
        f"{n} {w.start}–{w.end}/{w.every_minutes}m" for n, w in config.windows.items()
    )
    lines.append(f"Windows: {windows}")

    if upcoming:
        nxt_dt, nxt_name = upcoming[0]
        mins = round((nxt_dt - now).total_seconds() / 60)
        lines.append(f"Next: {nxt_dt:%a %H:%M} ({nxt_name}) — in ~{mins} min")
        lines.append("Upcoming:")
        lines += [f"  • {dt:%a %H:%M}  {name}" for dt, name in upcoming[:5]]
    else:
        lines.append("No pings scheduled.")

    await update.message.reply_text("\n".join(lines))


# ---- Scheduling ------------------------------------------------------------

def schedule_windows(app: Application, config: Config) -> int:
    tz = ZoneInfo(config.timezone)
    count = 0
    for name, window in config.windows.items():
        days = window.day_numbers()
        for hh, mm in window.tick_times():
            app.job_queue.run_daily(
                scheduled_job,
                time=dtime(hour=hh, minute=mm, tzinfo=tz),
                days=days,
                data=name,
                name=f"{name}-{hh:02d}{mm:02d}",
            )
            count += 1
    return count


def build_application(secrets: Secrets, config: Config) -> Application:
    app = Application.builder().token(secrets.telegram_token).build()
    app.bot_data["secrets"] = secrets
    app.bot_data["config"] = config

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("now", cmd_now))
    app.add_handler(CommandHandler("status", cmd_status))
    for name in config.windows:
        app.add_handler(CommandHandler(name, _make_command(name)))

    n = schedule_windows(app, config)
    log.info("Scheduled %d ping(s) across %d window(s)", n, len(config.windows))
    return app


# ---- One-shot / utility modes ----------------------------------------------

async def run_once(window_name: str, dry_run: bool) -> None:
    config = load_config()
    window = config.windows[window_name]

    if dry_run:
        # No Telegram credentials needed just to preview the message.
        import os

        async with TflClient(app_key=os.getenv("TFL_APP_KEY")) as tfl:
            text = await build_message(
                tfl, window.title, window.watches, config.timezone
            )
        print(text)
        return

    secrets = Secrets()
    text = await _snapshot(secrets, config, window)
    await Bot(secrets.telegram_token).send_message(
        chat_id=secrets.chat_id, text=text, parse_mode=ParseMode.HTML
    )
    print(f"Sent '{window_name}' snapshot to chat {secrets.chat_id}.")


async def run_whoami() -> None:
    # Only the token is needed here — chat_id is what we're trying to discover,
    # so don't require it via Secrets() (chicken-and-egg).
    import os

    from dotenv import dotenv_values

    from .config import PROJECT_ROOT

    env = {**dotenv_values(PROJECT_ROOT / ".env"), **os.environ}
    token = env.get("TELEGRAM_TOKEN")
    if not token:
        print("TELEGRAM_TOKEN is not set in .env — add it, then re-run --whoami.")
        return
    updates = await Bot(token).get_updates()
    if not updates:
        print("No recent messages. Send your bot a message, then re-run --whoami.")
        return
    seen = {}
    for u in updates:
        chat = getattr(u.effective_chat, "id", None)
        name = getattr(u.effective_chat, "full_name", "") or getattr(
            u.effective_chat, "title", ""
        )
        if chat is not None:
            seen[chat] = name
    for cid, name in seen.items():
        print(f"CHAT_ID={cid}  ({name})")


def main() -> None:
    parser = argparse.ArgumentParser(description="TfL commute Telegram bot")
    parser.add_argument("--window", choices=None, help="run one window once (e.g. morning)")
    parser.add_argument("--dry-run", action="store_true", help="print instead of sending")
    parser.add_argument("--whoami", action="store_true", help="print your CHAT_ID")
    args = parser.parse_args()

    if args.whoami:
        asyncio.run(run_whoami())
        return
    if args.window:
        asyncio.run(run_once(args.window, args.dry_run))
        return

    secrets = Secrets()
    config = load_config()
    app = build_application(secrets, config)
    log.info("Starting long-polling…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
