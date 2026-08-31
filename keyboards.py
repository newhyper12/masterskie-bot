# keyboards.py
# Все клавиатуры бота, версия 2.

from aiogram.types import InlineKeyboardButton as KB
from aiogram.types import InlineKeyboardMarkup as Markup
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from models import Workshop


# ==================================================
# ПОЛЬЗОВАТЕЛЬСКИЕ
# ==================================================

def kb_start() -> Markup:
    return Markup(inline_keyboard=[
        [KB(text="📝 Регистрация на МК", callback_data="menu:register")],
        [KB(text="📋 Мои записи", callback_data="menu:my")],
    ])


def kb_main_reply() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🏠 Меню")]],
        resize_keyboard=True,
    )


def kb_consent() -> Markup:
    return Markup(inline_keyboard=[
        [KB(text="✅ Согласен", callback_data="consent:yes")],
    ])


def kb_contact_type() -> Markup:
    return Markup(inline_keyboard=[
        [KB(text="Telegram", callback_data="contact:tg"),
         KB(text="VK", callback_data="contact:vk")],
    ])


def kb_confirm() -> Markup:
    return Markup(inline_keyboard=[
        [KB(text="✅ Да", callback_data="confirm:yes"),
         KB(text="✏️ Изменить", callback_data="confirm:edit")],
    ])


def kb_edit_fields() -> Markup:
    return Markup(inline_keyboard=[
        [KB(text="ФИО", callback_data="edit:full_name")],
        [KB(text="Группа", callback_data="edit:group")],
        [KB(text="Телефон", callback_data="edit:phone")],
        [KB(text="Почта", callback_data="edit:email")],
        [KB(text="Контакт", callback_data="edit:nickname")],
        [KB(text="↩️ Вернуться", callback_data="edit:back")],
    ])


def kb_formats() -> Markup:
    return Markup(inline_keyboard=[
        [KB(text="Базовые", callback_data="fmt:базовая")],
        [KB(text="Специальные", callback_data="fmt:специальная")],
        [KB(text="↩️ В меню", callback_data="back:menu")],
    ])


def kb_workshops(workshops: list[Workshop]) -> Markup:
    rows = [[KB(text=w.title, callback_data=f"ws:{w.id}")] for w in workshops]
    rows.append([KB(text="↩️ Назад", callback_data="back:formats")])
    return Markup(inline_keyboard=rows)


def kb_workshop_card(workshop_id: int) -> Markup:
    return Markup(inline_keyboard=[
        [KB(text="✅ Записаться", callback_data=f"signup:{workshop_id}")],
        [KB(text="↩️ Назад", callback_data="back:workshops")],
    ])


def kb_slot_dates(workshop_id: int, date1: str, date2: str) -> Markup:
    """Выбор даты для базовой мастерской."""
    return Markup(inline_keyboard=[
        [KB(text=f"📅 {date1}", callback_data=f"slot:1:{workshop_id}")],
        [KB(text=f"📅 {date2}", callback_data=f"slot:2:{workshop_id}")],
        [KB(text="↩️ Назад", callback_data=f"ws:{workshop_id}")],
    ])


def kb_reserve(workshop_id: int, slot: int) -> Markup:
    return Markup(inline_keyboard=[
        [KB(text="Да", callback_data=f"reserve:yes:{workshop_id}:{slot}"),
         KB(text="Нет", callback_data=f"reserve:no:{workshop_id}:{slot}")],
    ])


def kb_my_records(records: list[tuple[int, str, str]]) -> Markup:
    rows = []
    for ws_id, title, status in records:
        rows.append([
            KB(text=f"❌ Отменить: {title}", callback_data=f"cancel:ask:{ws_id}")
        ])
    rows.append([KB(text="↩️ В меню", callback_data="back:menu")])
    return Markup(inline_keyboard=rows)


def kb_cancel_confirm(workshop_id: int) -> Markup:
    return Markup(inline_keyboard=[
        [KB(text="Да, отменить", callback_data=f"cancel:yes:{workshop_id}"),
         KB(text="Нет", callback_data=f"cancel:no:{workshop_id}")],
    ])


