"""Действия, которые нужны и обработчикам, и планировщику."""
from __future__ import annotations

import logging
from datetime import timedelta
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from . import keyboards as kb
from . import texts
from .config import Config
from .db import Database
from .logic import TOTAL_DAYS, activity_label, days_between, local_now, progress_bar
from .program import PROGRAM, task_message

log = logging.getLogger(__name__)


def user_tz(user: dict, cfg: Config) -> int:
    return user["tz_offset"] if user.get("tz_offset") is not None else cfg.default_tz_offset


def user_now(user: dict, cfg: Config):
    return local_now(user_tz(user, cfg))


def display_name(user: dict) -> str:
    name = user.get("full_name") or (f"@{user['username']}" if user.get("username") else str(user["tg_id"]))
    return escape(name)


async def safe_send(bot: Bot, chat_id: int, text: str, **kwargs) -> bool:
    try:
        await bot.send_message(chat_id, text, **kwargs)
        return True
    except (TelegramForbiddenError, TelegramBadRequest) as e:
        log.warning("Не удалось отправить сообщение %s: %s", chat_id, e)
        return False


def split_message(text: str, limit: int = 3800) -> list[str]:
    parts, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > limit:
            parts.append(current)
            current = ""
        current += line + "\n"
    if current.strip():
        parts.append(current)
    return parts


async def invite_link(bot: Bot, tg_id: int) -> str:
    me = await bot.me()
    return f"https://t.me/{me.username}?start=m{tg_id}"


def compute_access(cfg: Config, mentor_id: int | None) -> int:
    return 1 if cfg.free_access or mentor_id else 0


# --- программа «30 дней» ---

async def send_task(bot: Bot, user: dict, prefix: str = "") -> bool:
    day = user["current_day"]
    task = PROGRAM[day]
    return await safe_send(bot, user["tg_id"], prefix + task_message(day), reply_markup=kb.task_kb(day, task["video"]))


async def start_program(bot: Bot, db: Database, cfg: Config, tg_id: int, goal: str, mentor_id: int | None) -> None:
    user = await db.get_user(tg_id)
    now = user_now(user, cfg)
    today = now.date().isoformat()
    has_access = max(user.get("has_access") or 0, compute_access(cfg, mentor_id))
    await db.update_user(
        tg_id, role="newbie", status="active", goal=goal, mentor_id=mentor_id, has_access=has_access,
        current_day=1, day_done=0, program_started_on=today, last_task_sent_on=today, last_active_on=today,
        inactive_notified=0,
        # Если стартовали вечером, не напоминаем о первом задании в тот же вечер.
        last_reminder_on=today if now.hour >= cfg.reminder_hour - 2 else None,
    )
    user = await db.get_user(tg_id)
    await safe_send(
        bot, tg_id,
        texts.PROGRAM_STARTED.format(hour=cfg.task_hour, rem=cfg.reminder_hour, tz=user_tz(user, cfg)),
        reply_markup=kb.main_menu(user),
    )
    await send_task(bot, user)

    if mentor_id:
        await safe_send(bot, mentor_id, texts.NEW_MENTEE.format(name=display_name(user), goal=escape(goal)),
                        reply_markup=kb.write_to_kb(tg_id, user.get("full_name") or "новичок"))
        n = await db.count_active_mentees(mentor_id)
        if n > cfg.max_mentees:
            await safe_send(bot, mentor_id, texts.MENTOR_OVERLOAD.format(n=n, max=cfg.max_mentees))


async def complete_day(bot: Bot, db: Database, cfg: Config, user: dict, day: int) -> str:
    """Отмечает день выполненным. Возвращает текст ответа пользователю."""
    if user.get("role") != "newbie" or user.get("status") not in {"active", "trial_ended", "graduate"}:
        return "Программа сейчас не активна."
    if day != user["current_day"]:
        return f"Это задание уже в прошлом. Сейчас открыт день {user['current_day']}."
    if user["day_done"]:
        return texts.ALREADY_DONE_TODAY.format(day=day, hour=cfg.task_hour)
    if user["status"] != "active":
        return "Программа сейчас не активна."

    today = user_now(user, cfg).date().isoformat()
    await db.add_completion(user["tg_id"], day, today)
    await db.update_user(user["tg_id"], day_done=1, last_active_on=today, inactive_notified=0)
    done = await db.completion_count(user["tg_id"])

    if day >= TOTAL_DAYS:
        await db.update_user(user["tg_id"], status="graduate", graduated_on=today)
        await safe_send(bot, user["tg_id"],
                        texts.GRADUATE.format(goal=escape(user.get("goal") or "—"), done=done),
                        reply_markup=kb.graduate_kb())
        if user.get("mentor_id"):
            await safe_send(bot, user["mentor_id"], texts.GRADUATE_TO_MENTOR.format(name=display_name(user)))
        return "🎓 Последний день выполнен!"

    if not user.get("has_access"):
        await db.update_user(user["tg_id"], status="trial_ended")
        await safe_send(bot, user["tg_id"], texts.TRIAL_ENDED, reply_markup=kb.pro_kb(cfg.pro_url))
        return "✅ День 1 выполнен!"

    return texts.DAY_DONE.format(day=day, bar=progress_bar(done), done=done, hour=cfg.task_hour)


