# keyboards.py
# Все клавиатуры бота: inline-кнопки воронок и постоянная нижняя клавиатура.

from aiogram.types import InlineKeyboardButton as KB
from aiogram.types import InlineKeyboardMarkup as Markup
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from models import Workshop


# ==================================================
# ПОЛЬЗОВАТЕЛЬСКИЕ КЛАВИАТУРЫ
# ==================================================

def kb_start() -> Markup:
    """Главное меню пользователя."""
    return Markup(inline_keyboard=[
        [KB(text="📝 Регистрация на МК", callback_data="menu:register")],
        [KB(text="📋 Мои записи", callback_data="menu:my")],
    ])


def kb_main_reply() -> ReplyKeyboardMarkup:
    """
    Постоянная нижняя клавиатура.
    Живёт под полем ввода всегда, чтобы пользователь никогда не терялся.
    """
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🏠 Меню")]],
        resize_keyboard=True,
    )


def kb_consent() -> Markup:
    # Кнопки «Не согласен» нет: без согласия анкета просто не сохраняется.
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
    """Фиксированный выбор формата (не зависит от таблицы)."""
    return Markup(inline_keyboard=[
        [KB(text="Базовые", callback_data="fmt:базовая")],
        [KB(text="Специальные", callback_data="fmt:специальная")],
        [KB(text="↩️ В меню", callback_data="back:menu")],
    ])


def kb_workshops(workshops: list[Workshop]) -> Markup:
    """Список мастерских выбранного формата."""
    rows = [[KB(text=w.title, callback_data=f"ws:{w.id}")] for w in workshops]
    rows.append([KB(text="↩️ Назад", callback_data="back:formats")])
    return Markup(inline_keyboard=rows)


def kb_workshop_card(workshop_id: int) -> Markup:
    """Карточка мастерской."""
    return Markup(inline_keyboard=[
        [KB(text="✅ Записаться", callback_data=f"signup:{workshop_id}")],
        [KB(text="↩️ Назад", callback_data="back:workshops")],
    ])


def kb_reserve(workshop_id: int) -> Markup:
    """Вопрос «Хотите в резерв?»."""
    return Markup(inline_keyboard=[
        [KB(text="Да", callback_data=f"reserve:yes:{workshop_id}"),
         KB(text="Нет", callback_data=f"reserve:no:{workshop_id}")],
    ])


def kb_my_records(records: list[tuple[int, str, str]]) -> Markup:
    """
    «Мои записи» с кнопками отмены.
    records: список кортежей (workshop_id, title, status).
    """
    rows = []
    for ws_id, title, status in records:
        rows.append([
            KB(text=f"❌ Отменить: {title}", callback_data=f"cancel:ask:{ws_id}")
        ])
    rows.append([KB(text="↩️ В меню", callback_data="back:menu")])
    return Markup(inline_keyboard=rows)


def kb_cancel_confirm(workshop_id: int) -> Markup:
    """Подтверждение отмены записи."""
    return Markup(inline_keyboard=[
        [KB(text="Да, отменить", callback_data=f"cancel:yes:{workshop_id}"),
         KB(text="Нет", callback_data=f"cancel:no:{workshop_id}")],
    ])


# ==================================================
# АДМИНСКИЕ КЛАВИАТУРЫ
# ==================================================

def kb_admin_menu() -> Markup:
    return Markup(inline_keyboard=[
        [KB(text="➕ Создать мастерскую", callback_data="admin:create")],
        [KB(text="⏰ Запись: открытие/закрытие", callback_data="admin:toggle")],
        [KB(text="📨 Напоминание", callback_data="admin:remind")],
        [KB(text="🖼 Фото приветствия", callback_data="admin:setphoto")],
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
    """Список мастерских для админ-действий (префикс в callback)."""
    rows = [[KB(text=w.title, callback_data=f"{prefix}:{w.id}")] for w in workshops]
    rows.append([KB(text="↩️ Назад", callback_data="admin:menu")])
    return Markup(inline_keyboard=rows)


def kb_admin_audience() -> Markup:
    """Кому отправить напоминание."""
    return Markup(inline_keyboard=[
        [KB(text="Основной список", callback_data="aud:основной")],
        [KB(text="Резерв", callback_data="aud:резерв")],
        [KB(text="Все", callback_data="aud:все")],
    ])