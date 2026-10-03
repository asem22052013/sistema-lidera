"""B3, B4, B9: задание дня, «Выполнено», прогресс, выпуск и переход в наставники."""
from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from .. import keyboards as kb
from .. import texts
from ..config import Config
from ..db import Database
from ..services import complete_day, display_name, invite_link, progress_text, safe_send, send_task

router = Router(name="newbie")


@router.message(Command("task"))
@router.message(F.text == kb.BTN_TASK)
async def show_task(message: Message, db: Database, cfg: Config, bot: Bot) -> None:
    user = await db.get_user(message.from_user.id)
    if not user or user.get("role") != "newbie" or not user.get("current_day"):
        await message.answer("Программа «30 дней» для новичков. Начать — /start")
        return
    if user["status"] == "trial_ended":
        await message.answer(texts.TRIAL_ENDED, reply_markup=kb.pro_kb(cfg.pro_url))
        return
    if user["status"] == "graduate":
        await message.answer("Ты уже выпускник программы 🎓 Хочешь вести новичков?", reply_markup=kb.graduate_kb())
        return
    if user["day_done"]:
        await message.answer(texts.ALREADY_DONE_TODAY.format(day=user["current_day"], hour=cfg.task_hour))
        return
    await send_task(bot, user)


@router.callback_query(F.data.startswith("done:"))
async def on_done(cb: CallbackQuery, db: Database, cfg: Config, bot: Bot) -> None:
    user = await db.get_user(cb.from_user.id)
    if not user:
        await cb.answer("Сначала нажми /start", show_alert=True)
        return
    day = int(cb.data.split(":")[1])
    was_open = user["current_day"] == day and not user["day_done"] and user["status"] == "active"
    reply = await complete_day(bot, db, cfg, user, day)
    if was_open:
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await cb.message.answer(reply)
        await cb.answer("Отмечено ✅")
    else:
        await cb.answer(reply, show_alert=True)


@router.message(Command("progress"))
@router.message(F.text == kb.BTN_PROGRESS)
async def show_progress(message: Message, db: Database, cfg: Config) -> None:
    user = await db.get_user(message.from_user.id)
    if not user or not user.get("current_day"):
        await message.answer("Ты ещё не начал(а) программу «30 дней». Начать — /start")
        return
    await message.answer(await progress_text(db, cfg, user))


@router.callback_query(F.data == "become_mentor")
async def become_mentor(cb: CallbackQuery, db: Database, cfg: Config, bot: Bot) -> None:
    user = await db.get_user(cb.from_user.id)
    if not user or user.get("status") != "graduate":
        await cb.answer("Это доступно выпускникам программы", show_alert=True)
        return
    await db.update_user(user["tg_id"], role="partner")
    user = await db.get_user(user["tg_id"])
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(
        "🙌 Теперь ты наставник!\n\n"
        + texts.INVITE_LINK.format(link=await invite_link(bot, user["tg_id"]), max=cfg.max_mentees),
        reply_markup=kb.main_menu(user),
    )
    if user.get("mentor_id"):
        await safe_send(bot, user["mentor_id"], f"🙌 {display_name(user)} стал(а) наставником.")
    await cb.answer()