# ==================================================
# АДМИНСКИЕ
# ==================================================

def kb_admin_menu() -> Markup:
    return Markup(inline_keyboard=[
        [KB(text="➕ Создать мастерскую", callback_data="admin:create")],
        [KB(text="⏰ Запись: открытие/закрытие", callback_data="admin:toggle")],
        [KB(text="✏️ Редактировать", callback_data="admin:edit")],
        [KB(text="🗑 Удалить", callback_data="admin:delete")],
        [KB(text="♻️ Восстановить", callback_data="admin:restore")],
        [KB(text="🖼 Фото форматов", callback_data="admin:fmtphoto")],
        [KB(text="🖼 Фото приветствия", callback_data="admin:setphoto")],
        [KB(text="📨 Напоминание", callback_data="admin:remind")],
        [KB(text="💬 Текст приветствия", callback_data="admin:settext")],
    ])


def kb_admin_format() -> Markup:
    return Markup(inline_keyboard=[
        [KB(text="Базовая", callback_data="awfmt:базовая"),
         KB(text="Специальная", callback_data="awfmt:специальная")],
    ])


def kb_admin_skip(next_step: str) -> Markup:
    return Markup(inline_keyboard=[
        [KB(text="Пропустить", callback_data=f"skip:{next_step}")],
    ])


def kb_admin_open_now() -> Markup:
    return Markup(inline_keyboard=[
        [KB(text="⚡ Открыть сразу", callback_data="openat:now")],
    ])


def kb_admin_no_close() -> Markup:
    return Markup(inline_keyboard=[
        [KB(text="Не закрывать", callback_data="noclose")],
    ])


def kb_admin_workshops(workshops: list[Workshop], prefix: str) -> Markup:
    rows = [[KB(text=w.title, callback_data=f"{prefix}:{w.id}")] for w in workshops]
    rows.append([KB(text="↩️ Назад", callback_data="admin:menu")])
    return Markup(inline_keyboard=rows)


def kb_admin_edit_fields(workshop_id: int) -> Markup:
    p = f"editf"
    return Markup(inline_keyboard=[
        [KB(text="Название", callback_data=f"{p}:title:{workshop_id}")],
        [KB(text="Описание", callback_data=f"{p}:description:{workshop_id}")],
        [KB(text="Дата 1", callback_data=f"{p}:date1:{workshop_id}")],
        [KB(text="Дата 2", callback_data=f"{p}:date2:{workshop_id}")],
        [KB(text="Место", callback_data=f"{p}:location:{workshop_id}")],
        [KB(text="Квота", callback_data=f"{p}:quota:{workshop_id}")],
        [KB(text="Фото", callback_data=f"{p}:photo:{workshop_id}")],
        [KB(text="↩️ Назад", callback_data="admin:menu")],
    ])


def kb_confirm_delete(workshop_id: int) -> Markup:
    return Markup(inline_keyboard=[
        [KB(text="🗑 Да, удалить", callback_data=f"del:yes:{workshop_id}"),
         KB(text="Нет", callback_data=f"del:no:{workshop_id}")],
    ])


def kb_confirm_restore(workshop_id: int) -> Markup:
    return Markup(inline_keyboard=[
        [KB(text="♻️ Да, восстановить", callback_data=f"rest:yes:{workshop_id}"),
         KB(text="Нет", callback_data=f"rest:no:{workshop_id}")],
    ])


def kb_format_photo_pick() -> Markup:
    return Markup(inline_keyboard=[
        [KB(text="Базовые", callback_data="fmtphoto:базовая"),
         KB(text="Специальные", callback_data="fmtphoto:специальная")],
        [KB(text="↩️ Назад", callback_data="admin:menu")],
    ])


def kb_admin_audience() -> Markup:
    return Markup(inline_keyboard=[
        [KB(text="Основной список", callback_data="aud:основной")],
        [KB(text="Резерв", callback_data="aud:резерв")],
        [KB(text="Все", callback_data="aud:все")],
    ])