async def progress_text(db: Database, cfg: Config, user: dict) -> str:
    done = await db.completion_count(user["tg_id"])
    mentor = await db.get_user(user["mentor_id"]) if user.get("mentor_id") else None
    state = "✅ выполнено" if user["day_done"] else "⏳ ждёт отметки"
    return (
        f"<b>Программа «30 дней»</b>\n"
        f"Статус: {texts.STATUS_NAMES.get(user['status'], user['status'])}\n"
        f"Сейчас: день {user['current_day']} из 30 — {state}\n"
        f"{progress_bar(done)} {done}/30\n\n"
        f"🎯 Цель: <i>{escape(user.get('goal') or '—')}</i>\n"
        f"🧭 Наставник: {display_name(mentor) if mentor else 'не указан'}"
    )


# --- команда и рейтинг (B7, B10) ---

async def team_text(db: Database, cfg: Config, root: dict) -> str:
    members = await db.downline(root["tg_id"])
    if not members:
        return ("В твоей команде пока никого нет.\n"
                "Отправь новичкам свою ссылку — кнопка «🔗 Моя ссылка».")

    today = user_now(root, cfg).date()
    counts = await db.all_completion_counts()
    names = {root["tg_id"]: "ты"}
    names.update({u["tg_id"]: display_name(u) for u, _ in members})

    on_program = [u for u, _ in members if u["role"] == "newbie" and u["status"] == "active"]
    graduates = [u for u, _ in members if u["status"] == "graduate"]
    mentors = {u["mentor_id"] for u, _ in members}
    lagging = {u["tg_id"] for u in on_program if days_between(u.get("last_active_on"), today) >= cfg.inactive_days}

    lines = [
        f"<b>👥 Команда: {len(members)} чел.</b>",
        f"На программе: {len(on_program)} · Выпускники: {len(graduates)} · Наставников: {len(mentors)}",
        f"🔴 Без отметок {cfg.inactive_days}+ дня: {len(lagging)}",
        "",
    ]
    for u, depth in members:
        indent = "  " * (depth - 1)
        if u["role"] == "newbie" and u["status"] in {"active", "trial_ended"}:
            flag = "🔴" if u["tg_id"] in lagging else ("✅" if u["day_done"] else "🟡")
            info = (f"день {u['current_day']}/30, выполнено {counts.get(u['tg_id'], 0)}, "
                    f"активность: {activity_label(u.get('last_active_on'), today)}")
        elif u["status"] == "graduate":
            flag, info = "🎓", f"выпускник, выполнено {counts.get(u['tg_id'], 0)}/30"
        else:
            flag, info = "▫️", texts.ROLE_NAMES.get(u["role"], "")
        mentor = f" ← {names.get(u['mentor_id'], '?')}" if depth > 1 else ""
        lines.append(f"{indent}{flag} <b>{display_name(u)}</b>{mentor}\n{indent}    {info}")

    overloaded = []
    for mentor_id in mentors:
        n = sum(1 for u in on_program if u["mentor_id"] == mentor_id)
        if n > cfg.max_mentees:
            overloaded.append(f"{names.get(mentor_id, '?')} ({n})")
    if overloaded:
        lines += ["", f"⚠️ У наставников больше {cfg.max_mentees} новичков: " + ", ".join(overloaded)]
    lines += ["", "✅ сегодня выполнено · 🟡 ждёт отметки · 🔴 нужен контакт · 🎓 выпускник"]
    return "\n".join(lines)


async def rating_text(db: Database, cfg: Config, root: dict) -> str | None:
    members = [u for u, _ in await db.downline(root["tg_id"]) if u["role"] == "newbie"]
    if not members:
        return None
    since = (user_now(root, cfg).date() - timedelta(days=7)).isoformat()
    counts = await db.completions_since([u["tg_id"] for u in members], since)
    ranked = sorted(members, key=lambda u: counts.get(u["tg_id"], 0), reverse=True)
    medals = ["🥇", "🥈", "🥉"]
    lines = ["<b>🏆 Рейтинг недели</b> — выполненные задания за 7 дней", ""]
    for i, u in enumerate(ranked[:10]):
        place = medals[i] if i < 3 else f"{i + 1}."
        lines.append(f"{place} {display_name(u)} — {counts.get(u['tg_id'], 0)}")
    zero = sum(1 for u in members if not counts.get(u["tg_id"]))
    if zero:
        lines += ["", f"Без отметок за неделю: {zero}. Им нужна поддержка наставника."]
    return "\n".join(lines)
