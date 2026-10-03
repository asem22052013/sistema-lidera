"""Админ: метрики проекта (модуль 6 и цели PRD) и ручная выдача доступа после оплаты."""
from datetime import timedelta

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from .. import texts
from ..config import Config
from ..db import Database
from ..logic import days_between, expected_days, local_now
from ..services import display_name, safe_send

router = Router(name="admin")


def _is_admin(message: Message, cfg: Config) -> bool:
    return message.from_user.id in cfg.admin_ids


async def _resolve(db: Database, arg: str | None) -> dict | None:
    arg = (arg or "").strip()
    if not arg:
        return None
    if arg.lstrip("-").isdigit():
        return await db.get_user(int(arg))
    return await db.find_by_username(arg)


@router.message(Command("stats"))
async def cmd_stats(message: Message, db: Database, cfg: Config) -> None:
    if not _is_admin(message, cfg):
        return
    users = await db.all_users()
    counts = await db.all_completion_counts()
    today = local_now(cfg.default_tz_offset).date()
    month_ago = (today - timedelta(days=30)).isoformat()

    by_role = {r: sum(1 for u in users if u["role"] == r) for r in texts.ROLE_NAMES}
    newbies = [u for u in users if u["role"] == "newbie" and u.get("program_started_on")]
    on_program = [u for u in newbies if u["status"] == "active"]
    graduates = [u for u in users if u["status"] == "graduate"]

    # Удержание: из тех, кто стартовал 30+ дней назад, — выпускники или активные за последнюю неделю.
    cohort = [u for u in newbies if days_between(u["program_started_on"], today) >= 30]
    retained = [u for u in cohort
                if u["status"] == "graduate" or days_between(u.get("last_active_on"), today) <= 7]
    retention = f"{len(retained)}/{len(cohort)} ({round(100 * len(retained) / len(cohort))}%)" if cohort else "нет данных"

    expected = sum(expected_days(u["program_started_on"], today) for u in newbies if u["status"] != "trial_ended")
    done = sum(counts.get(u["tg_id"], 0) for u in newbies if u["status"] != "trial_ended")
    completion = f"{round(100 * done / expected)}%" if expected else "нет данных"

    lagging = [u for u in on_program if days_between(u.get("last_active_on"), today) >= cfg.inactive_days]
    mentors = {u["mentor_id"] for u in newbies if u.get("mentor_id")}
    new_month = sum(1 for u in users if (u.get("created_at") or "")[:10] >= month_ago)
    contacts = await db.contact_status_counts()
    trial = sum(1 for u in users if u["status"] == "trial_ended")

    await message.answer(
        "<b>📊 Метрики «Система Лидера»</b>\n\n"
        f"Пользователи: {len(users)} (новых за 30 дней: {new_month})\n"
        f"Новички {by_role['newbie']} · Партнёры {by_role['partner']} · Лидеры {by_role['leader']}\n\n"
        f"<b>Программа «30 дней»</b>\n"
        f"Сейчас на программе: {len(on_program)}\n"
        f"🔴 Без отметок {cfg.inactive_days}+ дня: {len(lagging)}\n"
        f"Выполнение заданий: {completion}\n"
        f"Активны через 30 дней: {retention}\n"
        f"Выпускники: {len(graduates)}\n"
        f"Пробный день без доступа: {trial}\n\n"
        f"<b>Структура</b>\n"
        f"Наставников с новичками: {len(mentors)}\n"
        f"Контакты-клиенты: {contacts.get('Клиент', 0)} · Контакты-партнёры: {contacts.get('Партнёр', 0)}"
    )


@router.message(Command("grant"))
async def cmd_grant(message: Message, command: CommandObject, db: Database, cfg: Config, bot: Bot) -> None:
    """Выдать полный доступ к программе после оплаты PRO: /grant 123456789 или /grant @username."""
    if not _is_admin(message, cfg):
        return
    user = await _resolve(db, command.args)
    if not user:
        await message.answer("Не нашёл пользователя. Формат: /grant 123456789 или /grant @username")
        return
    await db.update_user(user["tg_id"], has_access=1)
    if user["status"] == "trial_ended":
        await db.update_user(user["tg_id"], status="active")
    await message.answer(f"✅ Доступ выдан: {display_name(user)}")
    await safe_send(bot, user["tg_id"],
                    "💎 Доступ к программе «30 дней» открыт! Следующее задание придёт утром в "
                    f"{cfg.task_hour}:00.")


@router.message(Command("revoke"))
async def cmd_revoke(message: Message, command: CommandObject, db: Database, cfg: Config) -> None:
    if not _is_admin(message, cfg):
        return
    user = await _resolve(db, command.args)
    if not user:
        await message.answer("Не нашёл пользователя. Формат: /revoke 123456789 или /revoke @username")
        return
    await db.update_user(user["tg_id"], has_access=0)
    await message.answer(f"Доступ отозван: {display_name(user)}. Действует со следующего выполненного дня.")
