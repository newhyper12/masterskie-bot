# db.py
# SQLite — источник правды бота. Авто-миграция схемы при старте.

from __future__ import annotations

import json
import sqlite3
import threading
import zlib
from datetime import datetime
from typing import List, Optional

from models import FormatInfo, Profile, Record, Workshop

ACTIVE = ("основной", "резерв")
BACKUPS_TO_KEEP = 3


class DB:
    def __init__(self, path: str = "bot.db"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.lock = threading.Lock()
        self._init_schema()
        self._migrate()

    def _init_schema(self):
        with self.lock, self.conn:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS profiles (
                    telegram_id INTEGER PRIMARY KEY,
                    full_name TEXT, "group" TEXT, phone TEXT,
                    email TEXT, nickname TEXT,
                    consent_date TEXT, updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS workshops (
                    id INTEGER PRIMARY KEY,
                    title TEXT, format TEXT, description TEXT,
                    date1 TEXT, date2 TEXT, location TEXT,
                    lessons INTEGER, days TEXT, quota INTEGER,
                    photo TEXT, open_date TEXT, close_date TEXT,
                    is_open INTEGER, attendance_file_id TEXT,
                    deleted INTEGER DEFAULT 0,
                    drive_folder_id TEXT, participants_file_id TEXT
                );
                CREATE TABLE IF NOT EXISTS records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER, username TEXT,
                    workshop_id INTEGER, slot INTEGER DEFAULT 1,
                    status TEXT, created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS formats (
                    name TEXT PRIMARY KEY, photo TEXT
                );
                CREATE TABLE IF NOT EXISTS kv (
                    key TEXT PRIMARY KEY, value TEXT
                );
                CREATE TABLE IF NOT EXISTS backups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workshop_id INTEGER, created_at TEXT, payload BLOB
                );
                """
            )

    def _migrate(self):
        """Добавляет недостающие колонки в старые таблицы."""
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(workshops)").fetchall()}
        with self.lock, self.conn:
            if "drive_folder_id" not in cols:
                self.conn.execute("ALTER TABLE workshops ADD COLUMN drive_folder_id TEXT")
            if "participants_file_id" not in cols:
                self.conn.execute("ALTER TABLE workshops ADD COLUMN participants_file_id TEXT")

    # ==================================================
    # ПРОФИЛИ
    # ==================================================

    def get_profile(self, telegram_id: int) -> Optional[Profile]:
        row = self.conn.execute(
            "SELECT * FROM profiles WHERE telegram_id=?", (telegram_id,)
        ).fetchone()
        if not row:
            return None
        return Profile(**{k: row[k] for k in row.keys()})

    def save_profile(self, p: Profile):
        with self.lock, self.conn:
            self.conn.execute(
                """INSERT INTO profiles VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(telegram_id) DO UPDATE SET
                     full_name=excluded.full_name, "group"=excluded."group",
                     phone=excluded.phone, email=excluded.email,
                     nickname=excluded.nickname,
                     consent_date=excluded.consent_date,
                     updated_at=excluded.updated_at""",
                (p.telegram_id, p.full_name, p.group, p.phone, p.email,
                 p.nickname, p.consent_date, p.updated_at),
            )

    # ==================================================
    # ФОРМАТЫ
    # ==================================================

    def get_formats(self) -> List[FormatInfo]:
        rows = self.conn.execute(
            "SELECT name, photo FROM formats ORDER BY name"
        ).fetchall()
        return [FormatInfo(name=r["name"], photo=r["photo"]) for r in rows]

    def set_format_photo(self, name: str, photo: str):
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT INTO formats(name, photo) VALUES(?,?) "
                "ON CONFLICT(name) DO UPDATE SET photo=excluded.photo",
                (name, photo),
            )

    # ==================================================
    # МАСТЕРСКИЕ
    # ==================================================

    @staticmethod
    def _row_to_workshop(row) -> Workshop:
        return Workshop(
            id=row["id"], title=row["title"], format=row["format"],
            description=row["description"], date1=row["date1"],
            date2=row["date2"], location=row["location"],
            lessons_count=row["lessons"], days=row["days"],
            quota=row["quota"], photo=row["photo"],
            open_date=row["open_date"], close_date=row["close_date"],
            is_open=bool(row["is_open"]),
            attendance_file_id=row["attendance_file_id"] or None,
            deleted=bool(row["deleted"]),
            drive_folder_id=row["drive_folder_id"] if "drive_folder_id" in row.keys() else None,
            participants_file_id=row["participants_file_id"] if "participants_file_id" in row.keys() else None,
        )

    def get_workshops(
        self,
        only_open: bool = False,
        include_deleted: bool = False,
        format_filter: Optional[str] = None,
    ) -> List[Workshop]:
        rows = self.conn.execute(
            "SELECT * FROM workshops ORDER BY id"
        ).fetchall()
        now = datetime.now()
        result = []
        for row in rows:
            w = self._row_to_workshop(row)
            if w.deleted and not include_deleted:
                continue
            if format_filter and w.format != format_filter.lower():
                continue

            open_eff = w.is_open
            if not open_eff and w.open_date:
                try:
                    open_eff = datetime.fromisoformat(w.open_date) <= now
                except ValueError:
                    pass
            if open_eff and w.close_date:
                try:
                    if datetime.fromisoformat(w.close_date) <= now:
                        open_eff = False
                except ValueError:
                    pass

            if only_open and not open_eff:
                continue
            w.is_open = open_eff
            result.append(w)
        return result

    def get_workshops_raw(self, include_deleted: bool = False) -> List[Workshop]:
        rows = self.conn.execute(
            "SELECT * FROM workshops ORDER BY id"
        ).fetchall()
        result = []
        for row in rows:
            w = self._row_to_workshop(row)
            if w.deleted and not include_deleted:
                continue
            result.append(w)
        return result

    def get_workshop(self, workshop_id: int) -> Optional[Workshop]:
        row = self.conn.execute(
            "SELECT * FROM workshops WHERE id=?", (workshop_id,)
        ).fetchone()
        return self._row_to_workshop(row) if row else None

    def next_workshop_id(self) -> int:
        row = self.conn.execute(
            "SELECT MAX(id) AS m FROM workshops"
        ).fetchone()
        return (row["m"] or 0) + 1

    def create_workshop(self, w: Workshop):
        with self.lock, self.conn:
            self.conn.execute(
                """INSERT OR REPLACE INTO workshops VALUES
                   (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (w.id, w.title, w.format, w.description, w.date1, w.date2,
                 w.location, w.lessons_count, w.days, w.quota, w.photo,
                 w.open_date, w.close_date, int(w.is_open),
                 w.attendance_file_id, int(w.deleted),
                 w.drive_folder_id, w.participants_file_id),
            )

    def update_workshop(self, workshop_id: int, **fields):
        allowed = {
            "title", "format", "description", "date1", "date2", "location",
            "lessons_count", "days", "quota", "photo", "open_date",
            "close_date", "is_open", "attendance_file_id", "deleted",
            "drive_folder_id", "participants_file_id",
        }
        cols, vals = [], []
        for k, v in fields.items():
            if k not in allowed:
                continue
            if k == "lessons_count":
                k = "lessons"
            if k in ("is_open", "deleted"):
                v = int(v)
            cols.append(f"{k}=?")
            vals.append(v)
        if not cols:
            return
        vals.append(workshop_id)
        with self.lock, self.conn:
            self.conn.execute(
                f"UPDATE workshops SET {', '.join(cols)} WHERE id=?", vals
            )

    # ==================================================
    # ЗАПИСИ
    # ==================================================

    def add_record(self, r: Record) -> int:
        with self.lock, self.conn:
            cur = self.conn.execute(
                """INSERT INTO records
                   (telegram_id, username, workshop_id, slot, status, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (r.telegram_id, r.username, r.workshop_id, r.slot,
                 r.status, r.created_at),
            )
            return cur.lastrowid

    def get_user_record(
        self, telegram_id: int, workshop_id: int
    ) -> Optional[Record]:
        row = self.conn.execute(
            """SELECT * FROM records
               WHERE telegram_id=? AND workshop_id=? AND status IN (?,?)
               ORDER BY id DESC LIMIT 1""",
            (telegram_id, workshop_id, *ACTIVE),
        ).fetchone()
        return self._row_to_records(row) if row else None

    def get_user_records(self, telegram_id: int) -> List[Record]:
        rows = self.conn.execute(
            """SELECT * FROM records WHERE telegram_id=? AND status IN (?,?)
               ORDER BY id""",
            (telegram_id, *ACTIVE),
        ).fetchall()
        return [self._row_to_records(r) for r in rows]

    def count_active(self, workshop_id: int, slot: int) -> int:
        row = self.conn.execute(
            """SELECT COUNT(*) AS c FROM records
               WHERE workshop_id=? AND slot=? AND status='основной'""",
            (workshop_id, slot),
        ).fetchone()
        return row["c"]

    def get_workshop_records(
        self, workshop_id: int, statuses: List[str]
    ) -> List[Record]:
        if not statuses:
            return []
        q = ",".join("?" for _ in statuses)
        rows = self.conn.execute(
            f"SELECT * FROM records WHERE workshop_id=? AND status IN ({q})",
            (workshop_id, *statuses),
        ).fetchall()
        return [self._row_to_records(r) for r in rows]

    def all_records(self) -> List[Record]:
        rows = self.conn.execute("SELECT * FROM records ORDER BY id").fetchall()
        return [self._row_to_records(r) for r in rows]

    def set_record_status(self, record_id: int, status: str):
        with self.lock, self.conn:
            self.conn.execute(
                "UPDATE records SET status=? WHERE id=?", (status, record_id)
            )

    def first_reserve(self, workshop_id: int, slot: int) -> Optional[Record]:
        row = self.conn.execute(
            """SELECT * FROM records
               WHERE workshop_id=? AND slot=? AND status='резерв'
               ORDER BY id LIMIT 1""",
            (workshop_id, slot),
        ).fetchone()
        return self._row_to_records(row) if row else None

    def get_record(self, record_id: int) -> Optional[Record]:
        row = self.conn.execute(
            "SELECT * FROM records WHERE id=?", (record_id,)
        ).fetchone()
        return self._row_to_records(row) if row else None

    def get_reserves(self, workshop_id: int, slot: int) -> List[Record]:
        rows = self.conn.execute(
            """SELECT * FROM records
               WHERE workshop_id=? AND slot=? AND status='резерв'
               ORDER BY id""",
            (workshop_id, slot),
        ).fetchall()
        return [self._row_to_records(r) for r in rows]

    @staticmethod
    def _row_to_records(row) -> Record:
        return Record(
            id=row["id"], telegram_id=row["telegram_id"],
            username=row["username"], workshop_id=row["workshop_id"],
            slot=row["slot"], status=row["status"], created_at=row["created_at"],
        )

    # ==================================================
    # KV (фото/текст приветствия, ключи предложений)
    # ==================================================

    def kv_get(self, key: str) -> Optional[str]:
        row = self.conn.execute(
            "SELECT value FROM kv WHERE key=?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def kv_set(self, key: str, value: str):
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT INTO kv(key, value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    # ==================================================
    # РЕЗЕРВНЫЕ КОПИИ (zlib level 9, храним последние 3)
    # ==================================================

    def save_backup(self, workshop_id: int, data: dict):
        payload = zlib.compress(
            json.dumps(data, ensure_ascii=False).encode("utf-8"), 9
        )
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT INTO backups(workshop_id, created_at, payload) "
                "VALUES(?,?,?)",
                (workshop_id, datetime.now().isoformat(), payload),
            )
            self.conn.execute(
                """DELETE FROM backups WHERE id NOT IN (
                     SELECT id FROM backups WHERE workshop_id=?
                     ORDER BY id DESC LIMIT ?
                   ) AND workshop_id=?""",
                (workshop_id, BACKUPS_TO_KEEP, workshop_id),
            )

    def latest_backup(self, workshop_id: int) -> Optional[dict]:
        row = self.conn.execute(
            """SELECT payload FROM backups WHERE workshop_id=?
               ORDER BY id DESC LIMIT 1""",
            (workshop_id,),
        ).fetchone()
        if not row:
            return None
        return json.loads(zlib.decompress(row["payload"]).decode("utf-8"))

    def has_backups(self, workshop_id: int) -> bool:
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM backups WHERE workshop_id=?",
            (workshop_id,),
        ).fetchone()
        return row["c"] > 0