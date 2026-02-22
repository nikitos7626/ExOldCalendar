from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List

from dotenv import load_dotenv

WEEKDAY_ALIASES = {
    "mon": 0,
    "monday": 0,
    "tue": 1,
    "tues": 1,
    "tuesday": 1,
    "wed": 2,
    "wednesday": 2,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "thursday": 3,
    "fri": 4,
    "friday": 4,
    "sat": 5,
    "saturday": 5,
    "sun": 6,
    "sunday": 6,
}


@dataclass(slots=True, frozen=True)
class Settings:
    bot_token: str
    instructor_chat_id: int
    timezone: str
    workdays: List[int]
    work_start_hour: int
    work_end_hour: int
    slot_duration_minutes: int
    booking_horizon_days: int
    storage_path: Path
    # MySQL settings
    mysql_host: str
    mysql_port: int
    mysql_user: str
    mysql_password: str
    mysql_database: str
    # Flask settings
    flask_secret_key: str
    flask_host: str
    flask_port: int


def _parse_workdays(raw: str | None) -> List[int]:
    if not raw:
        return [0, 1, 2, 3, 4, 5]
    result: List[int] = []
    for item in raw.split(","):
        key = item.strip().lower()
        if not key:
            continue
        if key not in WEEKDAY_ALIASES:
            raise ValueError(f"Unknown weekday alias: {item}")
        value = WEEKDAY_ALIASES[key]
        if value not in result:
            result.append(value)
    if not result:
        raise ValueError("At least one working day must be provided")
    return result


def load_settings(env_file: str | None = None) -> Settings:
    """Load settings from .env, config.env or environment variables."""
    if env_file:
        load_dotenv(env_file)
    else:
        # load defaults from config.env first, allow .env to override them
        load_dotenv("config.env")
        load_dotenv(".env", override=True)

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    instructor_chat_id = os.getenv("INSTRUCTOR_CHAT_ID")
    if not bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
    if not instructor_chat_id:
        raise RuntimeError("INSTRUCTOR_CHAT_ID is not set")

    timezone = os.getenv("TIMEZONE", "Europe/Moscow")
    workdays = _parse_workdays(os.getenv("WORKING_DAYS"))
    work_start_hour = int(os.getenv("WORK_START_HOUR", "8"))
    work_end_hour = int(os.getenv("WORK_END_HOUR", "22"))
    booking_horizon_days = min(
        max(int(os.getenv("BOOKING_HORIZON_DAYS", "14")), 1),
        30,
    )

    if work_end_hour <= work_start_hour:
        raise ValueError("WORK_END_HOUR must be greater than WORK_START_HOUR")

    data_dir = Path("data")
    data_dir.mkdir(parents=True, exist_ok=True)

    # MySQL settings
    mysql_host = os.getenv("MYSQL_HOST", "localhost")
    mysql_port = int(os.getenv("MYSQL_PORT", "3306"))
    mysql_user = os.getenv("MYSQL_USER", "root")
    mysql_password = os.getenv("MYSQL_PASSWORD", "")
    mysql_database = os.getenv("MYSQL_DATABASE", "excalendar")

    return Settings(
        bot_token=bot_token,
        instructor_chat_id=int(instructor_chat_id),
        timezone=timezone,
        workdays=workdays,
        work_start_hour=work_start_hour,
        work_end_hour=work_end_hour,
        slot_duration_minutes=60,
        booking_horizon_days=booking_horizon_days,
        storage_path=data_dir / "bookings.json",
        mysql_host=mysql_host,
        mysql_port=mysql_port,
        mysql_user=mysql_user,
        mysql_password=mysql_password,
        mysql_database=mysql_database,
        flask_secret_key=os.getenv("FLASK_SECRET_KEY", "dev-secret-key"),
        flask_host=os.getenv("FLASK_HOST", "0.0.0.0"),
        flask_port=int(os.getenv("FLASK_PORT", "5000")),
    )

