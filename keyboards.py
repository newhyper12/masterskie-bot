# keyboards.py
# Все клавиатуры бота.

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton as KB,
    InlineKeyboardMarkup as Markup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


def _short_date(d: str) -> str:
    """'20.09.2026 19:00' -> '20.09 · 19:00'; '20.09.2026' -> '20.09'."""
    parts = (d or "").split()
    if not parts or not parts[0]:
        return d or ""
    bits = parts[0].split(".")
    short = ".".join(bits[:2]) if len(bits) == 3 else parts[0]
    if len(parts) > 1:
        return f"{short} · {parts[1]}"
    return short


# ==================================================
# ПОЛЬЗОВАТЕЛЬСКИЕ
# ==================================================

def kb_main_reply() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📝 Регистрация на МК"),
             KeyboardButton(text="📋 Мои записи")],
            [KeyboardButton(text="🏠 Меню")],
        ],
        resize_keyboard=True,
    )


def kb_start() -> Markup:
    return Markup(inline_keyboard=[
        [KB(text="📝 Регистрация на МК", callback_data="menu:register")],
        [KB(text="📋 Мои записи", callback_data="menu:my")],
    ])


def kb_consent() -> Markup:
    return Markup(inline_keyboard=[
        [KB(text="✅ Согласен", callback_data="consent:yes")],
        [KB(text="❌ Не согласен", callback_data="consent:no")],
    ])


def kb_contact_type() -> Markup:
    return Markup(inline_keyboard=[
        [KB(text="✈️ Telegram", callback_data="contact:tg")],
        [KB(text="💙 VK", callback_data="contact:vk")],
    ])


def kb_confirm() -> Markup:
    return Markup(inline_keyboard=[
        [KB(text="✅ Всё верно", callback_data="confirm:yes")],
        [KB(text="✏️ Изменить", callback_data="confirm:edit")],
    ])


def kb_edit_fields() -> Markup:
    return Markup(inline_keyboard=[
        [KB(text="ФИО", callback_data="edit:full_name"),
         KB(text="Группа", callback_data="edit:group")],
        [KB(text="Телефон", callback_data="edit:phone"),
         KB(text="Почта", callback_data="edit:email")],
        [KB(text="Контакт", callback_data="edit:nickname")],
        [KB(text="↩️ Назад", callback_data="edit:back")],
    ])


def kb_birth_button() -> Markup:
    """НОВОЕ: кнопка сбора даты рождения — крепится к рассылке."""
    return Markup(inline_keyboard=[
        [KB(text="🎂 Указать дату рождения", callback_data="birth:set")],
    ])


def kb_formats() -> Markup:
    return Markup(inline_keyboard=[
        [KB(text="🛠 Базовые", callback_data="fmt:базовая")],
        [KB(text="⚡ Специальные", callback_data="fmt:специальная")],
        [KB(text="↩️ Назад", callback_data="back:menu")],
    ])


def kb_workshops(workshops) -> Markup:
    rows = [
        [KB(text=w.title, callback_data=f"ws:{w.id}")] for w in workshops
    ]
    rows.append([KB(text="↩️ Назад", callback_data="back:formats")])
    return Markup(inline_keyboard=rows)


def kb_workshop_card(workshop_id: int) -> Markup:
    return Markup(inline_keyboard=[
        [KB(text="✍️ Записаться", callback_data=f"signup:{workshop_id}")],
        [KB(text="↩️ Назад", callback_data="back:workshops")],
    ])


def kb_slot_dates(workshop_id: int, date1: str, date2: str) -> Markup:
    return Markup(inline_keyboard=[
        [KB(text=f"📅 {_short_date(date1)}", callback_data=f"slot:1:{workshop_id}")],
        [KB(text=f"📅 {_short_date(date2)}", callback_data=f"slot:2:{workshop_id}")],
        [KB(text="↩️ Назад", callback_data=f"ws:{workshop_id}")],
    ])


def kb_reserve(workshop_id: int, slot: int) -> Markup:
    return Markup(inline_keyboard=[
        [KB(text="🕑 Да, в резерв", callback_data=f"reserve:yes:{workshop_id}:{slot}")],
        [KB(text="❌ Нет", callback_data=f"reserve:no:{workshop_id}:{slot}")],
    ])


def kb_my_records(rows) -> Markup:
    buttons = [
        [KB(text=f"❌ Отменить: {title}", callback_data=f"cancel:ask:{ws_id}")]
        for ws_id, title, status in rows
    ]
    buttons.append([KB(text="↩️ В меню", callback_data="back:menu")])
    return Markup(inline_keyboard=buttons)


