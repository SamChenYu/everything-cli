"""Configuration: secrets from .env, watch/window config from config.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, Union

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 0=Sunday..6=Saturday, matching python-telegram-bot v20+ run_daily(days=...).
DAY_NAME_TO_NUM = {
    "sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6,
}


class Secrets(BaseSettings):
    """Loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    telegram_token: str
    chat_id: int
    tfl_app_key: str | None = None


class BusWatch(BaseModel):
    kind: Literal["bus"] = "bus"
    label: str
    stop_id: str
    line: str | None = None
    destination_contains: str | None = None
    max_results: int = 3


class TubeWatch(BaseModel):
    kind: Literal["tube"] = "tube"
    label: str
    line: str  # TfL line id, e.g. "hammersmith-city"
    # Optional: show next-train times at a station. Without stop_id we only
    # report line status.
    stop_id: str | None = None       # tube station Naptan, e.g. "940GZZLUSGN"
    direction: str | None = None     # matched in platform name: "Westbound"/"Eastbound"
    max_results: int = 3


Watch = Annotated[Union[BusWatch, TubeWatch], Field(discriminator="kind")]


class Window(BaseModel):
    title: str
    days: list[str] = ["mon", "tue", "wed", "thu", "fri"]
    start: str  # "HH:MM"
    end: str    # "HH:MM"
    every_minutes: int = 5
    watches: list[Watch]

    def day_numbers(self) -> tuple[int, ...]:
        return tuple(DAY_NAME_TO_NUM[d.lower()] for d in self.days)

    def tick_times(self) -> list[tuple[int, int]]:
        """List of (hour, minute) ticks from start to end inclusive."""
        sh, sm = (int(x) for x in self.start.split(":"))
        eh, em = (int(x) for x in self.end.split(":"))
        start_total, end_total = sh * 60 + sm, eh * 60 + em
        return [
            (t // 60, t % 60)
            for t in range(start_total, end_total + 1, self.every_minutes)
        ]


class Config(BaseModel):
    timezone: str = "Europe/London"
    windows: dict[str, Window]


def load_config(path: Path | str | None = None) -> Config:
    path = Path(path) if path else PROJECT_ROOT / "config.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Copy config.example.yaml to config.yaml and fill it in."
        )
    data = yaml.safe_load(path.read_text())
    return Config.model_validate(data)
