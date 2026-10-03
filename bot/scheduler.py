"""Планировщик: раз в минуту проверяет всех пользователей по их местному времени.

B3 — задание дня в 9:00, B5 — напоминание в 20:00, B6 — сигнал наставнику после 3 дней без отметок,
B8 — напоминания по контактам, B10 — рейтинг недели по понедельникам.
Флаги «отправлено сегодня» ставятся до отправки, поэтому после перезапуска бот не дублирует сообщения,
а пропущенное (бот был выключен в 9:00) отправит, как только запустится.
"""
import asyncio
import logging
from datetime import timedelta
from html import escape

from aiogram import Bot

from . import keyboards as kb
from . import texts
from .config import Config
from .db import Database
from .logic import (contacts_check_due, days_between, evening_reminder_due, inactive_signal_due,
                    morning_action, weekly_rating_due)
from .program import PROGRAM
from .services import display_name, rating_text, safe_send, send_task, user_now

log = logging.getLogger(__name__)


async def run_scheduler(bot: Bot, db: Database, cfg: Config) -> None:
    while True:
        try:
            await tick(bot, db, cfg)
        except Exception:
            log.exception("Ошибка в планировщике")
        await asyncio.sleep(60)


async def tick(bot: Bot, db: Database, cfg: Config) -> None:
    for user in await db.all_users():
        try:
            await process_user(bot, db, cfg, user)
        except Exception:
            log.exception("Ошибка при обработке пользователя %s", user["tg_id"])


async def process_user(bot: Bot, db: Database, cfg: Config, user: dict) -> None:
    now = user_now(user, cfg)
    today = now.date().isoformat()
    uid = user["tg_id"]

    action = morning_action(user, now, cfg.task_hour)
    if action == "advance":
        await db.update_user(uid, current_day=user["current_day"] + 1, day_done=0, last_task_sent_on=today)
        await send_task(bot, await db.get_user(uid))
        return  # остальные проверки — на следующей минуте, с обновлёнными данными
    if action == "resend":
        await db.update_user(uid, last_task_sent_on=today)
        await send_task(bot, user, prefix=texts.RESEND_PREFIX.format(day=user["current_day"]))

    if evening_reminder_due(user, now, cfg.reminder_hour):
        await db.update_user(uid, last_reminder_on=today)
        day = user["current_day"]
        await safe_send(bot, uid, texts.EVENING_REMINDER.format(day=day, title=PROGRAM[day]["title"]),
                        reply_markup=kb.task_kb(day, PROGRAM[day]["video"]))

    if inactive_signal_due(user, now.date(), cfg.inactive_days):
        await db.update_user(uid, inactive_notified=1)
        days = days_between(user["last_active_on"], now.date())
        await safe_send(bot, uid, texts.INACTIVE_TO_NEWBIE.format(days=days, day=user["current_day"]))
        if user.get("mentor_id"):
            await safe_send(
                bot, user["mentor_id"],
                texts.INACTIVE_TO_MENTOR.format(name=display_name(user), days=days, day=user["current_day"]),
                reply_markup=kb.write_to_kb(uid, user.get("full_name") or "новичок"),
            )

    if contacts_check_due(user, now, cfg.contacts_hour):
        await db.update_user(uid, last_contacts_check_on=today)
        for contact in await db.due_contacts(uid, today):
            await safe_send(bot, uid,
                            f"⏰ Пора сделать касание: <b>{escape(contact['name'])}</b> ({contact['status']}).\n"
                            "Не «ну что, надумал?», а забота или полезное.",
                            reply_markup=kb.contact_due_kb(contact["id"]))
            # Без ответа напоминание повторится через день, а не каждую минуту.
            await db.update_contact(uid, contact["id"], remind_on=(now.date() + timedelta(days=1)).isoformat())

    if weekly_rating_due(user, now, cfg.rating_hour):
        await db.update_user(uid, last_rating_sent_on=today)
        text = await rating_text(db, cfg, user)
        if text:
            await safe_send(bot, uid, text)
