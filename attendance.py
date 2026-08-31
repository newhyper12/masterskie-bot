# attendance.py
# Файлы посещаемости версии 2:
#  - базовая мастерская  -> два листа (по одному на дату), один чекбокс «Отметка»;
#  - специальная         -> один лист, чекбоксы по занятиям;
#  - строк всегда квота + 7 (запас под отменившихся — они остаются в файле);
#  - резерва в файле больше нет (резерв живёт в БД).

from __future__ import annotations

import asyncio

import gspread
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from config import Settings
from google_drive import create_spreadsheet_in_folder
from models import Workshop

EXTRA_ROWS = 7  # запас строк под отменившихся

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def col_letter(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


class AttendanceClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.gc = gspread.service_account(
            filename=str(settings.service_account_file)
        )

    # ==================================================
    # СОЗДАНИЕ ФАЙЛА
    # ==================================================

    async def create(self, workshop: Workshop) -> str:
        def _sync():
            file_id = self._create_file_on_drive(f"{workshop.title} — посещаемость")
            spreadsheet = self.gc.open_by_key(file_id)

            if workshop.format == "базовая":
                dates = [workshop.date1]
                if workshop.date2:
                    dates.append(workshop.date2)
                for i, d in enumerate(dates):
                    title = (d or f"Занятие {i + 1}")[:100]
                    if i == 0:
                        ws = spreadsheet.get_worksheet(0)
                        ws.update_title(title)
                    else:
                        ws = spreadsheet.add_worksheet(
                            title=title, rows=workshop.quota + EXTRA_ROWS + 1, columns=6
                        )
                    self._fill_basic(ws, workshop.quota)
            else:
                ws = spreadsheet.get_worksheet(0)
                ws.update_title("Посещаемость")
                self._fill_special(ws, workshop)

            return file_id

        return await asyncio.to_thread(_sync)

    def _create_file_on_drive(self, title: str) -> str:
        creds = Credentials.from_authorized_user_file(
            str(self.settings.oauth_token_file), SCOPES
        )
        user_drive = build("drive", "v3", credentials=creds, cache_discovery=False)
        return create_spreadsheet_in_folder(
            user_drive, title, self.settings.drive_folder_id
        )

    def _fill_basic(self, ws, quota: int):
        """Лист базовой мастерской: одна отметка, квота+7 строк."""
        rows = [["№ п/п", "ФИО", "Группа", "Ссылка в телеграм", "Отметка", "telegram_id"]]
        for i in range(1, quota + EXTRA_ROWS + 1):
            rows.append([i, "", "", "", "", ""])
        last = len(rows)

        ws.update(f"A1:F{last}", rows, value_input_option="USER_ENTERED")
        self._apply_formatting(ws, last, mark_cols=[4], hide_col=5)

    def _fill_special(self, ws, workshop: Workshop):
        """Лист специальной: чекбоксы по занятиям, квота+7 строк."""
        lessons = max(workshop.lessons_count or 1, 1)
        sess_start = "E"
        last_sess = col_letter(4 + lessons)
        hidden_col = col_letter(6 + lessons)

        header = ["№ п/п", "ФИО", "Группа", "Ссылка в телеграм"]
        header += [f"Занятие {i}" for i in range(1, lessons + 1)]
        header += ["Посещено занятий", "telegram_id"]
        rows = [header]

        for i in range(1, quota_rows(workshop.quota) + 1):
            r = len(rows) + 1
            rows.append([
                i, "", "", "",
                *([""] * lessons),
                f"=COUNTIF({sess_start}{r}:{last_sess}{r}, TRUE)",
                "",
            ])
        person_end = len(rows)

        total = ["", "ИТОГО", "", ""]
        for c in range(5, 5 + lessons):
            letter = col_letter(c)
            total.append(f"=COUNTIF({letter}2:{letter}{person_end}, TRUE)")
        total += ["", ""]
        rows.append(total)
        last = len(rows)

        ws.update(f"A1:{hidden_col}{last}", rows, value_input_option="USER_ENTERED")
        self._apply_formatting(
            ws, last, mark_cols=list(range(4, 4 + lessons)), hide_col=5 + lessons
        )

    def _apply_formatting(self, ws, last_row: int, mark_cols: list, hide_col: int):
        """Закрепление шапки, чекбоксы, скрытие служебной колонки."""
        spreadsheet = ws.spreadsheet
        requests = [
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": ws.id,
                        "gridProperties": {"frozenRowCount": 1},
                    },
                    "fields": "gridProperties.frozenRowCount",
                }
            }
        ]
        for col in mark_cols:
            requests.append({
                "setDataValidation": {
                    "range": {
                        "sheetId": ws.id,
                        "startRowIndex": 1,
                        "endRowIndex": last_row,
                        "startColumnIndex": col,
                        "endColumnIndex": col + 1,
                    },
                    "rule": {"condition": {"type": "BOOLEAN"}},
                }
            })
        spreadsheet.batch_update({"requests": requests})

        try:
            spreadsheet.batch_update({"requests": [{
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": ws.id,
                        "dimension": "COLUMNS",
                        "startIndex": hide_col,
                        "endIndex": hide_col + 1,
                    },
                    "properties": {"hiddenByDimension": True},
                    "fields": "hiddenByDimension",
                }
            }]})
        except Exception:
            pass

    # ==================================================
    # ЛЮДИ В ФАЙЛЕ
    # ==================================================

    def _target_sheet(self, spreadsheet, workshop: Workshop, slot: int):
        if workshop.format == "базовая":
            idx = 0 if slot == 1 else 1
            sheets = spreadsheet.worksheets()
            return sheets[min(idx, len(sheets) - 1)]
        return spreadsheet.worksheets()[0]

    async def add_person(
        self,
        file_id: str,
        workshop: Workshop,
        slot: int,
        full_name: str,
        group: str,
        link: str,
        telegram_id: int,
    ) -> bool:
        """Ставит человека в первую пустую строку нужного листа."""
        def _sync():
            spreadsheet = self.gc.open_by_key(file_id)
            ws = self._target_sheet(spreadsheet, workshop, slot)
            values = ws.get_all_values()
            hidden_idx = len(values[0]) - 1 if values else 5

            for r in range(2, len(values) + 1):
                row = values[r - 1]
                if len(row) < 2 or not str(row[1]).strip():
                    ws.update(
                        f"B{r}:D{r}", [[full_name, group, link]],
                        value_input_option="USER_ENTERED",
                    )
                    ws.update_cell(r, hidden_idx + 1, str(telegram_id))
                    return True
            return False

        return await asyncio.to_thread(_sync)

    # ==================================================
    # ДАМП И ВОССТАНОВЛЕНИЕ (для резервных копий)
    # ==================================================

    async def dump(self, file_id: str) -> dict:
        """Все листы файла как {название: [[...], ...]}."""
        def _sync():
            spreadsheet = self.gc.open_by_key(file_id)
            return {ws.title: ws.get_all_values() for ws in spreadsheet.worksheets()}
        return await asyncio.to_thread(_sync)

    async def restore(self, title: str, dump: dict) -> str:
        """Пересоздаёт файл посещаемости из дампа. Возвращает новый file_id."""
        def _sync():
            file_id = self._create_file_on_drive(title)
            spreadsheet = self.gc.open_by_key(file_id)

            for i, (sheet_title, rows) in enumerate(dump.items()):
                if i == 0:
                    ws = spreadsheet.get_worksheet(0)
                    ws.update_title(sheet_title[:100])
                else:
                    ws = spreadsheet.add_worksheet(
                        title=sheet_title[:100],
                        rows=max(len(rows), 5),
                        columns=max(len(rows[0]) if rows else 6, 6),
                    )
                if not rows:
                    continue
                width = max(len(r) for r in rows)
                padded = [r + [""] * (width - len(r)) for r in rows]
                ws.update(
                    f"A1:{col_letter(width)}{len(padded)}",
                    padded,
                    value_input_option="USER_ENTERED",
                )

                header = rows[0]
                mark_cols = [
                    i for i, h in enumerate(header)
                    if str(h).strip() == "Отметка" or str(h).startswith("Занятие")
                ]
                hide = None
                for i, h in enumerate(header):
                    if str(h).strip().lower() == "telegram_id":
                        hide = i
                if hide is not None:
                    self._apply_formatting(ws, len(padded), mark_cols, hide)
            return file_id

        return await asyncio.to_thread(_sync)

    async def delete_file(self, file_id: str):
        """Удаляет файл с Диска от твоего аккаунта."""
        def _sync():
            creds = Credentials.from_authorized_user_file(
                str(self.settings.oauth_token_file), SCOPES
            )
            drive = build("drive", "v3", credentials=creds, cache_discovery=False)
            drive.files().delete(fileId=file_id).execute()
        await asyncio.to_thread(_sync)


def quota_rows(quota: int) -> int:
    return max(quota or 1, 1) + EXTRA_ROWS