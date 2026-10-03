"""Чистая логика расписания и прогресса, без Telegram и БД — её легко тестировать."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

TOTAL_DAYS = 30


def local_now(tz_offset: int, utc_now: datetime | None = None) -> datetime:
    utc_now = utc_now or datetime.now(timezone.utc)
    return utc_now.astimezone(timezone(timedelta(hours=tz_offset)))


def days_between(earlier_iso: str | None, today: date) -> int:
    if not earlier_iso:
        return 0
    return (today - date.fromisoformat(earlier_iso)).days


def on_program(user: dict) -> bool:
    return (user.get("status") == "active" and user.get("role") == "newbie"
            and 1 <= (user.get("current_day") or 0) <= TOTAL_DAYS)


def morning_action(user: dict, now: datetime, task_hour: int) -> str | None:
    """Что сделать утром с новичком на программе.

    'advance' — вчерашнее задание выполнено, выдать следующее;
    'resend'  — задание не выполнено, напомнить о нём (день не сдвигается);
    None      — ещё рано или сегодня уже отправляли.
    """
    if not on_program(user):
        return None
    if now.hour < task_hour:
        return None
    if user.get("last_task_sent_on") == now.date().isoformat():
        return None
    if user.get("day_done"):
        return "advance" if user.get("current_day", 0) < TOTAL_DAYS else None
    return "resend"


def evening_reminder_due(user: dict, now: datetime, reminder_hour: int) -> bool:
    """B5: в 20:00 напомнить, если задание дня не отмечено (один раз в день)."""
    return (
        on_program(user)
        and not user.get("day_done")
        and now.hour >= reminder_hour
        and user.get("last_reminder_on") != now.date().isoformat()
    )


def inactive_signal_due(user: dict, today: date, inactive_days: int) -> bool:
    """B6: N дней без отметок — один сигнал наставнику на каждый такой период."""
    return (
        on_program(user)
        and not user.get("inactive_notified")
        and days_between(user.get("last_active_on"), today) >= inactive_days
    )


def weekly_rating_due(user: dict, now: datetime, rating_hour: int) -> bool:
    """B10: рейтинг недели по понедельникам для тех, у кого есть команда."""
    return (
        user.get("role") in {"partner", "leader"}
        and now.weekday() == 0
        and now.hour >= rating_hour
        and user.get("last_rating_sent_on") != now.date().isoformat()
    )


def contacts_check_due(user: dict, now: datetime, contacts_hour: int) -> bool:
    return now.hour >= contacts_hour and user.get("last_contacts_check_on") != now.date().isoformat()


def progress_bar(done: int, total: int = TOTAL_DAYS, width: int = 10) -> str:
    filled = round(width * done / total) if total else 0
    return "▓" * filled + "░" * (width - filled)


def activity_label(last_active_on: str | None, today: date) -> str:
    if not last_active_on:
        return "ещё не отмечался"
    days = days_between(last_active_on, today)
    if days == 0:
        return "сегодня"
    if days == 1:
        return "вчера"
    return f"{days} дн. назад"


def expected_days(started_on: str | None, today: date) -> int:
    """Сколько заданий человек мог выполнить с начала программы (не больше 30)."""
    if not started_on:
        return 0
    return min(days_between(started_on, today) + 1, TOTAL_DAYS)
