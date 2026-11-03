"""Линейки, справочник цветов и заливки таблиц."""

import sqlite3

from fastapi import HTTPException

from ..database import Connection
from ..utils import dump


class CatalogService:
    """Каталог: линейки, их цвета, справочник цветов, стили таблиц."""

    def __init__(self, conn: Connection):
        self.conn = conn

    # ---------- Линейки ----------

    def list_lines(self) -> list[dict]:
        rows = self.conn.all(
            "SELECT name, color FROM lines ORDER BY sort_order, rowid")
        assignments = self.conn.all(
            "SELECT line_name, color_name FROM line_product_colors "
            "ORDER BY line_name, sort_order, rowid")
        colors_by_line = {}
        for assignment in assignments:
            colors_by_line.setdefault(assignment["line_name"], []).append(
                assignment["color_name"])
        return [
            {**dict(row), "product_colors": colors_by_line.get(row["name"], [])}
            for row in rows
        ]

    def create_line(self, body) -> dict:
        try:
            self.conn.execute("INSERT INTO lines(name, color) VALUES (?, ?)", (body.name, body.color))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Такая линейка уже есть")
        return {"name": body.name, "color": body.color}

    def update_line(self, body) -> dict:
        cur = self.conn.execute("UPDATE lines SET color=? WHERE name=?", (body.color, body.name))
        if cur.rowcount == 0:
            raise HTTPException(404, "Линейка не найдена")
        return {"name": body.name, "color": body.color}

    def delete_line(self, name: str) -> dict:
        if not self.conn.one("SELECT 1 FROM lines WHERE name=?", (name,)):
            raise HTTPException(404, "Линейка не найдена")
        self.conn.execute("DELETE FROM lines WHERE name=?", (name,))
        self.conn.execute("DELETE FROM line_product_colors WHERE line_name=?", (name,))
        return {"ok": True}

    def set_line_product_colors(self, line_name: str, body) -> dict:
        """Заменяет набор разрешённых цветов линейки."""
        normalized_colors = [name.strip() for name in body.colors]
        if any(not name for name in normalized_colors):
            raise HTTPException(400, "Название цвета не может быть пустым")
        if len({name.casefold() for name in normalized_colors}) != len(normalized_colors):
            raise HTTPException(400, "Цвет указан несколько раз")
        if not self.conn.one("SELECT 1 FROM lines WHERE name=?", (line_name,)):
            raise HTTPException(404, "Линейка не найдена")
        for name in normalized_colors:
            if not self.conn.one(
                "SELECT 1 FROM product_colors WHERE name=? COLLATE NOCASE", (name,)):
                raise HTTPException(400, f"Цвет «{name}» отсутствует в справочнике")
        self.conn.execute("DELETE FROM line_product_colors WHERE line_name=?", (line_name,))
        self.conn.executemany(
            "INSERT INTO line_product_colors(line_name, color_name, sort_order) VALUES (?, ?, ?)",
            ((line_name, name, index) for index, name in enumerate(normalized_colors)),
        )
        return {"line": line_name, "colors": normalized_colors}

    # ---------- Справочник цветов ----------

    def list_product_colors(self) -> list[dict]:
        rows = self.conn.all(
            "SELECT name, palette_index, rgb, opacity FROM product_colors "
            "ORDER BY sort_order, name COLLATE NOCASE")
        return [dict(row) for row in rows]

    def create_product_color(self, body) -> dict:
        try:
            order = self.conn.scalar(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM product_colors")
            self.conn.execute(
                "INSERT INTO product_colors(name, palette_index, rgb, opacity, sort_order) "
                "VALUES (?, ?, ?, ?, ?)",
                (body.name, body.palette_index, body.rgb.lower(), body.opacity, order),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Такой цвет уже есть")
        return {"name": body.name, "palette_index": body.palette_index,
                "rgb": body.rgb.lower(), "opacity": body.opacity}

    def update_product_color(self, name: str, body) -> dict:
        """Обновляет RGB и прозрачность существующего цвета."""
        changes = {key: value for key, value in dump(body).items() if value is not None}
        if not changes:
            raise HTTPException(400, "Не указаны изменения цвета")
        current = self.conn.one(
            "SELECT name, palette_index, rgb, opacity FROM product_colors "
            "WHERE name=? COLLATE NOCASE", (name,))
        if not current:
            raise HTTPException(404, "Цвет не найден")
        values = {**dict(current), **changes}
        self.conn.execute(
            "UPDATE product_colors SET rgb=?, opacity=? WHERE name=? COLLATE NOCASE",
            (values["rgb"].lower(), values["opacity"], name),
        )
        return {"name": current["name"], "rgb": values["rgb"].lower(),
                "opacity": values["opacity"]}

    def delete_product_color(self, name: str) -> dict:
        """Удаляет цвет из справочника и его привязки к линейкам.

        Позиции и история журнала остаются без изменений.
        """
        color = self.conn.one(
            "SELECT name FROM product_colors WHERE name=? COLLATE NOCASE", (name,))
        if not color:
            raise HTTPException(404, "Цвет не найден")
        self.conn.execute(
            "DELETE FROM line_product_colors WHERE color_name=? COLLATE NOCASE",
            (color["name"],),
        )
        self.conn.execute(
            "DELETE FROM product_colors WHERE name=? COLLATE NOCASE", (color["name"],))
        return {"name": color["name"], "ok": True}

    # ---------- Заливки таблиц ----------

    def list_styles(self) -> list[dict]:
        rows = self.conn.all(
            "SELECT table_name, target_type, row_key, column_key, color FROM table_styles")
        return [
            {"table": row["table_name"], "kind": row["target_type"],
             "row": row["row_key"], "column": row["column_key"], "color": row["color"]}
            for row in rows
        ]

    def save_style(self, body) -> dict:
        self.conn.execute(
            "INSERT INTO table_styles(table_name, target_type, row_key, column_key, color) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(table_name, target_type, row_key, column_key) "
            "DO UPDATE SET color=excluded.color",
            (body.table, body.kind, body.row, body.column, body.color),
        )
        return {
            "table": body.table, "kind": body.kind, "row": body.row,
            "column": body.column, "color": body.color,
        }

    def delete_style(self, body) -> dict:
        self.conn.execute(
            "DELETE FROM table_styles WHERE table_name=? AND target_type=? "
            "AND row_key=? AND column_key=?",
            (body.table, body.kind, body.row, body.column),
        )
        return {"ok": True}
