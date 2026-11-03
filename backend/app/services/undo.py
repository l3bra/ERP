"""Одношаговая отмена изменений (таблица undo_history)."""

import json
from contextlib import contextmanager
from typing import Iterator

from fastapi import HTTPException

from ..database import Connection
from ..utils import now

UNDO_TABLES = ("items", "logs", "log_note_groups", "log_note_group_entries")

COLUMNS_BY_TABLE = {
    "items": ("id", "product", "color", "batch", "date", "qty", "sort_order"),
    "logs": (
        "id", "ts", "kind", "item_id", "product", "color", "batch",
        "old_qty", "new_qty", "diff", "type", "note",
    ),
    "log_note_groups": ("id", "code", "url", "text"),
    "log_note_group_entries": ("id", "group_id", "log_id", "previous_note"),
}


class UndoManager:
    """Снимает снимки таблиц до/после изменения и умеет их восстанавливать.

    История хранится в undo_history; отмена одношаговая: при записи нового
    изменения прежние отменённые записи удаляются.
    """

    def __init__(self, conn: Connection):
        self.conn = conn

    def capture_state(self) -> dict[str, dict[int, dict]]:
        return {
            table: {
                row["id"]: dict(row)
                for row in self.conn.execute(f"SELECT * FROM {table} ORDER BY id")
            }
            for table in UNDO_TABLES
        }

    @contextmanager
    def undoable(self, action: str) -> Iterator[None]:
        """Оборачивает изменение: при отличии состояния записывает шаг отмены."""
        before = self.capture_state()
        yield
        after = self.capture_state()
        changes = {}
        for table in before:
            rows = []
            for row_id in before[table].keys() | after[table].keys():
                old_row = before[table].get(row_id)
                new_row = after[table].get(row_id)
                if old_row != new_row:
                    rows.append({"id": row_id, "before": old_row})
            if rows:
                changes[table] = rows
        if changes:
            self.conn.execute("DELETE FROM undo_history WHERE undone_at IS NOT NULL")
            self.conn.execute(
                "INSERT INTO undo_history(created_at, action, before_state) VALUES (?, ?, ?)",
                (now(), action, json.dumps(changes, ensure_ascii=False)),
            )

    def restore_state(self, before_state: dict) -> None:
        """Восстанавливает таблицы по снимку, проверяя его формат."""
        if not isinstance(before_state, dict):
            raise HTTPException(500, "История отмены имеет неверный формат")
        for table in UNDO_TABLES:
            entries = before_state.get(table, [])
            if not isinstance(entries, list):
                raise HTTPException(500, "История отмены имеет неверный формат")
            if not entries:
                continue
            if any(
                not isinstance(entry, dict)
                or not isinstance(entry.get("id"), int)
                or (entry.get("before") is not None
                    and (not isinstance(entry["before"], dict)
                         or set(entry["before"]) != set(COLUMNS_BY_TABLE[table])))
                for entry in entries
            ):
                raise HTTPException(500, "История отмены содержит некорректную запись")
            self.conn.executemany(f"DELETE FROM {table} WHERE id=?", ((entry["id"],) for entry in entries))
            for entry in entries:
                row = entry.get("before")
                if row is None:
                    continue
                columns = COLUMNS_BY_TABLE[table]
                self.conn.execute(
                    f"INSERT INTO {table} ({', '.join(columns)}) "
                    f"VALUES ({', '.join('?' for _ in columns)})",
                    tuple(row[column] for column in columns),
                )

    def undo_last(self) -> dict:
        """Отменяет последнее неотменённое действие. История не удаляется — помечается."""
        entry = self.conn.one(
            "SELECT id, action, before_state FROM undo_history "
            "WHERE undone_at IS NULL ORDER BY id DESC LIMIT 1")
        if not entry:
            return {"undone": False, "action": None}
        try:
            before_state = json.loads(entry["before_state"])
        except json.JSONDecodeError as error:
            raise HTTPException(500, "История отмены повреждена") from error
        self.restore_state(before_state)
        self.conn.execute(
            "UPDATE undo_history SET undone_at=? WHERE id=?",
            (now(), entry["id"]),
        )
        return {"undone": True, "action": entry["action"]}
