# states.py
# Состояния диалогов бота.

from aiogram.fsm.state import State, StatesGroup


class SurveyStates(StatesGroup):
    """Анкета пользователя при первом запуске."""
    consent = State()
    full_name = State()
    group = State()
    phone = State()
    email = State()
    contact_type = State()
    nickname = State()
    confirm = State()
    edit_value = State()


class AdminWorkshopStates(StatesGroup):
    """Мастер создания мастерской."""
    title = State()
    format = State()
    description = State()
    date = State()
    location = State()
    lessons = State()
    days = State()
    quota = State()
    photo = State()
    open_at = State()
    close_at = State()


class AdminScheduleStates(StatesGroup):
    """Ручная настройка расписания открытия/закрытия записи."""
    open_at = State()
    close_at = State()


class AdminServiceStates(StatesGroup):
    """Служебные админ-действия (фото приветствия и т.п.)."""
    start_photo = State()


class AdminReminderStates(StatesGroup):
    """Рассылка напоминания участникам."""
    workshop = State()
    audience = State()
    text = State()