def kb_cancel_confirm(workshop_id: int) -> Markup:
    return Markup(inline_keyboard=[
        [KB(text="🗑 Да, отменить", callback_data=f"cancel:yes:{workshop_id}")],
        [KB(text="↩️ Оставить", callback_data=f"cancel:no:{workshop_id}")],
    ])


def kb_promote_offer(record_id: int) -> Markup:
    return Markup(inline_keyboard=[
        [KB(text="Да", callback_data=f"promote:yes:{record_id}"),
         KB(text="Нет", callback_data=f"promote:no:{record_id}")],
    ])


# ==================================================
# АДМИНСКИЕ
# ==================================================

def kb_admin_menu() -> Markup:
    return Markup(inline_keyboard=[
        [KB(text="➕ Создать мастерскую", callback_data="admin:create")],
        [KB(text="⏰ Запись: открытие/закрытие", callback_data="admin:toggle")],
        [KB(text="✏️ Редактировать", callback_data="admin:edit")],
        [KB(text="🗑 Удалить", callback_data="admin:delete"),
         KB(text="♻️ Восстановить", callback_data="admin:restore")],
        [KB(text=" Напоминания", callback_data="admin:remind")],
        [KB(text="📨 Рассылка всем", callback_data="admin:broadcast")],
        [KB(text="🖼 Фото форматов", callback_data="admin:fmtphoto")],
        [KB(text="📸 Фото приветствия", callback_data="admin:setphoto"),
         KB(text="✍️ Текст приветствия", callback_data="admin:settext")],
    ])


def kb_admin_format() -> Markup:
    return Markup(inline_keyboard=[
        [KB(text="🛠 Базовая", callback_data="awfmt:базовая")],
        [KB(text="⚡ Специальная", callback_data="awfmt:специальная")],
    ])


def kb_admin_skip(what: str) -> Markup:
    return Markup(inline_keyboard=[
        [KB(text="Пропустить", callback_data=f"skip:{what}")],
    ])


def kb_admin_open_now() -> Markup:
    return Markup(inline_keyboard=[
        [KB(text="⚡ Открыть сразу", callback_data="openat:now")],
    ])


def kb_admin_no_close() -> Markup:
    return Markup(inline_keyboard=[
        [KB(text="Не закрывать", callback_data="noclose")],
    ])


def kb_admin_workshops(workshops, prefix: str) -> Markup:
    rows = [
        [KB(text=f"{w.id}. {w.title}", callback_data=f"{prefix}:{w.id}")]
        for w in workshops
    ]
    rows.append([KB(text="↩️ Назад", callback_data="admin:menu")])
    return Markup(inline_keyboard=rows)


def kb_admin_edit_fields(workshop_id: int) -> Markup:
    fields = [
        ("title", "Название"),
        ("description", "Описание"),
        ("date1", "Дата 1"),
        ("date2", "Дата 2"),
        ("location", "Место"),
        ("quota", "Квота (мест)"),
        ("photo", "Фото"),
    ]
    rows = [
        [KB(text=label, callback_data=f"editf:{key}:{workshop_id}")]
        for key, label in fields
    ]
    rows.append([KB(text="↩️ Назад", callback_data="admin:menu")])
    return Markup(inline_keyboard=rows)


def kb_confirm_delete(workshop_id: int) -> Markup:
    return Markup(inline_keyboard=[
        [KB(text="🗑 Да, удалить", callback_data=f"del:yes:{workshop_id}")],
        [KB(text="❌ Нет", callback_data=f"del:no:{workshop_id}")],
    ])


def kb_confirm_restore(workshop_id: int) -> Markup:
    return Markup(inline_keyboard=[
        [KB(text="♻️ Да, восстановить", callback_data=f"rest:yes:{workshop_id}")],
        [KB(text="❌ Нет", callback_data=f"rest:no:{workshop_id}")],
    ])


def kb_format_photo_pick() -> Markup:
    return Markup(inline_keyboard=[
        [KB(text="🛠 Базовая", callback_data="fmtphoto:базовая")],
        [KB(text="⚡ Специальная", callback_data="fmtphoto:специальная")],
        [KB(text="↩️ Назад", callback_data="admin:menu")],
    ])


def kb_admin_audience() -> Markup:
    return Markup(inline_keyboard=[
        [KB(text="👥 Все записанные", callback_data="aud:все")],
        [KB(text="✅ Основной список", callback_data="aud:основной")],
        [KB(text="🕑 Резерв", callback_data="aud:резерв")],
    ])