"""Журнал операций: строки, разделители, месяцы, общие примечания."""

import urllib.parse
from datetime import date, datetime
from typing import Optional

from fastapi import HTTPException

from .. import config
from ..database import Connection
from ..utils import dump, now
from .undo import UndoManager


def validate_log_note_group_fields(data: dict) -> None:
    if data.get("url"):
        parsed_url = urllib.parse.urlparse(data["url"])
        if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
            raise HTTPException(400, "Ссылка должна начинаться с http:// или https://")
    if not any(data.get(field) for field in ("code", "url", "text")):
        raise HTTPException(400, "Укажите код, ссылку или текст примечания")


class JournalService:
    """Логика журнала: записи операций, разделители, месяцы, группы примечаний."""

    def __init__(self, conn: Connection):
        self.conn = conn
        self.undo = UndoManager(conn)

    # ---------- Разделители и месяцы ----------

    def ensure_months(self) -> None:
        """Создаёт вкладки месяцев от первого месяца в журнале до текущего.

        Ничего не удаляет. Вызывается при старте и при каждом обращении к журналу,
        поэтому новый месяц появляется сам при первом же заходе.
        """
        cur = datetime.now().strftime("%Y-%m")
        first = self.conn.scalar(
            "SELECT MIN(m) FROM (SELECT month AS m FROM log_months "
            "UNION SELECT substr(ts,1,7) FROM logs)") or cur
        if first > cur:
            first = cur
        y, m = map(int, first.split("-"))
        ey, em = map(int, cur.split("-"))
        while (y, m) <= (ey, em):
            self.conn.execute("INSERT OR IGNORE INTO log_months(month) VALUES (?)", (f"{y:04d}-{m:02d}",))
            m += 1
            if m == 13:
                y, m = y + 1, 1

    def ensure_daily_dividers(self, through: Optional[date] = None) -> list[str]:
        """Создаёт один разделитель дня за запрошенную дату, без заполнения пропусков."""
        through = through or datetime.now().date()
        self.conn.execute(
            "INSERT OR IGNORE INTO day_dividers(day, log_id) "
            "SELECT substr(ts, 1, 10), MIN(id) FROM logs "
            "WHERE kind='divider' AND (type='day' OR note LIKE '==== НОВЫЙ ДЕНЬ%') "
            "GROUP BY substr(ts, 1, 10)")
        self.conn.execute(
            "DELETE FROM day_dividers WHERE log_id IS NULL OR NOT EXISTS "
            "(SELECT 1 FROM logs WHERE logs.id=day_dividers.log_id)")
        day_key = through.isoformat()
        cursor = self.conn.execute(
            "INSERT OR IGNORE INTO day_dividers(day) VALUES (?)", (day_key,))
        if cursor.rowcount == 0:
            return []
        label = f"==== НОВЫЙ ДЕНЬ — {through.strftime('%d.%m.%Y')} ===="
        log_cursor = self.conn.execute(
            "INSERT INTO logs (ts, kind, type, note) VALUES (?, 'divider', 'day', ?)",
            (f"{day_key}T00:00:00", label),
        )
        self.conn.execute(
            "UPDATE day_dividers SET log_id=? WHERE day=?",
            (log_cursor.lastrowid, day_key),
        )
        return [day_key]

    def log_event(self, item, old: int, new: int, type_: str, note: Optional[str] = None) -> None:
        """Пишет строку операции в журнал (снимок реквизитов позиции)."""
        ts = now()
        self.ensure_daily_dividers(date.fromisoformat(ts[:10]))
        self.conn.execute(
            """INSERT INTO logs (ts, kind, item_id, product, color, batch,
                                 old_qty, new_qty, diff, type, note)
               VALUES (?, 'move', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ts, item["id"], item["product"], item["color"], item["batch"],
             old, new, new - old, type_, note),
        )

    def add_divider(self, kind: str) -> dict:
        """Добавляет идемпотентный разделитель дня либо разделитель инвентаризации."""
        with self.undo.undoable("Добавление разделителя журнала"):
            self.ensure_months()
            if kind == "day":
                created = self.ensure_daily_dividers()
                day = datetime.now().date().isoformat()
                row = self.conn.one(
                    "SELECT note FROM logs WHERE id=(SELECT log_id FROM day_dividers WHERE day=?)",
                    (day,),
                )
                return {"label": row["note"], "created": bool(created)}
            label = f"==== ИНВЕНТАРИЗАЦИЯ — {datetime.now().strftime('%d.%m.%Y %H:%M:%S')} ===="
            self.conn.execute(
                "INSERT INTO logs (ts, kind, type, note) VALUES (?, 'divider', ?, ?)",
                (now(), kind, label),
            )
        return {"label": label}

    def months(self) -> list[str]:
        """Список месяцев журнала (текущий создаётся автоматически)."""
        self.ensure_months()
        self.ensure_daily_dividers()
        rows = self.conn.all(
            "SELECT month FROM log_months UNION SELECT DISTINCT substr(ts,1,7) FROM logs ORDER BY 1")
        return [r[0] for r in rows]

    # ---------- Строки журнала ----------

    def list_logs(self, month: Optional[str]) -> list[dict]:
        """Записи журнала за месяц (по умолчанию текущий), от старых к новым."""
        month = month or datetime.now().strftime("%Y-%m")
        if not config.MONTH_RE.match(month):
            raise HTTPException(400, "Месяц в формате ГГГГ-ММ")
        self.ensure_months()
        self.ensure_daily_dividers()
        rows = self.conn.all(
            "SELECT * FROM logs WHERE substr(ts,1,7)=? ORDER BY ts, id", (month,))
        groups = self.conn.all(
            "SELECT e.log_id, g.id, g.code, g.url, g.text, "
            "(SELECT COUNT(*) FROM log_note_group_entries all_entries "
            "WHERE all_entries.group_id=g.id) AS member_count "
            "FROM log_note_group_entries e "
            "JOIN log_note_groups g ON g.id=e.group_id "
            "JOIN logs l ON l.id=e.log_id WHERE substr(l.ts,1,7)=?",
            (month,),
        )
        group_by_log = {
            entry["log_id"]: {
                "shared_note_group_id": entry["id"],
                "shared_note_code": entry["code"],
                "shared_note_url": entry["url"],
                "shared_note_text": entry["text"],
                "shared_note_count": entry["member_count"],
            }
            for entry in groups
        }
        return [
            {**dict(row), **group_by_log.get(row["id"], {})}
            for row in rows
        ]

    def update_log(self, log_id: int, data: dict) -> dict:
        """Правка строки журнала. Остатки в базе НЕ меняются — правится только запись."""
        with self.undo.undoable("Изменение записи журнала"):
            row = self.conn.one("SELECT * FROM logs WHERE id=?", (log_id,))
            if not row:
                raise HTTPException(404, "Запись не найдена")
            if row["kind"] == "divider":
                allowed = {k: v for k, v in data.items() if k == "note" and v is not None}
            else:
                if "note" in data and self.conn.one(
                    "SELECT 1 FROM log_note_group_entries WHERE log_id=?", (log_id,)):
                    raise HTTPException(400, "Измените общее примечание всей группы")
                allowed = {k: v for k, v in data.items()
                           if k in ("product", "color", "batch", "old_qty", "new_qty", "type", "note")
                           and (v is not None or k == "note")}
                if "old_qty" in allowed or "new_qty" in allowed:
                    old = allowed.get("old_qty", row["old_qty"]) or 0
                    new = allowed.get("new_qty", row["new_qty"]) or 0
                    allowed["diff"] = new - old
            if allowed:
                self.conn.execute(
                    f"UPDATE logs SET {', '.join(k + '=?' for k in allowed)} WHERE id=?",
                    (*allowed.values(), log_id),
                )
            return dict(self.conn.one("SELECT * FROM logs WHERE id=?", (log_id,)))

    def delete_log(self, log_id: int) -> None:
        """Удаляет одну запись журнала. Вкладки месяцев не удаляются никогда."""
        with self.undo.undoable("Удаление записи журнала"):
            if not self.conn.one("SELECT 1 FROM logs WHERE id=?", (log_id,)):
                raise HTTPException(404, "Запись не найдена")
            group = self.conn.one(
                "SELECT group_id FROM log_note_group_entries WHERE log_id=?", (log_id,))
            self.conn.execute("DELETE FROM log_note_group_entries WHERE log_id=?", (log_id,))
            if group:
                remaining = self.conn.all(
                    "SELECT log_id, previous_note FROM log_note_group_entries WHERE group_id=?",
                    (group["group_id"],))
                if len(remaining) == 1:
                    self.conn.execute(
                        "UPDATE logs SET note=? WHERE id=?",
                        (remaining[0]["previous_note"], remaining[0]["log_id"]),
                    )
                    self.conn.execute(
                        "DELETE FROM log_note_group_entries WHERE group_id=?",
                        (group["group_id"],),
                    )
                if len(remaining) <= 1:
                    self.conn.execute(
                        "DELETE FROM log_note_groups WHERE id=?", (group["group_id"],))
            self.conn.execute("DELETE FROM logs WHERE id=?", (log_id,))

    # ---------- Общие примечания групп ----------

    def create_note_group(self, body) -> dict:
        """Объединяет примечания выбранных строк журнала в общую ячейку."""
        if len(set(body.ids)) != len(body.ids):
            raise HTTPException(400, "Строки журнала выбраны несколько раз")
        data = dump(body)
        validate_log_note_group_fields(data)
        with self.undo.undoable("Объединение примечаний журнала"):
            placeholders = ",".join("?" for _ in body.ids)
            rows = self.conn.all(
                f"SELECT id, kind, note FROM logs WHERE id IN ({placeholders})",
                body.ids,
            )
            if len(rows) != len(body.ids):
                raise HTTPException(404, "Одна или несколько строк журнала не найдены")
            if any(row["kind"] != "move" for row in rows):
                raise HTTPException(400, "Объединять можно только строки операций")

            previous_notes = {}
            old_group_ids = {
                row["group_id"] for row in self.conn.all(
                    f"SELECT DISTINCT group_id FROM log_note_group_entries "
                    f"WHERE log_id IN ({placeholders})",
                    body.ids,
                )
            }
            old_entries = self.conn.all(
                f"SELECT log_id, previous_note FROM log_note_group_entries "
                f"WHERE log_id IN ({placeholders})",
                body.ids,
            )
            previous_notes.update({row["log_id"]: row["previous_note"] for row in old_entries})
            for row in rows:
                previous_notes.setdefault(row["id"], row["note"])

            self.conn.execute(
                "INSERT INTO log_note_groups(code, url, text) VALUES (?, ?, ?)",
                (data.get("code"), data.get("url"), data.get("text")),
            )
            group_id = self.conn.scalar("SELECT last_insert_rowid()")
            self.conn.execute(
                f"DELETE FROM log_note_group_entries WHERE log_id IN ({placeholders})",
                body.ids,
            )
            self.conn.executemany(
                "INSERT INTO log_note_group_entries(group_id, log_id, previous_note) "
                "VALUES (?, ?, ?)",
                ((group_id, log_id, previous_notes[log_id]) for log_id in body.ids),
            )
            for old_group_id in old_group_ids:
                remaining = self.conn.all(
                    "SELECT log_id, previous_note FROM log_note_group_entries WHERE group_id=?",
                    (old_group_id,),
                )
                if len(remaining) == 1:
                    self.conn.execute(
                        "UPDATE logs SET note=? WHERE id=?",
                        (remaining[0]["previous_note"], remaining[0]["log_id"]),
                    )
                    self.conn.execute(
                        "DELETE FROM log_note_group_entries WHERE group_id=?",
                        (old_group_id,),
                    )
            self.conn.execute(
                "DELETE FROM log_note_groups WHERE NOT EXISTS "
                "(SELECT 1 FROM log_note_group_entries WHERE group_id=log_note_groups.id)")
        return {"id": group_id, "ids": body.ids,
                **{key: data.get(key) for key in ("code", "url", "text")}}

    def update_note_group(self, group_id: int, data: dict) -> dict:
        with self.undo.undoable("Изменение общего примечания журнала"):
            group = self.conn.one(
                "SELECT id, code, url, text FROM log_note_groups WHERE id=?", (group_id,))
            if not group:
                raise HTTPException(404, "Общее примечание не найдено")
            fields = {**dict(group), **data}
            validate_log_note_group_fields(fields)
            self.conn.execute(
                "UPDATE log_note_groups SET code=?, url=?, text=? WHERE id=?",
                (fields["code"], fields["url"], fields["text"], group_id),
            )
        return {"id": group_id, **{key: fields[key] for key in ("code", "url", "text")}}

    def delete_note_group(self, group_id: int) -> dict:
        """Разъединяет общее примечание: участникам возвращаются их прежние примечания."""
        with self.undo.undoable("Разъединение примечания журнала"):
            group = self.conn.one("SELECT id FROM log_note_groups WHERE id=?", (group_id,))
            if not group:
                raise HTTPException(404, "Общее примечание не найдено")
            entries = self.conn.all(
                "SELECT log_id, previous_note FROM log_note_group_entries WHERE group_id=?",
                (group_id,),
            )
            self.conn.executemany(
                "UPDATE logs SET note=? WHERE id=?",
                ((entry["previous_note"], entry["log_id"]) for entry in entries),
            )
            self.conn.execute("DELETE FROM log_note_group_entries WHERE group_id=?", (group_id,))
            self.conn.execute("DELETE FROM log_note_groups WHERE id=?", (group_id,))
        return {"ok": True}
