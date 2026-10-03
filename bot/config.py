"""Настройки бота. Все значения читаются из переменных окружения (.env)."""
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "да"}


def _int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value not in (None, "") else default


def _ids(name: str) -> set[int]:
    raw = os.getenv(name, "")
    return {int(x) for x in raw.replace(" ", "").split(",") if x}


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_ids: set[int] = field(default_factory=set)
    db_path: str = "data/bot.sqlite3"

    # Время: по умолчанию Казахстан, UTC+5. Каждый пользователь может сменить пояс через /tz.
    default_tz_offset: int = 5
    task_hour: int = 9          # B3: задание дня
    reminder_hour: int = 20     # B5: напоминание, если не отмечено
    contacts_hour: int = 10     # B8: напоминания по контактам
    rating_hour: int = 10       # B10: рейтинг недели (по понедельникам)
    inactive_days: int = 3      # B6: дней без отметок до сигнала наставнику
    max_mentees: int = 5        # Модуль 6: у наставника не больше 5 новичков

    # Доступ: на пилоте программа бесплатна для всех.
    # Если выключить, полный доступ получают новички с наставником и те, кому выдал /grant админ,
    # а остальные проходят только день 1 (лид-магнит).
    free_access: bool = True

    pro_url: str = ""
    privacy_url: str = ""
    channel_url: str = ""


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN", "")
    if not token:
        raise RuntimeError("Не задан BOT_TOKEN. Скопируйте .env.example в .env и впишите токен от @BotFather.")
    return Config(
        bot_token=token,
        admin_ids=_ids("ADMIN_IDS"),
        db_path=os.getenv("DB_PATH", "data/bot.sqlite3"),
        default_tz_offset=_int("DEFAULT_TZ_OFFSET", 5),
        task_hour=_int("TASK_HOUR", 9),
        reminder_hour=_int("REMINDER_HOUR", 20),
        contacts_hour=_int("CONTACTS_HOUR", 10),
        rating_hour=_int("RATING_HOUR", 10),
        inactive_days=_int("INACTIVE_DAYS", 3),
        max_mentees=_int("MAX_MENTEES", 5),
        free_access=_bool("FREE_ACCESS", True),
        pro_url=os.getenv("PRO_URL", ""),
        privacy_url=os.getenv("PRIVACY_URL", ""),
        channel_url=os.getenv("CHANNEL_URL", ""),
    )
