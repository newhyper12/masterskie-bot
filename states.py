# states.py
# Состояния диалогов бота, версия 2.

from aiogram.fsm.state import State, StatesGroup


class SurveyStates(StatesGroup):
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
    date1 = State()
    date2 = State()
    location = State()
    lessons = State()
    days = State()
    quota = State()
    photo = State()
    open_at = State()
    close_at = State()


class AdminScheduleStates(StatesGroup):
    open_at = State()
    close_at = State()


class AdminEditStates(StatesGroup):
    """Редактирование мастерской: ждём новое значение поля."""
    value = State()
    photo = State()


class AdminServiceStates(StatesGroup):
    start_photo = State()
    format_photo = State()
    start_text = State()


class AdminReminderStates(StatesGroup):
    audience = State()
    text = State()