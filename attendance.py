# attendance.py
# Рабочая область мастерской на Диске, v3:
#   {корень}/«{id}. {название}»/
#       ├── «{название} — список участников»  (регенерирует export.py из БД)
#       └── «{название} — посещаемость»       (файл преподавателя)
# Отменившийся освобождает строку посещаемости; следующий записавшийся занимает её.

from __future__ import annotations

import asyncio

import gspread

from config import Settings
from google_drive import (
    create_folder,
    create_spreadsheet_in_folder,
    delete_file,
    service_account_email,
    share_with,
    user_drive,
)
from datetime import datetime
from models import Workshop

EXTRA_ROWS = 7  # запас строк под отменившихся

PARTICIPANTS_HEADERS = [
    "telegram_id", "ФИО", "группа", "телефон", "почта",
    "контакт", "дата", "статус", "дата записи",
]


def col_letter(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def quota_rows(quota: int) -> int:
    return max(quota or 1, 1) + EXTRA_ROWS


class AttendanceClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.gc = gspread.service_account(
            filename=str(settings.service_account_file)
        )

    # ==================================================
    # СОЗДАНИЕ РАБОЧЕЙ ОБЛАСТИ (папка + 2 файла)
    # ==================================================

    async def create_workspace(self, w: Workshop) -> tuple:
        """Возвращает (drive_folder_id, participants_file_id, attendance_file_id).
        Если что-то падает — частично созданная папка удаляется."""
        def _sync():
            drive = user_drive(self.settings)
            sa = service_account_email(self.settings)

            folder_id = create_folder(
                drive, f"{w.id}. {w.title}", self.settings.drive_folder_id
            )
            try:
                p_id = create_spreadsheet_in_folder(
                    drive, f"{w.title} — список участников", folder_id
                )
                a_id = create_spreadsheet_in_folder(
                    drive, f"{w.title} — посещаемость", folder_id
                )
                share_with(drive, p_id, sa)
                share_with(drive, a_id, sa)

                p_ws = self.gc.open_by_key(p_id).get_worksheet(0)
                p_ws.update_title("Участники")
                p_ws.update(
                    f"A1:{col_letter(len(PARTICIPANTS_HEADERS))}1",
                    [PARTICIPANTS_HEADERS],
                    value_input_option="USER_ENTERED",
                )

                a_sp = self.gc.open_by_key(a_id)
                self._fill_attendance_sheets(a_sp, w, old_dump=None)
            except Exception:
                try:
                    delete_file(drive, folder_id)
                except Exception as e:
                    print(f"[drive] не удалось убрать сироту: {e}")
                raise
            return folder_id, p_id, a_id

        return await asyncio.to_thread(_sync)

    # ==================================================
    # ЛИСТЫ ПОСЕЩАЕМОСТИ
    # ==================================================

    def _fill_attendance_sheets(self, spreadsheet, w: Workshop, old_dump: dict | None):
        """Создаёт листы посещаемости; если в old_dump есть лист с таким же
        заголовком — переносит его строки вместе с отметками.
        Имена листов гарантированно уникальны."""
        if w.format == "базовая":
            dates = [w.date1] + ([w.date2] if w.date2 else [])
            titles = [(d or f"Занятие {i + 1}")[:100] for i, d in enumerate(dates)]
        else:
            titles = ["Посещаемость"]

        used = set()
        for i, title in enumerate(titles):
            base = title
            n = 2
            while title in used:
                title = f"{base} ({n})"
                n += 1
            used.add(title)

            if i == 0:
                ws = spreadsheet.get_worksheet(0)
                ws.update_title(title)
            else:
                ws = spreadsheet.add_worksheet(
                    title=title, rows=w.quota + EXTRA_ROWS + 2, cols=8
                )

            old_rows = (old_dump or {}).get(base) or (old_dump or {}).get(title)
            if old_rows:
                width = max(len(r) for r in old_rows)
                padded = [r + [""] * (width - len(r)) for r in old_rows]
                ws.update(
                    f"A1:{col_letter(width)}{len(padded)}",
                    padded,
                    value_input_option="USER_ENTERED",
                )
                header = old_rows[0]
                mark_cols = [
                    j for j, h in enumerate(header)
                    if str(h).strip() == "Отметка" or str(h).startswith("Занятие")
                ]
                hide = None
                for j, h in enumerate(header):
                    if str(h).strip().lower() == "telegram_id":
                        hide = j
                if hide is not None:
                    self._apply_formatting(ws, len(padded), mark_cols, hide)
            elif w.format == "базовая":
                self._fill_basic(ws, w.quota)
            else:
                self._fill_special(ws, w)

    def _fill_basic(self, ws, quota: int):
        rows = [["№ п/п", "ФИО", "Группа", "Ссылка в телеграм", "Отметка", "telegram_id"]]
        for i in range(1, quota + EXTRA_ROWS + 1):
            rows.append([i, "", "", "", "", ""])
        last = len(rows)
        ws.update(f"A1:F{last}", rows, value_input_option="USER_ENTERED")
        self._apply_formatting(ws, last, mark_cols=[4], hide_col=5)

    def _fill_special(self, ws, w: Workshop):
        lessons = max(w.lessons_count or 1, 1)
        sess_start = "E"
        last_sess = col_letter(4 + lessons)
        hidden_col = col_letter(6 + lessons)

        header = ["№ п/п", "ФИО", "Группа", "Ссылка в телеграм"]
        header += [f"Занятие {i}" for i in range(1, lessons + 1)]
        header += ["Посещено занятий", "telegram_id"]
        rows = [header]

        for i in range(1, quota_rows(w.quota) + 1):
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
    # ЛЮДИ В ФАЙЛЕ ПОСЕЩАЕМОСТИ
    # ==================================================

    def _target_sheet(self, spreadsheet, w: Workshop, slot: int):
        if w.format == "базовая":
            idx = 0 if slot == 1 else 1
            sheets = spreadsheet.worksheets()
            return sheets[min(idx, len(sheets) - 1)]
        return spreadsheet.worksheets()[0]

    async def add_person(
        self,
        file_id: str,
        w: Workshop,
        slot: int,
        full_name: str,
        group: str,
        link: str,
        telegram_id: int,
    ) -> bool:
        """Вписывает человека в первую пустую строку листа."""
        def _sync():
            spreadsheet = self.gc.open_by_key(file_id)
            ws = self._target_sheet(spreadsheet, w, slot)
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

    async def remove_person(
        self, file_id: str, w: Workshop, slot: int, telegram_id: int
    ) -> bool:
        """Освобождает строку человека: стирает ФИО, группу, ссылку, отметки
        и telegram_id, сохраняя номер строки и формулы. Освободившуюся строку
        займёт следующий записавшийся."""
        def _sync():
            spreadsheet = self.gc.open_by_key(file_id)
            ws = self._target_sheet(spreadsheet, w, slot)
            values = ws.get_all_values()
            if not values:
                return False
            header = [str(h) for h in values[0]]
            width = len(header)
            hidden_idx = width - 1
            lessons = sum(1 for h in header if h.startswith("Занятие"))

            for r in range(2, len(values) + 1):
                row = values[r - 1]
                tid = str(row[hidden_idx]).strip() if len(row) > hidden_idx else ""
                if tid != str(telegram_id):
                    continue

                cleared = [""] * width
                cleared[0] = row[0] if row else ""  # сохраняем № п/п
                if lessons:
                    cleared[4 + lessons] = (
                        f"=COUNTIF(E{r}:{col_letter(4 + lessons)}{r}, TRUE)"
                    )
                ws.update(
                    f"A{r}:{col_letter(width)}{r}",
                    [cleared],
                    value_input_option="USER_ENTERED",
                )
                return True
            return False

        return await asyncio.to_thread(_sync)

    # ==================================================
    # ДАМП / ВОССТАНОВЛЕНИЕ / ПЕРЕСБОР / РАСШИРЕНИЕ / УДАЛЕНИЕ
    # ==================================================

    def dump_attendance_sync(self, file_id: str) -> dict:
        spreadsheet = self.gc.open_by_key(file_id)
        return {ws.title: ws.get_all_values() for ws in spreadsheet.worksheets()}

    async def dump_attendance(self, file_id: str) -> dict:
        return await asyncio.to_thread(self.dump_attendance_sync, file_id)

    async def restore_workspace(self, w: Workshop, dump: dict | None) -> tuple:
        """Пересоздаёт папку и оба файла; листы посещаемости — из дампа."""
        def _sync():
            drive = user_drive(self.settings)
            sa = service_account_email(self.settings)

            folder_id = create_folder(
                drive, f"{w.id}. {w.title}", self.settings.drive_folder_id
            )
            p_id = create_spreadsheet_in_folder(
                drive, f"{w.title} — список участников", folder_id
            )
            a_id = create_spreadsheet_in_folder(
                drive, f"{w.title} — посещаемость", folder_id
            )
            share_with(drive, p_id, sa)
            share_with(drive, a_id, sa)

            p_ws = self.gc.open_by_key(p_id).get_worksheet(0)
            p_ws.update_title("Участники")
            p_ws.update(
                f"A1:{col_letter(len(PARTICIPANTS_HEADERS))}1",
                [PARTICIPANTS_HEADERS],
                value_input_option="USER_ENTERED",
            )

            a_sp = self.gc.open_by_key(a_id)
            self._fill_attendance_sheets(a_sp, w, old_dump=dump)
            return folder_id, p_id, a_id

        return await asyncio.to_thread(_sync)

    async def rebuild_attendance(self, w: Workshop) -> str:
        """Пересоздаёт файл посещаемости (после правки дат), сохраняя отметки
        листов, чьи заголовки не изменились. Возвращает новый file_id."""
        def _sync():
            old = {}
            if w.attendance_file_id:
                try:
                    old = self.dump_attendance_sync(w.attendance_file_id)
                except Exception:
                    old = {}
                try:
                    delete_file(user_drive(self.settings), w.attendance_file_id)
                except Exception:
                    pass

            drive = user_drive(self.settings)
            sa = service_account_email(self.settings)
            folder_id = w.drive_folder_id or create_folder(
                drive, f"{w.id}. {w.title}", self.settings.drive_folder_id
            )
            a_id = create_spreadsheet_in_folder(
                drive, f"{w.title} — посещаемость", folder_id
            )
            share_with(drive, a_id, sa)

            a_sp = self.gc.open_by_key(a_id)
            self._fill_attendance_sheets(a_sp, w, old_dump=old)
            return a_id

        return await asyncio.to_thread(_sync)

    async def resize_quota(self, w: Workshop):
        """Дописывает недостающие строки в листы посещаемости после увеличения
        квоты (in-place, ссылка не меняется). При уменьшении ничего не удаляет."""
        def _sync():
            if not w.attendance_file_id:
                return
            spreadsheet = self.gc.open_by_key(w.attendance_file_id)
            need = quota_rows(w.quota)

            for ws in spreadsheet.worksheets():
                values = ws.get_all_values()
                if not values or len(values) < 2:
                    continue
                header = [str(h) for h in values[0]]
                mark_cols = [
                    j for j, h in enumerate(header)
                    if h.strip() == "Отметка" or h.startswith("Занятие")
                ]
                hide = None
                for j, h in enumerate(header):
                    if h.strip().lower() == "telegram_id":
                        hide = j
                lessons = sum(1 for h in header if h.startswith("Занятие"))

                if lessons:  # специальная: есть строка ИТОГО
                    total_idx = None
                    for i, row in enumerate(values):
                        if len(row) > 1 and str(row[1]).strip() == "ИТОГО":
                            total_idx = i
                            break
                    if total_idx is None:
                        continue
                    person = values[1:total_idx]
                    if need <= len(person):
                        continue
                    new_person = [list(r) for r in person]
                    for n in range(len(person) + 1, need + 1):
                        r = len(new_person) + 2
                        new_person.append([
                            n, "", "", "",
                            *([""] * lessons),
                            f"=COUNTIF(E{r}:{col_letter(4 + lessons)}{r}, TRUE)",
                            "",
                        ])
                    person_end = len(new_person) + 1
                    total = ["", "ИТОГО", "", ""]
                    for c in range(5, 5 + lessons):
                        letter = col_letter(c)
                        total.append(f"=COUNTIF({letter}2:{letter}{person_end}, TRUE)")
                    total += ["", ""]
                    rows = [header] + new_person + [total]
                else:  # базовая: только нумерованные строки
                    person = values[1:]
                    if need <= len(person):
                        continue
                    rows = [list(header)] + [list(r) for r in person]
                    for n in range(len(person) + 1, need + 1):
                        rows.append([n, "", "", "", "", ""])

                width = max(len(r) for r in rows)
                padded = [list(r) + [""] * (width - len(r)) for r in rows]
                ws.clear()
                ws.update(
                    f"A1:{col_letter(width)}{len(padded)}",
                    padded,
                    value_input_option="USER_ENTERED",
                )
                if hide is not None:
                    self._apply_formatting(ws, len(padded), mark_cols, hide)

        await asyncio.to_thread(_sync)

    async def delete_workspace(self, w: Workshop):
        """Удаляет папку мастерской вместе с обоими файлами."""
        def _sync():
            drive = user_drive(self.settings)
            if w.drive_folder_id:
                try:
                    delete_file(drive, w.drive_folder_id)
                    return
                except Exception as e:
                    print(f"[drive] папку не удалось удалить: {e}")
            for fid in (w.participants_file_id, w.attendance_file_id):
                if fid:
                    try:
                        delete_file(drive, fid)
                    except Exception:
                        pass

        await asyncio.to_thread(_sync)
    # ==================================================
    # НОВОЕ: РАЗДЕЛИТЕЛЬ АРХИВА (для перевыпуска мастерских)
    # ==================================================

    async def add_archive_separator(self, w: Workshop):
        """Добавляет разделитель в таблицу участников перед архивацией эпохи."""

        def _sync():
            if not w.participants_file_id:
                return
            spreadsheet = self.gc.open_by_key(w.participants_file_id)
            ws = spreadsheet.get_worksheet(0)

            values = ws.get_all_values()
            if not values:
                return

            last_row = len(values)
            archive_date = datetime.now().strftime("%d.%m.%Y %H:%M")

            separator_rows = [
                [""] * len(PARTICIPANTS_HEADERS),
                [f"═══ НОВАЯ ЭПОХА {archive_date} ═══"] + [""] * (len(PARTICIPANTS_HEADERS) - 1),
                [""] * len(PARTICIPANTS_HEADERS),
            ]

            ws.append_rows(separator_rows, value_input_option="USER_ENTERED")

            start_row = last_row + 1
            spreadsheet.batch_update({"requests": [{
                "repeatCell": {
                    "range": {
                        "sheetId": ws.id,
                        "startRowIndex": start_row,
                        "endRowIndex": start_row + 1,
                        "startColumnIndex": 0,
                        "endColumnIndex": len(PARTICIPANTS_HEADERS),
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "textFormat": {"bold": True}
                        }
                    },
                    "fields": "userEnteredFormat.textFormat.bold"
                }
            }]})

            print(f"[attendance] добавлен разделитель архива для мастерской {w.id}")

        await asyncio.to_thread(_sync)