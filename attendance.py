from __future__ import annotations

import asyncio

import gspread
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from config import Settings
from google_drive import create_spreadsheet_in_folder
from models import Workshop

# Сколько строк отводим под резерв при создании файла.
RESERVE_ROWS = 15

# Права, которые были выданы при авторизации.
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def col_letter(n: int) -> str:
    """1 -> A, 2 -> B, ... 27 -> AA."""
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


class AttendanceClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        # Сервисный аккаунт: наполнение и правка существующих файлов.
        self.gc = gspread.service_account(
            filename=str(settings.service_account_file)
        )

    # ==================================================
    # СЛУЖЕБНОЕ
    # ==================================================

    def _ws(self, file_id: str):
        """Открывает лист «Посещаемость» файла мастерской."""
        return self.gc.open_by_key(file_id).worksheet("Посещаемость")

    @staticmethod
    def _layout(values: list[list[str]]) -> dict:
        """По содержимому листа определяет границы блоков и колонки."""
        headers = values[0] if values else []

        lessons = sum(1 for h in headers if str(h).startswith("Занятие"))
        hidden_idx = len(headers) - 1
        attended_idx = hidden_idx - 1
        last_sess_idx = 4 + lessons - 1

        totals = [
            i + 1
            for i, row in enumerate(values[1:], start=1)
            if len(row) > 1 and str(row[1]).strip().lower().startswith("итого")
        ]
        main_total = totals[0] if totals else None
        reserve_total = totals[1] if len(totals) > 1 else None

        return {
            "lessons": lessons,
            "sess_start": 4,
            "last_sess": last_sess_idx,
            "attended": attended_idx,
            "hidden": hidden_idx,
            "main_rows": range(2, main_total) if main_total else range(0),
            "reserve_rows": (
                range(main_total + 1, reserve_total)
                if main_total and reserve_total else range(0)
            ),
        }

    def _find_row(self, values: list[list[str]], layout: dict, telegram_id: int):
        """Ищет строку человека по служебной колонке telegram_id."""
        for i, row in enumerate(values[1:], start=2):
            if len(row) > layout["hidden"]:
                if str(row[layout["hidden"]]).strip() == str(telegram_id):
                    return i
        return None

    def _first_empty(self, values: list[list[str]], layout: dict, block: str):
        """Первая пустая строка (по колонке ФИО) в нужном блоке."""
        rows = layout["main_rows"] if block == "основной" else layout["reserve_rows"]
        for r in rows:
            row = values[r - 1]
            if len(row) < 2 or not str(row[1]).strip():
                return r
        return None

    def _write_person(
        self,
        ws,
        row: int,
        layout: dict,
        full_name: str,
        group: str,
        link: str,
        telegram_id: int,
        checkboxes: list[str] | None = None,
    ):
        """Записывает данные человека в строку, не трогая формулы."""
        lessons = layout["lessons"]
        boxes = checkboxes if checkboxes else [""] * lessons

        ws.update(f"B{row}:D{row}", [[full_name, group, link]],
                  value_input_option="USER_ENTERED")
        ws.update(
            f"E{row}:{col_letter(layout['last_sess'] + 1)}{row}",
            [boxes],
            value_input_option="USER_ENTERED",
        )
        ws.update(
            f"{col_letter(layout['hidden'] + 1)}{row}",
            [[str(telegram_id)]],
            value_input_option="USER_ENTERED",
        )

    def _clear_person(self, ws, row: int, layout: dict):
        """Убирает человека из строки. № и формулы остаются."""
        lessons = layout["lessons"]
        ws.update(f"B{row}:D{row}", [["", "", ""]],
                  value_input_option="USER_ENTERED")
        ws.update(
            f"E{row}:{col_letter(layout['last_sess'] + 1)}{row}",
            [[""] * lessons],
            value_input_option="USER_ENTERED",
        )
        ws.update(
            f"{col_letter(layout['hidden'] + 1)}{row}",
            [[""]],
            value_input_option="USER_ENTERED",
        )

    # ==================================================
    # СОЗДАНИЕ ФАЙЛА
    # ==================================================

    async def create(self, workshop: Workshop) -> str:
        """
        Создаёт файл посещаемости в твоей папке (от твоего аккаунта)
        и наполняет его структурой. Возвращает ID файла.
        """
        def _sync():
            # --- 1. Создаём пустую таблицу от твоего аккаунта ---
            try:
                creds = Credentials.from_authorized_user_file(
                    str(self.settings.oauth_token_file), SCOPES
                )
                user_drive = build(
                    "drive", "v3", credentials=creds, cache_discovery=False
                )
                file_id = create_spreadsheet_in_folder(
                    user_drive,
                    f"{workshop.title} — посещаемость",
                    self.settings.drive_folder_id,
                )
            except Exception as e:
                raise RuntimeError(
                    "Не удалось создать файл на Диске. Возможно, истёк "
                    "токен доступа Google: запусти `python3 refresh_google_token.py` "
                    f"и попробуй снова. Детали: {e}"
                ) from e

            # --- 2. Наполняем через сервисный аккаунт ---
            spreadsheet = self.gc.open_by_key(file_id)
            ws = spreadsheet.get_worksheet(0)
            ws.update_title("Посещаемость")

            lessons = max(workshop.lessons_count or 1, 1)
            quota = max(workshop.quota or 1, 1)

            sess_start_col = "E"
            last_sess_col = col_letter(4 + lessons)
            hidden_col = col_letter(6 + lessons)

            headers = ["№ п/п", "ФИО", "Группа", "Ссылка в телеграм"]
            headers += [f"Занятие {i}" for i in range(1, lessons + 1)]
            headers += ["Посещено занятий", "telegram_id"]

            rows: list[list] = [headers]

            def person_row(num: int, r: int) -> list:
                return [
                    num, "", "", "",
                    *([""] * lessons),
                    f"=COUNTIF({sess_start_col}{r}:{last_sess_col}{r}, TRUE)",
                    "",
                ]

            # Основной блок (квота строк)
            for i in range(1, quota + 1):
                rows.append(person_row(i, len(rows) + 1))
            main_end = len(rows)

            total_main = ["", "ИТОГО (основа)", "", ""]
            for c in range(5, 5 + lessons):
                letter = col_letter(c)
                total_main.append(f"=COUNTIF({letter}2:{letter}{main_end}, TRUE)")
            total_main += ["", ""]
            rows.append(total_main)

            # Резервный блок
            for i in range(1, RESERVE_ROWS + 1):
                rows.append(person_row(i, len(rows) + 1))
            reserve_end = len(rows)

            total_res = ["", "ИТОГО (резерв)", "", ""]
            for c in range(5, 5 + lessons):
                letter = col_letter(c)
                total_res.append(
                    f"=COUNTIF({letter}{main_end + 2}:{letter}{reserve_end}, TRUE)"
                )
            total_res += ["", ""]
            rows.append(total_res)

            last_row = len(rows)

            ws.update(
                f"A1:{hidden_col}{last_row}",
                rows,
                value_input_option="USER_ENTERED",
            )

            # Чекбоксы + закрепление шапки
            spreadsheet.batch_update({"requests": [
                {
                    "updateSheetProperties": {
                        "properties": {
                            "sheetId": ws.id,
                            "gridProperties": {"frozenRowCount": 1},
                        },
                        "fields": "gridProperties.frozenRowCount",
                    }
                },
                {
                    "setDataValidation": {
                        "range": {
                            "sheetId": ws.id,
                            "startRowIndex": 1,
                            "endRowIndex": last_row,
                            "startColumnIndex": 4,
                            "endColumnIndex": 4 + lessons,
                        },
                        "rule": {"condition": {"type": "BOOLEAN"}},
                    }
                },
            ]})

            # Пытаемся скрыть служебную колонку telegram_id.
            try:
                spreadsheet.batch_update({"requests": [{
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": ws.id,
                            "dimension": "COLUMNS",
                            "startIndex": 6 + lessons - 1,
                            "endIndex": 6 + lessons,
                        },
                        "properties": {"hiddenByDimension": True},
                        "fields": "hiddenByDimension",
                    }
                }]})
            except Exception:
                pass

            return file_id

        return await asyncio.to_thread(_sync)

    # ==================================================
    # ЛЮДИ В ФАЙЛЕ
    # ==================================================

    async def add_person(
        self,
        file_id: str,
        telegram_id: int,
        full_name: str,
        group: str,
        link: str,
        status: str,
    ) -> bool:
        """Добавляет человека в основной блок или в резерв."""
        def _sync():
            ws = self._ws(file_id)
            values = ws.get_all_values()
            layout = self._layout(values)

            block = "основной" if status == "основной" else "reserve"
            row = self._first_empty(values, layout, block)
            if row is None:
                return False

            self._write_person(
                ws, row, layout, full_name, group, link, telegram_id
            )
            return True

        return await asyncio.to_thread(_sync)

    async def remove_person(self, file_id: str, telegram_id: int) -> None:
        """Убирает человека из файла (при отмене/отчислении)."""
        def _sync():
            ws = self._ws(file_id)
            values = ws.get_all_values()
            layout = self._layout(values)
            row = self._find_row(values, layout, telegram_id)
            if row:
                self._clear_person(ws, row, layout)

        await asyncio.to_thread(_sync)

    async def move_person(
        self, file_id: str, telegram_id: int, to_status: str
    ) -> bool:
        """
        Переносит человека между блоками «основа» и «резерв»,
        сохраняя отметки посещаемости преподавателя.
        """
        def _sync():
            ws = self._ws(file_id)
            values = ws.get_all_values()
            layout = self._layout(values)
            row = self._find_row(values, layout, telegram_id)
            if row is None:
                return False

            r = values[row - 1]
            full_name = r[1]
            group = r[2]
            link = r[3]
            boxes = r[layout["sess_start"]:layout["last_sess"] + 1]

            self._clear_person(ws, row, layout)
            values = ws.get_all_values()
            layout = self._layout(values)
            block = "основной" if to_status == "основной" else "reserve"
            new_row = self._first_empty(values, layout, block)
            if new_row is None:
                return False

            self._write_person(
                ws, new_row, layout, full_name, group, link,
                telegram_id, checkboxes=boxes,
            )
            return True

        return await asyncio.to_thread(_sync)
