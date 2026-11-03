"""Позиции базы: остатки, партии, порядок строк и печать."""

import sqlite3

from fastapi import HTTPException

from .. import config
from ..database import Connection
from ..utils import dump, now
from .journal import JournalService
from .undo import UndoManager


class InventoryService:
    """Бизнес-логика остатков: партии, изменения количества, порядок строк."""

    def __init__(self, conn: Connection):
        self.conn = conn
        self.journal = JournalService(conn)
        self.undo = UndoManager(conn)

    def get_item(self, item_id: int):
        row = self.conn.one("SELECT * FROM items WHERE id=?", (item_id,))
        if not row:
            raise HTTPException(404, "Позиция не найдена")
        return row

    def apply_change(self, item, new_qty: int, type_: str, note=None) -> dict:
        """Единая точка изменения остатка: обновляет qty и пишет строку в журнал."""
        old_qty = item["qty"]
        new_qty = max(0, new_qty)
        self.conn.execute("UPDATE items SET qty=? WHERE id=?", (new_qty, item["id"]))
        self.journal.log_event(item, old_qty, new_qty, type_, note)
        return {"id": item["id"], "old_qty": old_qty, "new_qty": new_qty,
                "diff": new_qty - old_qty, "type": type_}

    def place_item_in_line(self, item_id: int, product: str) -> None:
        """Переносит позицию в конец группы с тем же product (по sort_order)."""
        rows = self.conn.all(
            "SELECT id, product FROM items WHERE id != ? ORDER BY sort_order, id",
            (item_id,),
        )
        ordered = [row["id"] for row in rows]
        insert_at = max(
            (index + 1 for index, row in enumerate(rows) if row["product"] == product),
            default=len(ordered),
        )
        ordered.insert(insert_at, item_id)
        self.conn.executemany(
            "UPDATE items SET sort_order=? WHERE id=?",
            ((index, current_id) for index, current_id in enumerate(ordered)),
        )

    # ---------- Чтение ----------

    def list_items(self) -> list[dict]:
        rows = self.conn.all("SELECT * FROM items ORDER BY sort_order, id")
        return [dict(r) for r in rows]

    def local_stock_groups(self) -> list:
        """Локальные остатки, сумма по цвету (для сравнения с МойСклад)."""
        return self.conn.all(
            """
            WITH grouped AS (
                SELECT color COLLATE NOCASE AS color_key,
                       SUM(qty) AS quantity,
                       MIN(sort_order) AS first_order,
                       MIN(id) AS first_id
                FROM items
                GROUP BY color COLLATE NOCASE
                HAVING SUM(qty) <> 0
            )
            SELECT (
                SELECT item.color
                FROM items AS item
                WHERE item.color = grouped.color_key COLLATE NOCASE
                ORDER BY item.sort_order, item.id
                LIMIT 1
            ) AS name, quantity
            FROM grouped
            ORDER BY first_order, first_id
            """
        )

    def print_layout(self) -> dict:
        """Раскладка в две колонки для А4, сохраняющая порядок базы."""
        rows = self.conn.all("SELECT * FROM items ORDER BY sort_order, id")
        groups: dict = {}
        for r in rows:
            groups.setdefault(r["product"], []).append(
                {"color": r["color"], "batch": r["batch"], "date": r["date"], "qty": r["qty"]})
        left, right = [], []
        lh = rh = 0
        for product, g in groups.items():
            h = len(g) + 1
            if lh <= rh:
                left.append({"product": product, "rows": g}); lh += h
            else:
                right.append({"product": product, "rows": g}); rh += h
        return {"left": left, "right": right, "generated": now()}

    # ---------- Изменение ----------

    def reorder_items(self, body) -> dict:
        """Новый порядок позиций; перемещение допускается только внутри линейки."""
        with self.undo.undoable("Изменение порядка позиций"):
            rows = self.conn.all("SELECT id, product FROM items ORDER BY sort_order, id")
            existing_ids = [row["id"] for row in rows]
            if len(body.ids) != len(set(body.ids)) or set(body.ids) != set(existing_ids):
                raise HTTPException(400, "Порядок должен содержать все позиции ровно один раз")
            products = {row["id"]: row["product"] for row in rows}

            def groups(ids):
                result = []
                for item_id in ids:
                    product = products[item_id]
                    if not result or result[-1] != product:
                        result.append(product)
                return result

            if groups(body.ids) != groups(existing_ids):
                raise HTTPException(400, "Перемещать позиции можно только внутри своей линейки")
            self.conn.executemany(
                "UPDATE items SET sort_order=? WHERE id=?",
                ((index, item_id) for index, item_id in enumerate(body.ids)),
            )
        return {"ok": True}

    def create_item(self, body) -> dict:
        """Новая партия. В журнал пишется НОВАЯ ПАРТИЯ."""
        with self.undo.undoable("Добавление позиции"):
            if not self.conn.one(
                "SELECT 1 FROM product_colors WHERE name=? COLLATE NOCASE", (body.color,)):
                raise HTTPException(400, "Выберите цвет из справочника")
            if body.product and self.conn.one(
                "SELECT 1 FROM lines WHERE name=?", (body.product,)) and not self.conn.one(
                "SELECT 1 FROM line_product_colors WHERE line_name=? AND color_name=? COLLATE NOCASE",
                (body.product, body.color),
            ):
                raise HTTPException(400, "Этот цвет не разрешён для выбранной линейки")
            last_in_group = self.conn.scalar(
                "SELECT MAX(sort_order) FROM items WHERE product=?", (body.product,))
            if last_in_group is None:
                insert_order = self.conn.scalar(
                    "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM items")
            else:
                insert_order = last_in_group + 1
                self.conn.execute(
                    "UPDATE items SET sort_order=sort_order+1 WHERE sort_order>=?", (insert_order,))
            try:
                cur = self.conn.execute(
                    "INSERT INTO items (product, color, batch, date, qty, sort_order) VALUES (?,?,?,?,0,?)",
                    (body.product, body.color, body.batch, body.date or None, insert_order),
                )
            except sqlite3.IntegrityError:
                raise HTTPException(409, "Такая позиция (товар/цвет/партия) уже есть")
            self.apply_change(self.get_item(cur.lastrowid), body.qty, config.T_NEW)
            return dict(self.get_item(cur.lastrowid))

    def update_item(self, item_id: int, body) -> dict:
        """Изменения реквизитов сохраняются в базе; в журнал попадают только изменения количества."""
        data = dump(body)
        with self.undo.undoable("Изменение позиции"):
            item = self.get_item(item_id)
            if "product" in data or "color" in data:
                product = data.get("product", item["product"])
                color = data.get("color", item["color"])
                if color is not None:
                    if not self.conn.one(
                        "SELECT 1 FROM product_colors WHERE name=? COLLATE NOCASE", (color,)):
                        raise HTTPException(400, "Выберите цвет из справочника")
                    if product and self.conn.one(
                        "SELECT 1 FROM lines WHERE name=?", (product,)) and not self.conn.one(
                        "SELECT 1 FROM line_product_colors "
                        "WHERE line_name=? AND color_name=? COLLATE NOCASE",
                        (product, color),
                    ):
                        raise HTTPException(400, "Этот цвет не разрешён для выбранной линейки")
            new = {}
            required_labels = {"color": "цвет", "batch": "партия"}
            for field in ("product", "color", "batch", "date"):
                if field not in data:
                    continue
                v = (data[field] or "").strip()
                if field in required_labels and not v:
                    raise HTTPException(
                        400,
                        f"Поле «{required_labels[field]}» не может быть пустым",
                    )
                if field == "date":
                    v = v or None
                if v != item[field]:
                    new[field] = v
            if new:
                try:
                    self.conn.execute(
                        f"UPDATE items SET {', '.join(k + '=?' for k in new)} WHERE id=?",
                        (*new.values(), item_id),
                    )
                except sqlite3.IntegrityError:
                    raise HTTPException(409, "Такая позиция (товар/цвет/партия) уже есть")
                if "product" in new:
                    self.place_item_in_line(item_id, new["product"])
                item = self.get_item(item_id)
            if data.get("qty") is not None and data["qty"] != item["qty"]:
                self.apply_change(item, data["qty"], config.T_FIX)
            return dict(self.get_item(item_id))

    def delete_item(self, item_id: int) -> dict:
        """Удаляет позицию (в журнал не пишется; отменяемо)."""
        with self.undo.undoable("Удаление позиции"):
            self.get_item(item_id)
            self.conn.execute("DELETE FROM items WHERE id=?", (item_id,))
        return {"ok": True}

    def quick_consume(self, item_id: int, amount: int) -> dict:
        """Кнопки быстрого списания: 1 / 6 / 9 / 12."""
        if amount not in config.QUICK_AMOUNTS:
            raise HTTPException(400, f"Допустимо: {config.QUICK_AMOUNTS}")
        with self.undo.undoable("Списание количества"):
            item = self.get_item(item_id)
            return self.apply_change(item, item["qty"] - amount, config.T_OUT)

    def consume(self, item_id: int, amount: int) -> dict:
        with self.undo.undoable("Списание количества"):
            item = self.get_item(item_id)
            return self.apply_change(item, item["qty"] - amount, config.T_OUT)

    def receive(self, item_id: int, amount: int) -> dict:
        with self.undo.undoable("Приход количества"):
            item = self.get_item(item_id)
            return self.apply_change(item, item["qty"] + amount, config.T_IN)
