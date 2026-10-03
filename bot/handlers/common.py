"""Помощь, часовой пояс, политика, удаление данных и ответ на всё остальное."""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from .. import keyboards as kb
from .. import texts
from ..config import Config
from ..db import Database

router = Router(name="common")


@router.message(Command("help", "menu"))
@router.message(F.text == kb.BTN_HELP)
async def cmd_help(message: Message, db: Database) -> None:
    user = await db.get_user(message.from_user.id)
    if not user or not user.get("role"):
        await message.answer("Нажми /start, чтобы начать.")
        return
    text = texts.HELP_MENTOR if user["role"] in {"partner", "leader"} else texts.HELP_NEWBIE
    await message.answer(text, reply_markup=kb.main_menu(user))


@router.message(Command("tz"))
async def cmd_tz(message: Message, db: Database, cfg: Config) -> None:
    user = await db.get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала нажми /start")
        return
    current = user["tz_offset"] if user["tz_offset"] is not None else cfg.default_tz_offset
    await message.answer(
        f"Сейчас твой часовой пояс: UTC+{current}.\n"
        "Казахстан — UTC+5, Москва — UTC+3, Бишкек — UTC+6, Ташкент — UTC+5.\nВыбери свой:",
        reply_markup=kb.tz_kb(),
    )


@router.callback_query(F.data.startswith("tz:"))
async def on_tz(cb: CallbackQuery, db: Database, cfg: Config) -> None:
    offset = int(cb.data.split(":")[1])
    await db.update_user(cb.from_user.id, tz_offset=offset)
    await cb.message.edit_text(
        f"✅ Часовой пояс: UTC+{offset}. Задания — в {cfg.task_hour}:00, напоминания — в {cfg.reminder_hour}:00 "
        "по твоему времени."
    )
    await cb.answer()


@router.message(Command("privacy"))
async def cmd_privacy(message: Message, cfg: Config) -> None:
    text = texts.CONSENT.split("\n\nНажимая")[0]
    if cfg.privacy_url:
        text += f"\n\nПолный текст политики: {cfg.privacy_url}"
    await message.answer(text)


@router.message(Command("delete_me"))
async def cmd_delete(message: Message) -> None:
    await message.answer(
        "Удалить все твои данные: профиль, прогресс программы и контакты? Это необратимо.",
        reply_markup=kb.delete_confirm_kb(),
    )


@router.callback_query(F.data.startswith("delete_me:"))
async def on_delete(cb: CallbackQuery, state: FSMContext, db: Database) -> None:
    if cb.data.endswith(":yes"):
        await db.delete_user(cb.from_user.id)
        await state.clear()
        await cb.message.edit_text("Данные удалены. Если захочешь вернуться — /start.")
        await cb.message.answer("До встречи 👋", reply_markup=ReplyKeyboardRemove())
    else:
        await cb.message.edit_text("Отменено, всё на месте.")
    await cb.answer()


@router.message(F.text)
async def fallback(message: Message, db: Database) -> None:
    """Бот не даёт медицинских советов: на вопросы о здоровье — дисклеймер."""
    text = message.text.lower()
    if any(word in text for word in texts.MEDICAL_TRIGGERS):
        await message.answer(texts.MEDICAL_DISCLAIMER)
        return
    user = await db.get_user(message.from_user.id)
    if not user or not user.get("role"):
        await message.answer("Нажми /start, чтобы начать.")
        return
    await message.answer("Я пока понимаю только кнопки меню 🙂 Вопросы задавай наставнику или в чате клуба.",
                         reply_markup=kb.main_menu(user))
