"""B7, B10: /team для лидера и наставника, рейтинг недели, ссылка-приглашение."""
from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import LinkPreviewOptions, Message

from .. import keyboards as kb
from .. import texts
from ..config import Config
from ..db import Database
from ..services import invite_link, rating_text, split_message, team_text

router = Router(name="team")


async def _mentor_or_reject(message: Message, db: Database) -> dict | None:
    user = await db.get_user(message.from_user.id)
    if not user or user.get("role") not in {"partner", "leader"}:
        await message.answer("Этот раздел — для партнёров, наставников и лидеров.")
        return None
    return user


@router.message(Command("team"))
@router.message(F.text == kb.BTN_TEAM)
async def cmd_team(message: Message, db: Database, cfg: Config) -> None:
    user = await _mentor_or_reject(message, db)
    if user:
        for part in split_message(await team_text(db, cfg, user)):
            await message.answer(part)


@router.message(Command("rating"))
@router.message(F.text == kb.BTN_RATING)
async def cmd_rating(message: Message, db: Database, cfg: Config) -> None:
    user = await _mentor_or_reject(message, db)
    if user:
        await message.answer(await rating_text(db, cfg, user) or "В команде пока нет новичков на программе.")


@router.message(Command("link"))
@router.message(F.text == kb.BTN_LINK)
async def cmd_link(message: Message, db: Database, cfg: Config, bot: Bot) -> None:
    user = await _mentor_or_reject(message, db)
    if user:
        await message.answer(texts.INVITE_LINK.format(link=await invite_link(bot, user["tg_id"]), max=cfg.max_mentees),
                             link_preview_options=LinkPreviewOptions(is_disabled=True))
