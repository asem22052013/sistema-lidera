"""Запуск: python -m bot"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from .config import load_config
from .db import Database
from .handlers import admin, common, contacts, newbie, onboarding, team
from .scheduler import run_scheduler

COMMANDS = [
    BotCommand(command="start", description="Начать / главное меню"),
    BotCommand(command="task", description="Задание дня"),
    BotCommand(command="progress", description="Мой прогресс"),
    BotCommand(command="contacts", description="Мои контакты"),
    BotCommand(command="team", description="Моя команда (для наставников и лидеров)"),
    BotCommand(command="rating", description="Рейтинг недели"),
    BotCommand(command="link", description="Ссылка-приглашение"),
    BotCommand(command="tz", description="Часовой пояс"),
    BotCommand(command="privacy", description="Политика конфиденциальности"),
    BotCommand(command="delete_me", description="Удалить мои данные"),
]


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config()
    db = Database(cfg.db_path)
    await db.connect()

    bot = Bot(cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp["db"] = db
    dp["cfg"] = cfg
    # Порядок важен: common с общим ответом на любой текст — последним.
    dp.include_routers(admin.router, onboarding.router, newbie.router, team.router, contacts.router, common.router)

    await bot.set_my_commands(COMMANDS)
    scheduler = asyncio.create_task(run_scheduler(bot, db, cfg))
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.cancel()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
