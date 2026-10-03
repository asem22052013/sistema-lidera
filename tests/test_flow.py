"""Сквозной сценарий без Telegram: фейковый бот записывает сообщения, время подменяется."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from bot import scheduler, services
from bot.config import Config
from bot.db import Database

KZ = timezone(timedelta(hours=5))
NEWBIE, MENTOR, LEADER = 100, 200, 300


class FakeBot:
    def __init__(self):
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text))

    async def me(self):
        return SimpleNamespace(username="sistema_lidera_bot")

    def to(self, chat_id) -> list[str]:
        return [t for c, t in self.sent if c == chat_id]


@pytest.fixture
def clock(monkeypatch):
    state = {"now": datetime(2026, 11, 2, 10, 0, tzinfo=KZ)}
    fake = lambda user, cfg: state["now"]  # noqa: E731
    monkeypatch.setattr(services, "user_now", fake)
    monkeypatch.setattr(scheduler, "user_now", fake)
    return state


@pytest.fixture
async def env(tmp_path):
    db = Database(str(tmp_path / "test.sqlite3"))
    await db.connect()
    cfg = Config(bot_token="x", free_access=False)
    bot = FakeBot()
    await db.create_user(LEADER, "leader", "Лидер", 5, None)
    await db.update_user(LEADER, role="leader", status="active", has_access=1)
    await db.create_user(MENTOR, "mentor", "Наставник", 5, None)
    await db.update_user(MENTOR, role="partner", status="active", has_access=1, mentor_id=LEADER)
    await db.create_user(NEWBIE, "newbie", "Новичок", 5, None)
    yield db, cfg, bot
    await db.close()


async def tick(env, clock, when: datetime):
    db, cfg, bot = env
    clock["now"] = when
    await scheduler.tick(bot, db, cfg)


@pytest.mark.asyncio
async def test_full_program_flow(env, clock):
    db, cfg, bot = env
    await services.start_program(bot, db, cfg, NEWBIE, "3 клиента, 1 партнёр", MENTOR)

    assert any("День 1 из 30" in t for t in bot.to(NEWBIE))
    assert any("присоединился новичок" in t for t in bot.to(MENTOR))
    user = await db.get_user(NEWBIE)
    assert user["has_access"] == 1  # новичок с наставником получает доступ

    # Вечером в день старта (после 20:00) — напоминание, так как стартовали утром и не отметили.
    await tick(env, clock, datetime(2026, 11, 2, 20, 5, tzinfo=KZ))
    assert any("Напоминаю про задание дня 1" in t for t in bot.to(NEWBIE))

    # Выполнил день 1.
    reply = await services.complete_day(bot, db, cfg, await db.get_user(NEWBIE), 1)
    assert "День 1 из 30 выполнен" in reply

    # Утро: приходит день 2.
    await tick(env, clock, datetime(2026, 11, 3, 9, 0, tzinfo=KZ))
    assert any("День 2 из 30" in t for t in bot.to(NEWBIE))
    assert (await db.get_user(NEWBIE))["current_day"] == 2

    # Повторный тик в то же утро ничего не дублирует.
    before = len(bot.sent)
    await tick(env, clock, datetime(2026, 11, 3, 9, 1, tzinfo=KZ))
    assert len(bot.sent) == before

    # Пропал на 3 дня → сигнал наставнику, один раз.
    await tick(env, clock, datetime(2026, 11, 6, 9, 0, tzinfo=KZ))
    signals = [t for t in bot.to(MENTOR) if "без отметок" in t]
    assert len(signals) == 1
    await tick(env, clock, datetime(2026, 11, 6, 12, 0, tzinfo=KZ))
    assert len([t for t in bot.to(MENTOR) if "без отметок" in t]) == 1

    # День не сдвигается, пока не выполнено: утром — повтор того же задания.
    assert (await db.get_user(NEWBIE))["current_day"] == 2


@pytest.mark.asyncio
async def test_graduation(env, clock):
    db, cfg, bot = env
    await services.start_program(bot, db, cfg, NEWBIE, "цель на 90 дней", MENTOR)
    for day in range(1, 31):
        user = await db.get_user(NEWBIE)
        assert user["current_day"] == day
        await services.complete_day(bot, db, cfg, user, day)
        await tick(env, clock, clock["now"] + timedelta(days=1))
    user = await db.get_user(NEWBIE)
    assert user["status"] == "graduate"
    assert await db.completion_count(NEWBIE) == 30
    assert any("выпускник" in t for t in bot.to(NEWBIE))
    assert any("завершил(а) программу" in t for t in bot.to(MENTOR))


@pytest.mark.asyncio
async def test_trial_without_mentor(env, clock):
    db, cfg, bot = env
    await services.start_program(bot, db, cfg, NEWBIE, "попробовать", None)
    await services.complete_day(bot, db, cfg, await db.get_user(NEWBIE), 1)
    assert (await db.get_user(NEWBIE))["status"] == "trial_ended"
    await tick(env, clock, datetime(2026, 11, 3, 9, 0, tzinfo=KZ))
    assert not any("День 2 из 30" in t for t in bot.to(NEWBIE))


@pytest.mark.asyncio
async def test_team_shows_whole_downline(env, clock):
    db, cfg, bot = env
    await services.start_program(bot, db, cfg, NEWBIE, "цель", MENTOR)
    text = await services.team_text(db, cfg, await db.get_user(LEADER))
    assert "Наставник" in text and "Новичок" in text
    assert "день 1/30" in text


@pytest.mark.asyncio
async def test_contact_reminder(env, clock):
    db, cfg, bot = env
    await db.update_user(NEWBIE, role="newbie", status="active")
    await db.add_contact(NEWBIE, "Айгерим", "Думает", "2026-11-05")
    await tick(env, clock, datetime(2026, 11, 4, 10, 0, tzinfo=KZ))
    assert not any("Айгерим" in t for t in bot.to(NEWBIE))
    await tick(env, clock, datetime(2026, 11, 5, 10, 0, tzinfo=KZ))
    assert any("Айгерим" in t for t in bot.to(NEWBIE))


@pytest.mark.asyncio
async def test_delete_user_detaches_mentees(env, clock):
    db, cfg, bot = env
    await services.start_program(bot, db, cfg, NEWBIE, "цель", MENTOR)
    await db.delete_user(MENTOR)
    assert await db.get_user(MENTOR) is None
    assert (await db.get_user(NEWBIE))["mentor_id"] is None
