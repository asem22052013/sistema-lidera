"""B1, B2: /start, согласие, выбор роли, цель и наставник, лид-магнит «ПЛАН»."""
from aiogram import Bot, F, Router
from aiogram.filters import CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from .. import keyboards as kb
from .. import texts
from ..config import Config
from ..db import Database
from ..services import compute_access, display_name, invite_link, send_task, start_program

router = Router(name="onboarding")


class Onboarding(StatesGroup):
    goal = State()
    mentor = State()


def _parse_payload(args: str | None, self_id: int) -> tuple[int | None, str | None]:
    args = (args or "").strip()
    if args.startswith("m") and args[1:].isdigit():
        mentor_id = int(args[1:])
        return (None if mentor_id == self_id else mentor_id), "invite"
    if args.lower() == "plan":
        return None, "plan"
    return None, args or None


def _is_mentor(user: dict | None) -> bool:
    return bool(user) and user.get("role") in {"partner", "leader"}


async def _begin(message: Message, state: FSMContext, db: Database, cfg: Config, bot: Bot,
                 mentor_id: int | None, source: str | None) -> None:
    tg = message.from_user
    user = await db.get_user(tg.id)

    if user and user.get("role"):
        await db.update_user(tg.id, username=tg.username, full_name=tg.full_name)
        # Пришёл по ссылке наставника, а наставника ещё нет — закрепляем.
        mentor = await db.get_user(mentor_id) if mentor_id else None
        if _is_mentor(mentor) and not user.get("mentor_id"):
            access = max(user.get("has_access") or 0, compute_access(cfg, mentor_id))
            await db.update_user(tg.id, mentor_id=mentor_id, has_access=access)
            if user["status"] == "trial_ended" and access:
                await db.update_user(tg.id, status="active")
            await message.answer(f"Твой наставник теперь: <b>{display_name(mentor)}</b>.")
        user = await db.get_user(tg.id)
        await message.answer("С возвращением! 👋", reply_markup=kb.main_menu(user))
        return

    await state.update_data(mentor_id=mentor_id, source=source)
    if user:  # согласие уже дано, роль не выбрана
        await message.answer(texts.CHOOSE_ROLE, reply_markup=kb.role_kb())
        return
    await message.answer(texts.WELCOME)
    await message.answer(texts.CONSENT, reply_markup=kb.consent_kb(cfg.privacy_url))


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, state: FSMContext,
                    db: Database, cfg: Config, bot: Bot) -> None:
    await state.clear()
    mentor_id, source = _parse_payload(command.args, message.from_user.id)
    await _begin(message, state, db, cfg, bot, mentor_id, source)


def _is_plan_word(message: Message) -> bool:
    return (message.text or "").strip().strip("!.").lower() == "план"


@router.message(StateFilter(None), _is_plan_word)
async def lead_magnet_plan(message: Message, state: FSMContext, db: Database, cfg: Config, bot: Bot) -> None:
    """Лид-магнит: человек пишет слово ПЛАН и получает день 1 программы."""
    user = await db.get_user(message.from_user.id)
    if user and user.get("role") == "newbie" and user["status"] == "active":
        await send_task(bot, user)
        return
    await _begin(message, state, db, cfg, bot, None, "plan")


@router.callback_query(F.data == "consent:yes")
async def on_consent(cb: CallbackQuery, db: Database, cfg: Config) -> None:
    tg = cb.from_user
    await db.create_user(tg.id, tg.username, tg.full_name, cfg.default_tz_offset, None)
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(texts.CHOOSE_ROLE, reply_markup=kb.role_kb())
    await cb.answer("Спасибо!")


@router.callback_query(F.data.startswith("role:"))
async def on_role(cb: CallbackQuery, state: FSMContext, db: Database, cfg: Config, bot: Bot) -> None:
    user = await db.get_user(cb.from_user.id)
    if not user:
        await cb.answer("Сначала нажми /start", show_alert=True)
        return
    if user.get("role"):
        await cb.answer("Роль уже выбрана")
        return
    role = cb.data.split(":", 1)[1]
    data = await state.get_data()
    await db.update_user(cb.from_user.id, source=data.get("source"))
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.answer()

    if role == "newbie":
        await state.set_state(Onboarding.goal)
        await cb.message.answer(texts.ASK_GOAL)
        return

    # Партнёр или лидер: сразу получает ссылку-приглашение. Если пришёл по ссылке лидера — встаёт в его структуру.
    mentor = await db.get_user(data["mentor_id"]) if data.get("mentor_id") else None
    await db.update_user(cb.from_user.id, role=role, status="active", has_access=1,
                         mentor_id=mentor["tg_id"] if _is_mentor(mentor) else None)
    await state.clear()
    user = await db.get_user(cb.from_user.id)
    await cb.message.answer(
        f"Готово! Ты — <b>{texts.ROLE_NAMES[role]}</b>.\n\n"
        + texts.INVITE_LINK.format(link=await invite_link(bot, user["tg_id"]), max=cfg.max_mentees),
        reply_markup=kb.main_menu(user),
    )
    await cb.message.answer(texts.HELP_MENTOR)


@router.message(Onboarding.goal, F.text)
async def on_goal(message: Message, state: FSMContext, db: Database) -> None:
    goal = message.text.strip()[:500]
    if len(goal) < 5:
        await message.answer("Напиши цель чуть подробнее — хотя бы одно предложение.")
        return
    await state.update_data(goal=goal)
    data = await state.get_data()
    mentor = await db.get_user(data["mentor_id"]) if data.get("mentor_id") else None
    if _is_mentor(mentor):
        await message.answer(f"Твой наставник — <b>{display_name(mentor)}</b>?",
                             reply_markup=kb.mentor_confirm_kb(mentor["tg_id"]))
        return
    await state.set_state(Onboarding.mentor)
    await message.answer(texts.ASK_MENTOR, reply_markup=kb.mentor_skip_kb())


@router.message(Onboarding.mentor, F.text)
async def on_mentor_username(message: Message, state: FSMContext, db: Database, cfg: Config, bot: Bot) -> None:
    mentor = await db.find_by_username(message.text.strip())
    if not _is_mentor(mentor) or mentor["tg_id"] == message.from_user.id:
        await message.answer(texts.MENTOR_NOT_FOUND, reply_markup=kb.mentor_skip_kb())
        return
    data = await state.get_data()
    await state.clear()
    await message.answer(f"Наставник: <b>{display_name(mentor)}</b> ✅")
    await start_program(bot, db, cfg, message.from_user.id, data["goal"], mentor["tg_id"])


@router.callback_query(F.data.startswith("mentor:"))
async def on_mentor_choice(cb: CallbackQuery, state: FSMContext, db: Database, cfg: Config, bot: Bot) -> None:
    data = await state.get_data()
    if "goal" not in data:
        await cb.answer("Начни заново: /start", show_alert=True)
        return
    parts = cb.data.split(":")
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.answer()

    if parts[1] == "other":
        await state.set_state(Onboarding.mentor)
        await cb.message.answer(texts.ASK_MENTOR, reply_markup=kb.mentor_skip_kb())
        return

    mentor_id = None
    if parts[1] == "ok":
        mentor = await db.get_user(int(parts[2]))
        mentor_id = mentor["tg_id"] if _is_mentor(mentor) else None
    await state.clear()
    await start_program(bot, db, cfg, cb.from_user.id, data["goal"], mentor_id)


@router.message(Onboarding.goal)
@router.message(Onboarding.mentor)
async def on_onboarding_other(message: Message) -> None:
    await message.answer("Пожалуйста, ответь текстом 🙂")
