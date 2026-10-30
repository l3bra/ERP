"""Складской учёт: бэкенд (FastAPI + SQLite).

  items      -> остатки (вкладка «База»)
  logs       -> журнал операций и разделителей (вкладка «Журнал»)
  log_months -> месяцы журнала (создаются автоматически, не удаляются)
  /print     -> данные для печати на А4

Запуск:  uvicorn main:app --reload
"""
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator

DB_PATH = Path(__file__).parent / "warehouse.db"

# Типы операций журнала
T_IN = "ПРИХОД"            # добавили количество к существующей партии
T_OUT = "РАСХОД"           # уход со склада
T_NEW = "НОВАЯ ПАРТИЯ"     # создана новая позиция
T_FIX = "КОРРЕКЦИЯ"        # количество исправлено вручную в базе
T_EDIT = "ПРАВКА"          # изменены товар/цвет/партия/дата
T_DEL = "УДАЛЕНИЕ"         # позиция удалена
LOG_TYPES = [T_IN, T_OUT, T_NEW, T_FIX, T_EDIT, T_DEL]

QUICK_AMOUNTS = (1, 6, 9, 12)   # кнопки быстрого списания
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


# ---------- БД ----------
@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with db() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS items (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                product TEXT NOT NULL,
                color   TEXT NOT NULL,
                batch   TEXT NOT NULL,
                date    TEXT,
                qty     INTEGER NOT NULL DEFAULT 0,
                sort_order INTEGER NOT NULL DEFAULT 0,
                UNIQUE(product, color, batch)
            );
            CREATE TABLE IF NOT EXISTS logs (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                ts      TEXT NOT NULL,
                kind    TEXT NOT NULL DEFAULT 'move',   -- move | divider
                item_id INTEGER,
                product TEXT, color TEXT, batch TEXT,
                old_qty INTEGER, new_qty INTEGER, diff INTEGER,
                type    TEXT,                           -- тип операции / day / inventory
                note    TEXT
            );
            CREATE TABLE IF NOT EXISTS log_months (
                month TEXT PRIMARY KEY                  -- 'YYYY-MM'
            );
            CREATE TABLE IF NOT EXISTS lines (
                name TEXT PRIMARY KEY,
                color INTEGER NOT NULL DEFAULT 0,
                sort_order INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS table_styles (
                table_name TEXT NOT NULL,
                target_type TEXT NOT NULL,
                row_key TEXT NOT NULL,
                column_key TEXT NOT NULL,
                color INTEGER NOT NULL,
                PRIMARY KEY (table_name, target_type, row_key, column_key)
            );
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        item_columns = {row["name"] for row in c.execute("PRAGMA table_info(items)")}
        if "sort_order" not in item_columns:
            c.execute("ALTER TABLE items ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")
        line_columns = {row["name"] for row in c.execute("PRAGMA table_info(lines)")}
        if "sort_order" not in line_columns:
            c.execute("ALTER TABLE lines ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")
        ensure_months(c)
        ensure_lines(c)
        ensure_item_order(c)


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def ensure_months(c):
    """Создаёт вкладки месяцев от первого месяца в журнале до текущего.
    Ничего не удаляет. Вызывается при старте и при каждом обращении к журналу,
    поэтому новый месяц появляется сам при первом же заходе."""
    cur = datetime.now().strftime("%Y-%m")
    first = c.execute(
        "SELECT MIN(m) FROM (SELECT month AS m FROM log_months "
        "UNION SELECT substr(ts,1,7) FROM logs)"
    ).fetchone()[0] or cur
    if first > cur:
        first = cur
    y, m = map(int, first.split("-"))
    ey, em = map(int, cur.split("-"))
    while (y, m) <= (ey, em):
        c.execute("INSERT OR IGNORE INTO log_months(month) VALUES (?)", (f"{y:04d}-{m:02d}",))
        m += 1
        if m == 13:
            y, m = y + 1, 1


def ensure_lines(c):
    examples = (
        ("Standart", 0), ("Simple", 1), ("HT", 2), ("Castable", 3),
        ("Durable", 4), ("Silicone", 5), ("Force", 6), ("Flex", 7),
        ("Art", 8), ("Crown", 9), ("Dental", 0), ("Reactive", 1), ("ACF", 2),
    )
    seeded = c.execute(
        "SELECT 1 FROM app_settings WHERE key='sample_lines_seeded'"
    ).fetchone()
    if not seeded:
        c.executemany(
            "INSERT OR IGNORE INTO lines(name, color, sort_order) VALUES (?, ?, ?)",
            ((name, color, index) for index, (name, color) in enumerate(examples)),
        )
        c.execute(
            "INSERT INTO app_settings(key, value) VALUES ('sample_lines_seeded', '1')"
        )
    if not c.execute(
        "SELECT 1 FROM app_settings WHERE key='line_order_initialized'"
    ).fetchone():
        rows = c.execute("SELECT name FROM lines ORDER BY rowid").fetchall()
        for index, row in enumerate(rows):
            c.execute("UPDATE lines SET sort_order=? WHERE name=?", (index, row["name"]))
        c.execute(
            "INSERT INTO app_settings(key, value) VALUES ('line_order_initialized', '1')"
        )


def ensure_item_order(c):
    if c.execute(
        "SELECT 1 FROM app_settings WHERE key='item_order_initialized'"
    ).fetchone():
        return
    lines = c.execute("SELECT name, sort_order FROM lines ORDER BY sort_order, rowid").fetchall()
    line_order = {row["name"]: index for index, row in enumerate(lines)}
    products = c.execute(
        "SELECT product, MIN(id) AS first_id FROM items GROUP BY product ORDER BY first_id"
    ).fetchall()
    for row in products:
        line_order.setdefault(row["product"], len(line_order))
    rows = c.execute("SELECT id, product FROM items").fetchall()
    rows.sort(key=lambda row: (line_order[row["product"]], row["id"]))
    c.executemany(
        "UPDATE items SET sort_order=? WHERE id=?",
        ((index, row["id"]) for index, row in enumerate(rows)),
    )
    c.execute(
        "INSERT INTO app_settings(key, value) VALUES ('item_order_initialized', '1')"
    )


def dump(model) -> dict:
    return model.model_dump(exclude_unset=True) if hasattr(model, "model_dump") \
        else model.dict(exclude_unset=True)


def get_item(c, item_id: int) -> sqlite3.Row:
    row = c.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Позиция не найдена")
    return row


def log_event(c, item, old: int, new: int, type_: str, note: Optional[str] = None):
    ts = now()
    previous = c.execute("SELECT ts FROM logs ORDER BY ts DESC, id DESC LIMIT 1").fetchone()
    if previous and previous["ts"][:10] != ts[:10]:
        label = f"==== НОВЫЙ ДЕНЬ — {datetime.now().strftime('%d.%m.%Y %H:%M:%S')} ===="
        c.execute(
            "INSERT INTO logs (ts, kind, type, note) VALUES (?, 'divider', 'day', ?)",
            (ts, label),
        )
    c.execute(
        """INSERT INTO logs (ts, kind, item_id, product, color, batch,
                             old_qty, new_qty, diff, type, note)
           VALUES (?, 'move', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (ts, item["id"], item["product"], item["color"], item["batch"],
         old, new, new - old, type_, note),
    )


def apply_change(c, item, new_qty: int, type_: str, note: Optional[str] = None) -> dict:
    """Единая точка изменения остатка: обновляет qty и пишет строку в журнал."""
    old_qty = item["qty"]
    new_qty = max(0, new_qty)
    c.execute("UPDATE items SET qty=? WHERE id=?", (new_qty, item["id"]))
    log_event(c, item, old_qty, new_qty, type_, note)
    return {"id": item["id"], "old_qty": old_qty, "new_qty": new_qty,
            "diff": new_qty - old_qty, "type": type_}


def place_item_in_line(c, item_id: int, product: str):
    rows = c.execute(
        "SELECT id, product FROM items WHERE id != ? ORDER BY sort_order, id",
        (item_id,),
    ).fetchall()
    ordered = [row["id"] for row in rows]
    insert_at = max(
        (index + 1 for index, row in enumerate(rows) if row["product"] == product),
        default=len(ordered),
    )
    ordered.insert(insert_at, item_id)
    c.executemany(
        "UPDATE items SET sort_order=? WHERE id=?",
        ((index, current_id) for index, current_id in enumerate(ordered)),
    )


# ---------- Модели ----------
class ItemIn(BaseModel):
    product: str = ""
    color: str = Field(min_length=1)
    batch: str = Field(min_length=1)
    date: Optional[str] = None          # YYYY-MM-DD
    qty: int = Field(default=0, ge=0)

    @validator("product", pre=True, always=True)
    def strip_product(cls, value: Optional[str]) -> str:
        if value is None:
            return ""
        return value.strip() if isinstance(value, str) else value

    @validator("color", "batch")
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Поле не может быть пустым или состоять из пробелов")
        return value

class ItemUpdate(BaseModel):
    product: Optional[str] = None
    color: Optional[str] = None
    batch: Optional[str] = None
    date: Optional[str] = None          # пустая строка = очистить
    qty: Optional[int] = Field(default=None, ge=0)

    @validator("product")
    def strip_product(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value is not None else value


class LineIn(BaseModel):
    name: str = Field(min_length=1)
    color: int = Field(ge=0, le=9)

    @validator("name")
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Название линейки не может быть пустым")
        return value


class ItemOrder(BaseModel):
    ids: list[int] = Field(min_length=1)


class StyleTarget(BaseModel):
    table: Literal["items", "logs", "print"]
    kind: Literal["row", "column", "cell"]
    row: str = "*"
    column: str = "*"


class TableStyle(StyleTarget):
    color: int = Field(ge=0, le=9)


class Amount(BaseModel):
    amount: int = Field(gt=0)


class Divider(BaseModel):
    kind: Literal["day", "inventory"]


class LogUpdate(BaseModel):
    product: Optional[str] = None
    color: Optional[str] = None
    batch: Optional[str] = None
    old_qty: Optional[int] = None
    new_qty: Optional[int] = None
    type: Optional[str] = None
    note: Optional[str] = None

    @validator("product")
    def strip_product(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value is not None else value


# ---------- Приложение ----------
app = FastAPI(title="Warehouse")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],     # локальная разработка
    allow_methods=["*"],
    allow_headers=["*"],
)
init_db()


@app.get("/meta")
def meta():
    return {"log_types": LOG_TYPES, "quick_amounts": list(QUICK_AMOUNTS)}


@app.get("/lines")
def list_lines():
    with db() as c:
        rows = c.execute(
            "SELECT name, color FROM lines ORDER BY sort_order, rowid"
        ).fetchall()
        return [dict(row) for row in rows]


@app.post("/lines", status_code=201)
def create_line(body: LineIn):
    with db() as c:
        try:
            c.execute("INSERT INTO lines(name, color) VALUES (?, ?)", (body.name, body.color))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Такая линейка уже есть")
        return {"name": body.name, "color": body.color}


@app.put("/lines")
def update_line(body: LineIn):
    with db() as c:
        cur = c.execute("UPDATE lines SET color=? WHERE name=?", (body.color, body.name))
        if cur.rowcount == 0:
            raise HTTPException(404, "Линейка не найдена")
        return {"name": body.name, "color": body.color}


@app.delete("/lines/{name}")
def delete_line(name: str):
    with db() as c:
        if not c.execute("SELECT 1 FROM lines WHERE name=?", (name,)).fetchone():
            raise HTTPException(404, "Линейка не найдена")
        c.execute("DELETE FROM lines WHERE name=?", (name,))
    return {"ok": True}


@app.get("/styles")
def list_styles():
    with db() as c:
        rows = c.execute(
            "SELECT table_name, target_type, row_key, column_key, color FROM table_styles"
        ).fetchall()
        return [
            {"table": row["table_name"], "kind": row["target_type"],
             "row": row["row_key"], "column": row["column_key"], "color": row["color"]}
            for row in rows
        ]


@app.put("/styles")
def save_style(body: TableStyle):
    with db() as c:
        c.execute(
            "INSERT INTO table_styles(table_name, target_type, row_key, column_key, color) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(table_name, target_type, row_key, column_key) "
            "DO UPDATE SET color=excluded.color",
            (body.table, body.kind, body.row, body.column, body.color),
        )
    return {
        "table": body.table, "kind": body.kind, "row": body.row,
        "column": body.column, "color": body.color,
    }


@app.delete("/styles")
def delete_style(body: StyleTarget):
    with db() as c:
        c.execute(
            "DELETE FROM table_styles WHERE table_name=? AND target_type=? "
            "AND row_key=? AND column_key=?",
            (body.table, body.kind, body.row, body.column),
        )
    return {"ok": True}


# ===== БАЗА =====
@app.get("/items")
def list_items():
    with db() as c:
        rows = c.execute("SELECT * FROM items ORDER BY sort_order, id").fetchall()
        return [dict(r) for r in rows]


@app.put("/items/order")
def reorder_items(body: ItemOrder):
    with db() as c:
        rows = c.execute("SELECT id, product FROM items ORDER BY sort_order, id").fetchall()
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
        c.executemany(
            "UPDATE items SET sort_order=? WHERE id=?",
            ((index, item_id) for index, item_id in enumerate(body.ids)),
        )
    return {"ok": True}


@app.post("/items", status_code=201)
def create_item(body: ItemIn):
    """Новая партия. В журнал пишется НОВАЯ ПАРТИЯ."""
    with db() as c:
        last_in_group = c.execute(
            "SELECT MAX(sort_order) FROM items WHERE product=?", (body.product,)
        ).fetchone()[0]
        if last_in_group is None:
            insert_order = c.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM items").fetchone()[0]
        else:
            insert_order = last_in_group + 1
            c.execute("UPDATE items SET sort_order=sort_order+1 WHERE sort_order>=?", (insert_order,))
        try:
            cur = c.execute(
                "INSERT INTO items (product, color, batch, date, qty, sort_order) VALUES (?,?,?,?,0,?)",
                (body.product, body.color, body.batch, body.date or None, insert_order),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Такая позиция (товар/цвет/партия) уже есть")
        apply_change(c, get_item(c, cur.lastrowid), body.qty, T_NEW)
        return dict(get_item(c, cur.lastrowid))


@app.put("/items/{item_id}")
def update_item(item_id: int, body: ItemUpdate):
    """Любая правка позиции. Количество -> КОРРЕКЦИЯ, остальные поля -> ПРАВКА."""
    data = dump(body)
    with db() as c:
        item = get_item(c, item_id)
        new, changes = {}, []
        for field, label in (("product", "товар"), ("color", "цвет"),
                             ("batch", "партия"), ("date", "дата")):
            if field not in data:
                continue
            v = (data[field] or "").strip()
            if field not in ("date", "product") and not v:
                raise HTTPException(400, f"Поле «{label}» не может быть пустым")
            if field == "date":
                v = v or None
            if v != item[field]:
                new[field] = v
                changes.append(f"{label}: {item[field] or '—'} → {v or '—'}")
        if new:
            try:
                c.execute(
                    f"UPDATE items SET {', '.join(k + '=?' for k in new)} WHERE id=?",
                    (*new.values(), item_id),
                )
            except sqlite3.IntegrityError:
                raise HTTPException(409, "Такая позиция (товар/цвет/партия) уже есть")
            if "product" in new:
                place_item_in_line(c, item_id, new["product"])
            item = get_item(c, item_id)
            log_event(c, item, item["qty"], item["qty"], T_EDIT, "; ".join(changes))
        if data.get("qty") is not None and data["qty"] != item["qty"]:
            apply_change(c, item, data["qty"], T_FIX)
        return dict(get_item(c, item_id))


@app.delete("/items/{item_id}")
def delete_item(item_id: int):
    with db() as c:
        item = get_item(c, item_id)
        log_event(c, item, item["qty"], 0, T_DEL)
        c.execute("DELETE FROM items WHERE id=?", (item_id,))
    return {"ok": True}


@app.post("/items/{item_id}/quick/{amount}")
def quick_consume(item_id: int, amount: int):
    """Кнопки быстрого списания: 1 / 6 / 9 / 12."""
    if amount not in QUICK_AMOUNTS:
        raise HTTPException(400, f"Допустимо: {QUICK_AMOUNTS}")
    with db() as c:
        item = get_item(c, item_id)
        return apply_change(c, item, item["qty"] - amount, T_OUT)


@app.post("/items/{item_id}/consume")
def manual_consume(item_id: int, body: Amount):
    with db() as c:
        item = get_item(c, item_id)
        return apply_change(c, item, item["qty"] - body.amount, T_OUT)


@app.post("/items/{item_id}/receive")
def receive(item_id: int, body: Amount):
    with db() as c:
        item = get_item(c, item_id)
        return apply_change(c, item, item["qty"] + body.amount, T_IN)


# ===== ЖУРНАЛ =====
@app.get("/logs/months")
def log_months():
    """Список месяцев журнала (текущий создаётся автоматически)."""
    with db() as c:
        ensure_months(c)
        rows = c.execute(
            "SELECT month FROM log_months UNION SELECT DISTINCT substr(ts,1,7) FROM logs ORDER BY 1"
        ).fetchall()
        return [r[0] for r in rows]


@app.get("/logs")
def get_logs(month: Optional[str] = None):
    """Записи журнала за месяц (по умолчанию текущий), от старых к новым."""
    month = month or datetime.now().strftime("%Y-%m")
    if not MONTH_RE.match(month):
        raise HTTPException(400, "Месяц в формате ГГГГ-ММ")
    with db() as c:
        ensure_months(c)
        rows = c.execute(
            "SELECT * FROM logs WHERE substr(ts,1,7)=? ORDER BY ts, id", (month,)
        ).fetchall()
        return [dict(r) for r in rows]


@app.post("/logs/divider", status_code=201)
def add_divider(body: Divider):
    """Полоса «новый день» / «инвентаризация» с датой и временем вызова."""
    title = "НОВЫЙ ДЕНЬ" if body.kind == "day" else "ИНВЕНТАРИЗАЦИЯ"
    label = f"==== {title} — {datetime.now().strftime('%d.%m.%Y %H:%M:%S')} ===="
    with db() as c:
        ensure_months(c)
        c.execute(
            "INSERT INTO logs (ts, kind, type, note) VALUES (?, 'divider', ?, ?)",
            (now(), body.kind, label),
        )
    return {"label": label}


@app.put("/logs/{log_id}")
def update_log(log_id: int, body: LogUpdate):
    """Правка строки журнала. Остатки в базе НЕ меняются — правится только запись."""
    data = dump(body)
    with db() as c:
        row = c.execute("SELECT * FROM logs WHERE id=?", (log_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Запись не найдена")
        if row["kind"] == "divider":
            allowed = {k: v for k, v in data.items() if k == "note" and v is not None}
        else:
            allowed = {k: v for k, v in data.items()
                       if k in ("product", "color", "batch", "old_qty", "new_qty", "type", "note")
                       and (v is not None or k == "note")}
            if "old_qty" in allowed or "new_qty" in allowed:
                old = allowed.get("old_qty", row["old_qty"]) or 0
                new = allowed.get("new_qty", row["new_qty"]) or 0
                allowed["diff"] = new - old
        if allowed:
            c.execute(
                f"UPDATE logs SET {', '.join(k + '=?' for k in allowed)} WHERE id=?",
                (*allowed.values(), log_id),
            )
        return dict(c.execute("SELECT * FROM logs WHERE id=?", (log_id,)).fetchone())


@app.delete("/logs/{log_id}")
def delete_log(log_id: int):
    """Удаляет одну запись журнала. Вкладки месяцев не удаляются никогда."""
    with db() as c:
        if not c.execute("SELECT 1 FROM logs WHERE id=?", (log_id,)).fetchone():
            raise HTTPException(404, "Запись не найдена")
        c.execute("DELETE FROM logs WHERE id=?", (log_id,))
    return {"ok": True}


# ===== ПЕЧАТЬ =====
@app.get("/print")
def print_layout():
    """Раскладка в две колонки для А4, сохраняющая порядок базы."""
    with db() as c:
        rows = c.execute("SELECT * FROM items ORDER BY sort_order, id").fetchall()
    groups: dict = {}
    for r in rows:
        groups.setdefault(r["product"], []).append(
            {"color": r["color"], "batch": r["batch"], "date": r["date"], "qty": r["qty"]}
        )
    left, right = [], []
    lh = rh = 0
    for product, g in groups.items():
        h = len(g) + 1
        if lh <= rh:
            left.append({"product": product, "rows": g}); lh += h
        else:
            right.append({"product": product, "rows": g}); rh += h
    return {"left": left, "right": right, "generated": now()}


# ===== Демо-данные для проверки =====
@app.post("/demo")
def demo():
    sample = [
        ("Футболка", "Белый", "П-001", "2026-10-01", 40),
        ("Футболка", "Белый", "П-002", "2026-10-15", 25),
        ("Футболка", "Чёрный", "П-001", "2026-10-01", 30),
        ("Худи", "Серый", "П-010", "2026-10-10", 18),
        ("Худи", "Чёрный", "П-010", "2026-10-10", 22),
        ("Кепка", "Синий", "П-020", "2026-10-20", 60),
    ]
    added = 0
    for product, color, batch, d, qty in sample:
        try:
            create_item(ItemIn(product=product, color=color, batch=batch, date=d, qty=qty))
            added += 1
        except HTTPException:
            pass
    return {"added": added}
