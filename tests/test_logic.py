import re
from datetime import date, datetime, timedelta, timezone

from bot.logic import (evening_reminder_due, inactive_signal_due, local_now, morning_action, progress_bar,
                       weekly_rating_due)
from bot.program import PROGRAM

KZ = timezone(timedelta(hours=5))


def at(day: int, hour: int) -> datetime:
    return datetime(2026, 11, day, hour, 0, tzinfo=KZ)


def newbie(**kw) -> dict:
    base = dict(role="newbie", status="active", current_day=1, day_done=0,
                last_task_sent_on="2026-11-02", last_reminder_on=None, last_active_on="2026-11-02",
                inactive_notified=0)
    base.update(kw)
    return base


def test_local_now_uses_offset():
    utc = datetime(2026, 11, 2, 4, 0, tzinfo=timezone.utc)
    assert local_now(5, utc).hour == 9


def test_morning_waits_for_task_hour():
    assert morning_action(newbie(day_done=1), at(3, 8), 9) is None


def test_morning_advances_when_done():
    assert morning_action(newbie(day_done=1), at(3, 9), 9) == "advance"


def test_morning_resends_when_not_done():
    assert morning_action(newbie(), at(3, 9), 9) == "resend"


def test_morning_only_once_a_day():
    assert morning_action(newbie(day_done=1, last_task_sent_on="2026-11-03"), at(3, 12), 9) is None


def test_no_advance_after_day_30():
    assert morning_action(newbie(current_day=30, day_done=1), at(3, 9), 9) is None


def test_evening_reminder():
    assert evening_reminder_due(newbie(), at(2, 20), 20)
    assert not evening_reminder_due(newbie(), at(2, 19), 20)
    assert not evening_reminder_due(newbie(day_done=1), at(2, 20), 20)
    assert not evening_reminder_due(newbie(last_reminder_on="2026-11-02"), at(2, 21), 20)


def test_inactive_signal_after_three_days():
    assert not inactive_signal_due(newbie(), date(2026, 11, 4), 3)
    assert inactive_signal_due(newbie(), date(2026, 11, 5), 3)
    assert not inactive_signal_due(newbie(inactive_notified=1), date(2026, 11, 5), 3)


def test_weekly_rating_on_monday_only():
    leader = dict(role="leader", last_rating_sent_on=None)
    assert weekly_rating_due(leader, at(2, 10), 10)       # 2 ноября 2026 — понедельник
    assert not weekly_rating_due(leader, at(3, 10), 10)
    assert not weekly_rating_due(dict(role="newbie"), at(2, 10), 10)


def test_progress_bar():
    assert progress_bar(0) == "░" * 10
    assert progress_bar(30) == "▓" * 10
    assert progress_bar(15) == "▓" * 5 + "░" * 5


def test_program_has_30_days_and_valid_html():
    assert sorted(PROGRAM) == list(range(1, 31))
    for day, task in PROGRAM.items():
        text = task["text"]
        for tag in ("b", "i"):
            assert text.count(f"<{tag}>") == text.count(f"</{tag}>"), f"день {day}: незакрытый <{tag}>"


def test_program_has_no_stop_words():
    """Стоп-слова допустимы только в дне 8, где их разбирают как запрещённые."""
    stop = re.compile(r"\bлечит|\bвылечи|лекарств|детокс|гарантированн", re.IGNORECASE)
    for day, task in PROGRAM.items():
        if day == 8:
            continue
        for match in stop.finditer(task["text"]):
            context = task["text"][max(0, match.start() - 30):match.end()]
            # Разрешено только в формулировках-запретах («без слов «лечит»», «не про «результаты лечения»»)
            assert "без" in context or "не про" in context, f"день {day}: стоп-слово «{match.group()}»"
