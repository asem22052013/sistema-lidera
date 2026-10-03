from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

BTN_TASK = "📌 Задание дня"
BTN_PROGRESS = "📈 Прогресс"
BTN_CONTACTS = "📇 Мои контакты"
BTN_TEAM = "👥 Команда"
BTN_RATING = "🏆 Рейтинг"
BTN_LINK = "🔗 Моя ссылка"
BTN_HELP = "❓ Помощь"

CONTACT_STATUSES = ["Знакомый", "Интерес", "Думает", "Клиент", "Партнёр", "Не сейчас"]
REMIND_DAYS = [1, 3, 7, 14, 30]


def main_menu(user: dict) -> ReplyKeyboardMarkup:
    rows: list[list[str]] = []
    if user.get("role") == "newbie" and user.get("status") in {"active", "trial_ended"}:
        rows.append([BTN_TASK, BTN_PROGRESS])
    if user.get("role") in {"partner", "leader"}:
        rows.append([BTN_TEAM, BTN_RATING])
        rows.append([BTN_LINK])
    rows.append([BTN_CONTACTS, BTN_HELP])
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t) for t in row] for row in rows], resize_keyboard=True
    )


def consent_kb(privacy_url: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Согласен(на)", callback_data="consent:yes")
    if privacy_url:
        kb.button(text="📄 Политика конфиденциальности", url=privacy_url)
    kb.adjust(1)
    return kb.as_markup()


def role_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🌱 Новичок (0–3 месяца)", callback_data="role:newbie")
    kb.button(text="🤝 Партнёр", callback_data="role:partner")
    kb.button(text="👑 Лидер со структурой", callback_data="role:leader")
    kb.adjust(1)
    return kb.as_markup()


def mentor_confirm_kb(mentor_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да, это мой наставник", callback_data=f"mentor:ok:{mentor_id}")
    kb.button(text="✏️ Указать другого", callback_data="mentor:other")
    kb.button(text="Без наставника", callback_data="mentor:none")
    kb.adjust(1)
    return kb.as_markup()


def mentor_skip_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Продолжить без наставника", callback_data="mentor:none")
    return kb.as_markup()


def task_kb(day: int, video: str = "") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if video:
        kb.button(text="▶️ Видео к заданию", url=video)
    kb.button(text="✅ Выполнено", callback_data=f"done:{day}")
    kb.adjust(1)
    return kb.as_markup()


def graduate_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🙋 Хочу быть наставником", callback_data="become_mentor")
    return kb.as_markup()


def pro_kb(pro_url: str) -> InlineKeyboardMarkup | None:
    if not pro_url:
        return None
    kb = InlineKeyboardBuilder()
    kb.button(text="💎 Узнать о клубе PRO", url=pro_url)
    return kb.as_markup()


def write_to_kb(tg_id: int, name: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=f"✉️ Написать: {name}"[:60], url=f"tg://user?id={tg_id}")
    return kb.as_markup()


def tz_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for off in (2, 3, 4, 5, 6, 7):
        kb.button(text=f"UTC+{off}", callback_data=f"tz:{off}")
    kb.adjust(3)
    return kb.as_markup()


def delete_confirm_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🗑 Да, удалить всё", callback_data="delete_me:yes")
    kb.button(text="Отмена", callback_data="delete_me:no")
    kb.adjust(1)
    return kb.as_markup()


# --- контакты ---

def contacts_menu_kb(contacts: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить контакт", callback_data="c:add")
    for c in contacts[:40]:
        mark = f" · ⏰ {c['remind_on'][8:10]}.{c['remind_on'][5:7]}" if c["remind_on"] else ""
        kb.button(text=f"{c['name']} — {c['status']}{mark}"[:60], callback_data=f"c:open:{c['id']}")
    kb.adjust(1)
    return kb.as_markup()


def status_kb(prefix: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for i, s in enumerate(CONTACT_STATUSES):
        kb.button(text=s, callback_data=f"{prefix}:{i}")
    kb.adjust(3)
    return kb.as_markup()


def remind_kb(prefix: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for d in REMIND_DAYS:
        kb.button(text=f"через {d} дн.", callback_data=f"{prefix}:{d}")
    kb.button(text="Без напоминания", callback_data=f"{prefix}:0")
    kb.adjust(3, 2, 1)
    return kb.as_markup()


def contact_card_kb(contact_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Статус", callback_data=f"c:status:{contact_id}")
    kb.button(text="⏰ Напомнить", callback_data=f"c:remind:{contact_id}")
    kb.button(text="🗑 Удалить", callback_data=f"c:del:{contact_id}")
    kb.button(text="⬅️ К списку", callback_data="c:list")
    kb.adjust(2, 2)
    return kb.as_markup()


def contact_due_kb(contact_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Написал(а)", callback_data=f"c:touched:{contact_id}")
    kb.button(text="⏰ Через 3 дня", callback_data=f"c:snooze:{contact_id}")
    kb.button(text="Открыть", callback_data=f"c:open:{contact_id}")
    kb.adjust(2, 1)
    return kb.as_markup()
