"""B8: «Мои контакты» — имя, статус, напоминание через N дней."""
from datetime import timedelta
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from .. import keyboards as kb
from ..config import Config
from ..db import Database
from ..services import user_now

router = Router(name="contacts")


class ContactAdd(StatesGroup):
    name = State()


def _remind_date(user: dict, cfg: Config, days: int) -> str | None:
    if days <= 0:
        return None
    return (user_now(user, cfg).date() + timedelta(days=days)).isoformat()


def _card(c: dict) -> str:
    remind = f"{c['remind_on'][8:10]}.{c['remind_on'][5:7]}.{c['remind_on'][:4]}" if c["remind_on"] else "нет"
    return f"👤 <b>{escape(c['name'])}</b>\nСтатус: {c['status']}\nНапоминание: {remind}"


async def _send_list(target: Message, db: Database, owner_id: int, edit: bool = False) -> None:
    contacts = await db.list_contacts(owner_id)
    text = (f"<b>📇 Мои контакты</b> ({len(contacts)})\n"
            "Ставь напоминание через N дней — я напишу, когда пора сделать касание."
            if contacts else
            "<b>📇 Мои контакты</b>\nПока пусто. Добавь людей из своего списка 100 знакомых.")
    if edit:
        await target.edit_text(text, reply_markup=kb.contacts_menu_kb(contacts))
    else:
        await target.answer(text, reply_markup=kb.contacts_menu_kb(contacts))


@router.message(Command("contacts"))
@router.message(F.text == kb.BTN_CONTACTS)
async def cmd_contacts(message: Message, state: FSMContext, db: Database) -> None:
    await state.clear()
    if not await db.get_user(message.from_user.id):
        await message.answer("Сначала нажми /start")
        return
    await _send_list(message, db, message.from_user.id)


@router.callback_query(F.data == "c:list")
async def cb_list(cb: CallbackQuery, db: Database) -> None:
    await _send_list(cb.message, db, cb.from_user.id, edit=True)
    await cb.answer()


@router.callback_query(F.data == "c:add")
async def cb_add(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ContactAdd.name)
    await cb.message.answer("Как зовут человека? Можно с пометкой: «Айгерим, коллега»")
    await cb.answer()


@router.message(ContactAdd.name, F.text)
async def add_name(message: Message, state: FSMContext) -> None:
    await state.update_data(contact_name=message.text.strip()[:80])
    await message.answer("Какой статус?", reply_markup=kb.status_kb("ca:st"))


@router.callback_query(F.data.startswith("ca:st:"))
async def add_status(cb: CallbackQuery, state: FSMContext) -> None:
    if "contact_name" not in await state.get_data():
        await cb.answer("Начни заново: «📇 Мои контакты» → «Добавить»", show_alert=True)
        return
    status = kb.CONTACT_STATUSES[int(cb.data.split(":")[2])]
    await state.update_data(contact_status=status)
    await cb.message.edit_text(f"Статус: {status}\nКогда напомнить о касании?", reply_markup=kb.remind_kb("ca:rm"))
    await cb.answer()


@router.callback_query(F.data.startswith("ca:rm:"))
async def add_remind(cb: CallbackQuery, state: FSMContext, db: Database, cfg: Config) -> None:
    data = await state.get_data()
    if "contact_status" not in data:
        await cb.answer("Начни заново: «📇 Мои контакты» → «Добавить»", show_alert=True)
        return
    user = await db.get_user(cb.from_user.id)
    remind_on = _remind_date(user, cfg, int(cb.data.split(":")[2]))
    await db.add_contact(user["tg_id"], data["contact_name"], data["contact_status"], remind_on)
    await state.clear()
    await cb.message.edit_text(f"✅ Добавлен: <b>{escape(data['contact_name'])}</b>")
    await _send_list(cb.message, db, user["tg_id"])
    await cb.answer()


@router.callback_query(F.data.startswith("c:open:"))
async def cb_open(cb: CallbackQuery, db: Database) -> None:
    contact = await db.get_contact(cb.from_user.id, int(cb.data.split(":")[2]))
    if not contact:
        await cb.answer("Контакт не найден", show_alert=True)
        return
    await cb.message.answer(_card(contact), reply_markup=kb.contact_card_kb(contact["id"]))
    await cb.answer()


@router.callback_query(F.data.startswith("c:status:"))
async def cb_status(cb: CallbackQuery) -> None:
    cid = int(cb.data.split(":")[2])
    await cb.message.edit_reply_markup(reply_markup=kb.status_kb(f"c:setst:{cid}"))
    await cb.answer()


@router.callback_query(F.data.startswith("c:setst:"))
async def cb_set_status(cb: CallbackQuery, db: Database) -> None:
    _, _, cid, idx = cb.data.split(":")
    await db.update_contact(cb.from_user.id, int(cid), status=kb.CONTACT_STATUSES[int(idx)])
    await _refresh_card(cb, db, int(cid))


@router.callback_query(F.data.startswith("c:remind:"))
async def cb_remind(cb: CallbackQuery) -> None:
    cid = int(cb.data.split(":")[2])
    await cb.message.edit_reply_markup(reply_markup=kb.remind_kb(f"c:setrm:{cid}"))
    await cb.answer()


@router.callback_query(F.data.startswith("c:setrm:"))
async def cb_set_remind(cb: CallbackQuery, db: Database, cfg: Config) -> None:
    _, _, cid, days = cb.data.split(":")
    user = await db.get_user(cb.from_user.id)
    await db.update_contact(user["tg_id"], int(cid), remind_on=_remind_date(user, cfg, int(days)))
    await _refresh_card(cb, db, int(cid))


@router.callback_query(F.data.startswith("c:snooze:"))
async def cb_snooze(cb: CallbackQuery, db: Database, cfg: Config) -> None:
    cid = int(cb.data.split(":")[2])
    user = await db.get_user(cb.from_user.id)
    await db.update_contact(user["tg_id"], cid, remind_on=_remind_date(user, cfg, 3))
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.answer("Напомню через 3 дня")


@router.callback_query(F.data.startswith("c:touched:"))
async def cb_touched(cb: CallbackQuery, db: Database) -> None:
    cid = int(cb.data.split(":")[2])
    await db.update_contact(cb.from_user.id, cid, remind_on=None)
    await cb.message.edit_reply_markup(reply_markup=kb.contact_card_kb(cid))
    await cb.answer("Отлично! Обнови статус или поставь следующее напоминание.")


@router.callback_query(F.data.startswith("c:del:"))
async def cb_delete(cb: CallbackQuery, db: Database) -> None:
    await db.delete_contact(cb.from_user.id, int(cb.data.split(":")[2]))
    await cb.message.edit_text("🗑 Контакт удалён")
    await cb.answer()


async def _refresh_card(cb: CallbackQuery, db: Database, cid: int) -> None:
    contact = await db.get_contact(cb.from_user.id, cid)
    if contact:
        await cb.message.edit_text(_card(contact), reply_markup=kb.contact_card_kb(cid))
    await cb.answer("Сохранено")
