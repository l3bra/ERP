"""Складской учёт: бэкенд (FastAPI + SQLite).

  items      -> остатки (вкладка «База»)
  logs       -> журнал операций и разделителей (вкладка «Журнал»)
  log_months -> месяцы журнала (создаются автоматически, не удаляются)
  /print     -> данные для печати на А4

Запуск:  uvicorn main:app --reload
"""
import asyncio
import gzip
import json
import logging
import os
import re
import sqlite3
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zlib
from contextlib import asynccontextmanager, contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, validator

DB_PATH = Path(__file__).parent / "warehouse.db"
FRONTEND_PATH = Path(__file__).resolve().parent.parent / "frontend" / "index.html"
MOYSKLAD_API = "https://api.moysklad.ru/api/remap/1.2/"
MOYSKLAD_MAPPINGS_PATH = Path(__file__).with_name("moysklad_mappings.json")
MOYSKLAD_MAPPINGS_LOCK = threading.RLock()

# Типы операций журнала
T_IN = "ПРИХОД"            # добавили количество к существующей партии
T_OUT = "РАСХОД"           # уход со склада
T_NEW = "НОВАЯ ПАРТИЯ"     # создана новая позиция
T_FIX = "КОРРЕКЦИЯ"        # количество исправлено вручную в базе
T_EDIT = "ПРАВКА"          # изменены товар/цвет/партия/дата
T_DEL = "УДАЛЕНИЕ"         # позиция удалена
T_MANAGER_ERROR = "ОШИБКА МЕНЕДЖЕРА"
LOG_TYPES = [T_IN, T_OUT, T_NEW, T_FIX, T_EDIT, T_DEL, T_MANAGER_ERROR]

QUICK_AMOUNTS = (1, 6, 9, 12)   # кнопки быстрого списания
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
PRODUCT_COLOR_SWATCHES = (
    ("#ff6384", 0.36), ("#ff9f40", 0.36), ("#ffcd56", 0.40),
    ("#4bc078", 0.34), ("#36a2eb", 0.34), ("#9966ff", 0.32),
    ("#ff69b4", 0.32), ("#00bcd4", 0.32), ("#8bc34a", 0.36),
    ("#a0a0a0", 0.34),
)
LOGGER = logging.getLogger(__name__)


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


def capture_undo_state(c) -> dict[str, dict[int, dict]]:
    return {
        table: {
            row["id"]: dict(row)
            for row in c.execute(f"SELECT * FROM {table} ORDER BY id")
        }
        for table in ("items", "logs", "log_note_groups", "log_note_group_entries")
    }


@contextmanager
def undoable(c, action: str):
    before = capture_undo_state(c)
    yield
    after = capture_undo_state(c)
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
        c.execute("DELETE FROM undo_history WHERE undone_at IS NOT NULL")
        c.execute(
            "INSERT INTO undo_history(created_at, action, before_state) VALUES (?, ?, ?)",
            (now(), action, json.dumps(changes, ensure_ascii=False)),
        )


def restore_undo_state(c, before_state: dict):
    columns_by_table = {
        "items": ("id", "product", "color", "batch", "date", "qty", "sort_order"),
        "logs": (
            "id", "ts", "kind", "item_id", "product", "color", "batch",
            "old_qty", "new_qty", "diff", "type", "note",
        ),
        "log_note_groups": ("id", "code", "url", "text"),
        "log_note_group_entries": ("id", "group_id", "log_id", "previous_note"),
    }
    if not isinstance(before_state, dict):
        raise HTTPException(500, "История отмены имеет неверный формат")
    for table in ("items", "logs", "log_note_groups", "log_note_group_entries"):
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
                     or set(entry["before"]) != set(columns_by_table[table])))
            for entry in entries
        ):
            raise HTTPException(500, "История отмены содержит некорректную запись")
        c.executemany(f"DELETE FROM {table} WHERE id=?", ((entry["id"],) for entry in entries))
        for entry in entries:
            row = entry.get("before")
            if row is None:
                continue
            columns = columns_by_table[table]
            c.execute(
                f"INSERT INTO {table} ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                tuple(row[column] for column in columns),
            )


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
            CREATE TABLE IF NOT EXISTS log_note_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT,
                url TEXT,
                text TEXT
            );
            CREATE TABLE IF NOT EXISTS log_note_group_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL,
                log_id INTEGER NOT NULL UNIQUE,
                previous_note TEXT
            );
            CREATE TABLE IF NOT EXISTS log_months (
                month TEXT PRIMARY KEY                  -- 'YYYY-MM'
            );
            CREATE TABLE IF NOT EXISTS day_dividers (
                day TEXT PRIMARY KEY,
                log_id INTEGER UNIQUE
            );
            CREATE TABLE IF NOT EXISTS lines (
                name TEXT PRIMARY KEY,
                color INTEGER NOT NULL DEFAULT 0,
                sort_order INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS product_colors (
                name TEXT PRIMARY KEY COLLATE NOCASE,
                palette_index INTEGER NOT NULL DEFAULT 0,
                rgb TEXT NOT NULL DEFAULT '#ff6384',
                opacity REAL NOT NULL DEFAULT 0.36,
                sort_order INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS line_product_colors (
                line_name TEXT NOT NULL,
                color_name TEXT NOT NULL COLLATE NOCASE,
                sort_order INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (line_name, color_name)
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
            CREATE TABLE IF NOT EXISTS moysklad_mappings (
                local_name TEXT PRIMARY KEY COLLATE NOCASE,
                assortment_href TEXT UNIQUE
            );
            CREATE TABLE IF NOT EXISTS undo_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                action TEXT NOT NULL,
                before_state TEXT NOT NULL,
                undone_at TEXT
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
        ensure_product_color_display(c)
        ensure_product_colors(c)
        ensure_daily_dividers(c)


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


def ensure_daily_dividers(c, through: Optional[date] = None) -> list[str]:
    """Creates one day divider for the requested date, without filling past gaps."""
    through = through or datetime.now().date()
    c.execute(
        "INSERT OR IGNORE INTO day_dividers(day, log_id) "
        "SELECT substr(ts, 1, 10), MIN(id) FROM logs "
        "WHERE kind='divider' AND (type='day' OR note LIKE '==== НОВЫЙ ДЕНЬ%') "
        "GROUP BY substr(ts, 1, 10)"
    )
    c.execute(
        "DELETE FROM day_dividers WHERE log_id IS NULL OR NOT EXISTS "
        "(SELECT 1 FROM logs WHERE logs.id=day_dividers.log_id)"
    )
    day_key = through.isoformat()
    cursor = c.execute(
        "INSERT OR IGNORE INTO day_dividers(day) VALUES (?)", (day_key,)
    )
    if cursor.rowcount == 0:
        return []
    label = f"==== НОВЫЙ ДЕНЬ — {through.strftime('%d.%m.%Y')} ===="
    log_cursor = c.execute(
        "INSERT INTO logs (ts, kind, type, note) VALUES (?, 'divider', 'day', ?)",
        (f"{day_key}T00:00:00", label),
    )
    c.execute(
        "UPDATE day_dividers SET log_id=? WHERE day=?",
        (log_cursor.lastrowid, day_key),
    )
    return [day_key]


async def daily_divider_scheduler():
    while True:
        current = datetime.now()
        next_day = datetime.combine(current.date() + timedelta(days=1), datetime.min.time())
        await asyncio.sleep(max(1, (next_day - current).total_seconds()))
        try:
            with db() as c:
                ensure_daily_dividers(c)
        except sqlite3.Error:
            LOGGER.exception("Не удалось автоматически добавить разделитель нового дня")


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(daily_divider_scheduler())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


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


def ensure_product_colors(c):
    if c.execute(
        "SELECT 1 FROM app_settings WHERE key='product_colors_initialized'"
    ).fetchone():
        return
    existing = c.execute(
        "SELECT name FROM product_colors ORDER BY sort_order, rowid"
    ).fetchall()
    known_colors = {row["name"].casefold() for row in existing}
    color_names = c.execute(
        "SELECT color AS name FROM items UNION SELECT color AS name FROM logs "
        "WHERE color IS NOT NULL ORDER BY name COLLATE NOCASE"
    ).fetchall()
    next_order = len(existing)
    for row in color_names:
        name = row["name"].strip()
        if not name or name.casefold() in known_colors:
            continue
        palette_index = next_order % len(PRODUCT_COLOR_SWATCHES)
        rgb, opacity = PRODUCT_COLOR_SWATCHES[palette_index]
        c.execute(
            "INSERT INTO product_colors(name, palette_index, rgb, opacity, sort_order) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, palette_index, rgb, opacity, next_order),
        )
        known_colors.add(name.casefold())
        next_order += 1

    mappings = c.execute(
        "SELECT DISTINCT product, color FROM items ORDER BY product, color COLLATE NOCASE"
    ).fetchall()
    for row in mappings:
        c.execute(
            "INSERT OR IGNORE INTO line_product_colors(line_name, color_name, sort_order) "
            "VALUES (?, ?, (SELECT COALESCE(MAX(sort_order), -1) + 1 "
            "FROM line_product_colors WHERE line_name=?))",
            (row["product"], row["color"], row["product"]),
        )
    c.execute(
        "INSERT INTO app_settings(key, value) VALUES ('product_colors_initialized', '1')"
    )


def ensure_product_color_display(c):
    columns = {row["name"] for row in c.execute("PRAGMA table_info(product_colors)")}
    rgb_added = "rgb" not in columns
    opacity_added = "opacity" not in columns
    if rgb_added:
        c.execute("ALTER TABLE product_colors ADD COLUMN rgb TEXT NOT NULL DEFAULT '#ff6384'")
    if opacity_added:
        c.execute("ALTER TABLE product_colors ADD COLUMN opacity REAL NOT NULL DEFAULT 0.36")
    if not rgb_added and not opacity_added:
        return

    for index, (rgb, opacity) in enumerate(PRODUCT_COLOR_SWATCHES):
        if rgb_added:
            c.execute("UPDATE product_colors SET rgb=? WHERE palette_index=?", (rgb, index))
        if opacity_added:
            c.execute(
                "UPDATE product_colors SET opacity=? WHERE palette_index=?", (opacity, index)
            )


def dump(model) -> dict:
    return model.model_dump(exclude_unset=True) if hasattr(model, "model_dump") \
        else model.dict(exclude_unset=True)


def setting(c, key: str) -> Optional[str]:
    row = c.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def save_setting(c, key: str, value: str):
    c.execute(
        "INSERT INTO app_settings(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def moysklad_token() -> str:
    with db() as c:
        token = setting(c, "moysklad_token")
    if not token:
        raise HTTPException(400, "Сначала укажите токен МойСклад во вкладке «МойСклад»")
    return token


def moysklad_url(path: str) -> str:
    url = urllib.parse.urljoin(MOYSKLAD_API, path)
    parsed = urllib.parse.urlsplit(url)
    base = urllib.parse.urlsplit(MOYSKLAD_API)
    if parsed.scheme != "https" or parsed.netloc != base.netloc or not parsed.path.startswith(base.path):
        raise HTTPException(502, "МойСклад вернул некорректную ссылку")
    return url


def moysklad_get(path: str, token: str) -> dict:
    request = urllib.request.Request(
        moysklad_url(path),
        method="GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json;charset=utf-8",
            "Accept-Encoding": "gzip",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response_body = response.read()
            if response.headers.get("Content-Encoding", "").lower() == "gzip":
                response_body = gzip.decompress(response_body)
            data = json.loads(response_body.decode("utf-8"))
    except urllib.error.HTTPError as error:
        status = 401 if error.code in (401, 403) else 415 if error.code == 415 else 502
        response_body = error.read(4096).decode("utf-8", "replace")
        try:
            error_data = json.loads(response_body)
        except json.JSONDecodeError:
            error_data = {}
        errors = error_data.get("errors") if isinstance(error_data, dict) else None
        upstream_message = "; ".join(
            item["error"] for item in errors
            if isinstance(item, dict) and isinstance(item.get("error"), str)
        ) if isinstance(errors, list) else ""
        if upstream_message:
            upstream_message = re.sub(r"[\x00-\x1f\x7f]+", " ", upstream_message).strip()[:500]
            if token:
                upstream_message = upstream_message.replace(token, "[скрыто]")
        if status == 401:
            message = "Проверьте API-токен МойСклад"
        elif status == 415:
            message = "МойСклад отклонил формат запроса (415); проверьте настройки API"
        else:
            message = f"МойСклад вернул ошибку HTTP {error.code}"
        if upstream_message:
            message += f": {upstream_message}"
        raise HTTPException(status, message) from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise HTTPException(502, "Не удалось связаться с API МойСклад") from error
    except (UnicodeDecodeError, json.JSONDecodeError, OSError, EOFError, zlib.error) as error:
        raise HTTPException(502, "МойСклад вернул некорректный ответ") from error
    if not isinstance(data, dict):
        raise HTTPException(502, "МойСклад вернул неожиданный формат данных")
    return data


def moysklad_get_all(path: str, token: str) -> list[dict]:
    rows = []
    next_path = path
    visited = set()
    while next_path:
        url = moysklad_url(next_path)
        if url in visited or len(visited) >= 100:
            raise HTTPException(502, "МойСклад вернул некорректную пагинацию")
        visited.add(url)
        response = moysklad_get(url, token)
        page = response.get("rows")
        if not isinstance(page, list):
            raise HTTPException(502, "МойСклад не вернул список записей")
        rows.extend(page)
        next_path = (response.get("meta") or {}).get("nextHref")
    return rows


def moysklad_stores(token: str) -> list[dict]:
    rows = moysklad_get_all("entity/store?limit=1000", token)
    stores = []
    for row in rows:
        meta = row.get("meta") or {}
        href = meta.get("href")
        if href and row.get("name"):
            stores.append({"href": href, "name": row["name"]})
    return stores


def moysklad_stock_items(token: str, store_href: str) -> list[dict]:
    query = urllib.parse.urlencode({
        "filter": f"store={store_href};stockMode=all",
        "limit": 1000,
    })
    rows = moysklad_get_all(f"report/stock/all?{query}", token)
    stock_by_href = {}
    for row in rows:
        assortment = row.get("assortment") or {}
        meta = assortment.get("meta") or {}
        href = meta.get("href") or (row.get("meta") or {}).get("href")
        name = row.get("name") or assortment.get("name")
        if not href or not name:
            continue
        raw_stock = row.get("stock")
        if raw_stock is None:
            raw_stock = row.get("quantity", 0)
        try:
            quantity = float(raw_stock or 0)
        except (TypeError, ValueError) as error:
            raise HTTPException(502, "МойСклад вернул некорректное количество товара") from error
        if quantity.is_integer():
            quantity = int(quantity)
        current = stock_by_href.get(href)
        if current:
            current["quantity"] += quantity
        else:
            stock_by_href[href] = {
                "href": href,
                "name": name,
                "article": row.get("article") or assortment.get("article") or "",
                "code": row.get("code") or assortment.get("code") or "",
                "quantity": quantity,
            }
    return sorted(stock_by_href.values(), key=lambda item: item["name"].casefold())


def local_stock_groups(c) -> list[sqlite3.Row]:
    return c.execute(
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
    ).fetchall()


def read_moysklad_mappings() -> list[dict]:
    with MOYSKLAD_MAPPINGS_LOCK:
        if not MOYSKLAD_MAPPINGS_PATH.exists():
            with db() as c:
                legacy_rows = c.execute(
                    "SELECT local_name, assortment_href FROM moysklad_mappings"
                ).fetchall()
            mappings = [
                {**dict(row), "mapping_id": str(uuid.uuid4())}
                for row in legacy_rows
            ]
            if mappings:
                write_moysklad_mappings(mappings)
            return mappings

        try:
            data = json.loads(MOYSKLAD_MAPPINGS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise HTTPException(500, "Не удалось прочитать файл сопоставлений МойСклад") from error
        if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("mappings"), list):
            raise HTTPException(500, "Файл сопоставлений МойСклад имеет неверный формат")

        mappings = []
        seen_names = set()
        seen_ids = set()
        needs_save = False
        for entry in data["mappings"]:
            if (
                not isinstance(entry, dict)
                or not isinstance(entry.get("local_name"), str)
                or not entry["local_name"].strip()
                or (entry.get("assortment_href") is not None
                    and not isinstance(entry["assortment_href"], str))
            ):
                raise HTTPException(500, "Файл сопоставлений МойСклад содержит некорректную запись")
            key = entry["local_name"].casefold()
            if key in seen_names:
                raise HTTPException(500, "В файле сопоставлений МойСклад повторяется название")
            seen_names.add(key)
            mapping_id = entry.get("mapping_id")
            try:
                parsed_id = uuid.UUID(mapping_id) if isinstance(mapping_id, str) else None
            except ValueError:
                parsed_id = None
            if parsed_id is None or str(parsed_id) != mapping_id or mapping_id in seen_ids:
                mapping_id = str(uuid.uuid4())
                needs_save = True
            seen_ids.add(mapping_id)
            mappings.append({
                "mapping_id": mapping_id,
                "local_name": entry["local_name"],
                "assortment_href": entry["assortment_href"],
            })
        if needs_save:
            write_moysklad_mappings(mappings)
        return mappings


def write_moysklad_mappings(mappings: list[dict]):
    with MOYSKLAD_MAPPINGS_LOCK:
        temporary_path = MOYSKLAD_MAPPINGS_PATH.with_name(
            MOYSKLAD_MAPPINGS_PATH.name + ".tmp"
        )
        try:
            MOYSKLAD_MAPPINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            with temporary_path.open("w", encoding="utf-8", newline="\n") as file:
                json.dump(
                    {"version": 1, "mappings": mappings},
                    file,
                    ensure_ascii=False,
                    indent=2,
                )
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_path, MOYSKLAD_MAPPINGS_PATH)
        except OSError as error:
            raise HTTPException(500, "Не удалось сохранить файл сопоставлений МойСклад") from error


def get_item(c, item_id: int) -> sqlite3.Row:
    row = c.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Позиция не найдена")
    return row


def log_event(c, item, old: int, new: int, type_: str, note: Optional[str] = None):
    ts = now()
    ensure_daily_dividers(c, date.fromisoformat(ts[:10]))
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

    @validator("color")
    def strip_color(cls, value: Optional[str]) -> Optional[str]:
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


class ProductColorIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    palette_index: int = Field(default=0, ge=0, le=9)
    rgb: str = "#ff6384"
    opacity: float = Field(default=0.36, ge=0, le=1)

    @validator("name")
    def strip_color_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Название цвета не может быть пустым")
        return value

    @validator("rgb")
    def validate_rgb(cls, value: str) -> str:
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
            raise ValueError("RGB должен быть в формате #RRGGBB")
        return value


class ProductColorUpdate(BaseModel):
    rgb: Optional[str] = None
    opacity: Optional[float] = Field(default=None, ge=0, le=1)

    @validator("rgb")
    def validate_rgb(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
            raise ValueError("RGB должен быть в формате #RRGGBB")
        return value


class MoyskladTokenIn(BaseModel):
    token: str = Field(min_length=1)

    @validator("token")
    def strip_token(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Укажите токен МойСклад")
        return value


class MoyskladStoreIn(BaseModel):
    href: str = Field(min_length=1)


class MoyskladMappingIn(BaseModel):
    local_name: str = Field(min_length=1)
    assortment_href: Optional[str] = None

    @validator("local_name")
    def strip_local_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Название из базы не может быть пустым")
        return value

    @validator("assortment_href")
    def strip_assortment_href(cls, value: Optional[str]) -> Optional[str]:
        value = value.strip() if value else None
        return value or None


class LineProductColors(BaseModel):
    colors: list[str]


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


class LogNoteGroupIn(BaseModel):
    ids: list[int] = Field(min_length=2)
    code: Optional[str] = Field(default=None, max_length=120)
    url: Optional[str] = Field(default=None, max_length=2000)
    text: Optional[str] = Field(default=None, max_length=1000)

    @validator("code", "url", "text")
    def strip_note_fields(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() or None if value is not None else None


class LogNoteGroupUpdate(BaseModel):
    code: Optional[str] = Field(default=None, max_length=120)
    url: Optional[str] = Field(default=None, max_length=2000)
    text: Optional[str] = Field(default=None, max_length=1000)

    @validator("code", "url", "text")
    def strip_note_fields(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() or None if value is not None else None


# ---------- Приложение ----------
app = FastAPI(title="Warehouse", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],     # локальная разработка
    allow_methods=["*"],
    allow_headers=["*"],
)
init_db()


@app.get("/", include_in_schema=False)
def frontend():
    if not FRONTEND_PATH.is_file():
        raise HTTPException(500, "Файл интерфейса frontend/index.html не найден")
    return FileResponse(FRONTEND_PATH, media_type="text/html")


@app.get("/meta")
def meta():
    return {"log_types": LOG_TYPES, "quick_amounts": list(QUICK_AMOUNTS)}


@app.post("/undo")
def undo_last_change():
    with db() as c:
        entry = c.execute(
            "SELECT id, action, before_state FROM undo_history "
            "WHERE undone_at IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not entry:
            return {"undone": False, "action": None}
        try:
            before_state = json.loads(entry["before_state"])
        except json.JSONDecodeError as error:
            raise HTTPException(500, "История отмены повреждена") from error
        restore_undo_state(c, before_state)
        c.execute(
            "UPDATE undo_history SET undone_at=? WHERE id=?",
            (now(), entry["id"]),
        )
    return {"undone": True, "action": entry["action"]}


@app.get("/moysklad/config")
def moysklad_config():
    with db() as c:
        return {
            "configured": bool(setting(c, "moysklad_token")),
            "store_href": setting(c, "moysklad_store_href"),
        }


@app.put("/moysklad/token")
def save_moysklad_token(body: MoyskladTokenIn):
    with db() as c:
        save_setting(c, "moysklad_token", body.token)
    return {"configured": True}


@app.delete("/moysklad/token")
def delete_moysklad_token():
    with db() as c:
        c.execute("DELETE FROM app_settings WHERE key='moysklad_token'")
        c.execute("DELETE FROM app_settings WHERE key='moysklad_store_href'")
    return {"configured": False}


@app.get("/moysklad/local-groups")
def moysklad_local_groups():
    with db() as c:
        rows = local_stock_groups(c)
    mappings = read_moysklad_mappings()
    return {
        "groups": [dict(row) for row in rows],
        "mappings": {row["local_name"].casefold(): row["assortment_href"] for row in mappings},
        "mapping_ids": {row["local_name"].casefold(): row["mapping_id"] for row in mappings},
    }


@app.get("/moysklad/stores")
def list_moysklad_stores():
    return moysklad_stores(moysklad_token())


@app.put("/moysklad/store")
def select_moysklad_store(body: MoyskladStoreIn):
    token = moysklad_token()
    if not any(store["href"] == body.href for store in moysklad_stores(token)):
        raise HTTPException(400, "Выберите склад из списка МойСклад")
    with db() as c:
        save_setting(c, "moysklad_store_href", body.href)
    return {"store_href": body.href}


@app.get("/moysklad/compare")
def compare_moysklad_stock():
    token = moysklad_token()
    with db() as c:
        store_href = setting(c, "moysklad_store_href")
        if not store_href:
            raise HTTPException(400, "Выберите склад МойСклад для сравнения")
        groups = local_stock_groups(c)
    mappings = read_moysklad_mappings()

    return {
        "groups": [dict(row) for row in groups],
        "mappings": {row["local_name"].casefold(): row["assortment_href"] for row in mappings},
        "mapping_ids": {row["local_name"].casefold(): row["mapping_id"] for row in mappings},
        "stock_items": moysklad_stock_items(token, store_href),
    }


@app.put("/moysklad/mappings")
def save_moysklad_mapping(body: MoyskladMappingIn):
    with db() as c:
        if not c.execute(
            "SELECT 1 FROM items WHERE color=? COLLATE NOCASE LIMIT 1",
            (body.local_name,),
        ).fetchone():
            raise HTTPException(404, "Название не найдено в базе")
    if body.assortment_href is not None:
        moysklad_url(body.assortment_href)
    mappings = read_moysklad_mappings()
    local_key = body.local_name.casefold()
    if body.assortment_href is not None and any(
        entry["local_name"].casefold() != local_key
        and entry["assortment_href"] == body.assortment_href
        for entry in mappings
    ):
        raise HTTPException(409, "Этот товар МойСклад уже сопоставлен с другим названием")
    updated = False
    for entry in mappings:
        if entry["local_name"].casefold() == local_key:
            entry["assortment_href"] = body.assortment_href
            mapping_id = entry["mapping_id"]
            updated = True
            break
    if not updated:
        mapping_id = str(uuid.uuid4())
        mappings.append({
            "mapping_id": mapping_id,
            "local_name": body.local_name,
            "assortment_href": body.assortment_href,
        })
    write_moysklad_mappings(mappings)
    return {
        "mapping_id": mapping_id,
        "local_name": body.local_name,
        "assortment_href": body.assortment_href,
    }


@app.get("/lines")
def list_lines():
    with db() as c:
        rows = c.execute(
            "SELECT name, color FROM lines ORDER BY sort_order, rowid"
        ).fetchall()
        assignments = c.execute(
            "SELECT line_name, color_name FROM line_product_colors "
            "ORDER BY line_name, sort_order, rowid"
        ).fetchall()
        colors_by_line = {}
        for assignment in assignments:
            colors_by_line.setdefault(assignment["line_name"], []).append(
                assignment["color_name"]
            )
        return [
            {**dict(row), "product_colors": colors_by_line.get(row["name"], [])}
            for row in rows
        ]


@app.get("/product-colors")
def list_product_colors():
    with db() as c:
        rows = c.execute(
            "SELECT name, palette_index, rgb, opacity FROM product_colors "
            "ORDER BY sort_order, name COLLATE NOCASE"
        ).fetchall()
        return [dict(row) for row in rows]


@app.post("/product-colors", status_code=201)
def create_product_color(body: ProductColorIn):
    with db() as c:
        try:
            order = c.execute(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM product_colors"
            ).fetchone()[0]
            c.execute(
                "INSERT INTO product_colors(name, palette_index, rgb, opacity, sort_order) "
                "VALUES (?, ?, ?, ?, ?)",
                (body.name, body.palette_index, body.rgb.lower(), body.opacity, order),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Такой цвет уже есть")
    return {"name": body.name, "palette_index": body.palette_index,
            "rgb": body.rgb.lower(), "opacity": body.opacity}


@app.delete("/product-colors/{name}")
def delete_product_color(name: str):
    with db() as c:
        color = c.execute(
            "SELECT name FROM product_colors WHERE name=? COLLATE NOCASE", (name,)
        ).fetchone()
        if not color:
            raise HTTPException(404, "Цвет не найден")
        c.execute(
            "DELETE FROM line_product_colors WHERE color_name=? COLLATE NOCASE",
            (color["name"],),
        )
        c.execute(
            "DELETE FROM product_colors WHERE name=? COLLATE NOCASE", (color["name"],)
        )
    return {"name": color["name"], "ok": True}


@app.put("/product-colors/{name}")
def update_product_color(name: str, body: ProductColorUpdate):
    changes = {key: value for key, value in dump(body).items() if value is not None}
    if not changes:
        raise HTTPException(400, "Не указаны изменения цвета")
    with db() as c:
        current = c.execute(
            "SELECT name, palette_index, rgb, opacity FROM product_colors "
            "WHERE name=? COLLATE NOCASE", (name,)
        ).fetchone()
        if not current:
            raise HTTPException(404, "Цвет не найден")
        values = {**dict(current), **changes}
        c.execute(
            "UPDATE product_colors SET rgb=?, opacity=? WHERE name=? COLLATE NOCASE",
            (values["rgb"].lower(), values["opacity"], name),
        )
    return {"name": current["name"], "rgb": values["rgb"].lower(),
            "opacity": values["opacity"]}


@app.put("/lines/{line_name}/product-colors")
def set_line_product_colors(line_name: str, body: LineProductColors):
    normalized_colors = [name.strip() for name in body.colors]
    if any(not name for name in normalized_colors):
        raise HTTPException(400, "Название цвета не может быть пустым")
    if len({name.casefold() for name in normalized_colors}) != len(normalized_colors):
        raise HTTPException(400, "Цвет указан несколько раз")
    with db() as c:
        if not c.execute("SELECT 1 FROM lines WHERE name=?", (line_name,)).fetchone():
            raise HTTPException(404, "Линейка не найдена")
        for name in normalized_colors:
            if not c.execute(
                "SELECT 1 FROM product_colors WHERE name=? COLLATE NOCASE", (name,)
            ).fetchone():
                raise HTTPException(400, f"Цвет «{name}» отсутствует в справочнике")
        c.execute("DELETE FROM line_product_colors WHERE line_name=?", (line_name,))
        c.executemany(
            "INSERT INTO line_product_colors(line_name, color_name, sort_order) VALUES (?, ?, ?)",
            ((line_name, name, index) for index, name in enumerate(normalized_colors)),
        )
    return {"line": line_name, "colors": normalized_colors}


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
        c.execute("DELETE FROM line_product_colors WHERE line_name=?", (name,))
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
    with db() as c, undoable(c, "Изменение порядка позиций"):
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
    with db() as c, undoable(c, "Добавление позиции"):
        if not c.execute(
            "SELECT 1 FROM product_colors WHERE name=? COLLATE NOCASE", (body.color,)
        ).fetchone():
            raise HTTPException(400, "Выберите цвет из справочника")
        if body.product and c.execute(
            "SELECT 1 FROM lines WHERE name=?", (body.product,)
        ).fetchone() and not c.execute(
            "SELECT 1 FROM line_product_colors WHERE line_name=? AND color_name=? COLLATE NOCASE",
            (body.product, body.color),
        ).fetchone():
            raise HTTPException(400, "Этот цвет не разрешён для выбранной линейки")
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
    """Изменения реквизитов сохраняются в базе; в журнал попадают только изменения количества."""
    data = dump(body)
    with db() as c, undoable(c, "Изменение позиции"):
        item = get_item(c, item_id)
        if "product" in data or "color" in data:
            product = data.get("product", item["product"])
            color = data.get("color", item["color"])
            if color is not None:
                if not c.execute(
                    "SELECT 1 FROM product_colors WHERE name=? COLLATE NOCASE", (color,)
                ).fetchone():
                    raise HTTPException(400, "Выберите цвет из справочника")
                if product and c.execute(
                    "SELECT 1 FROM lines WHERE name=?", (product,)
                ).fetchone() and not c.execute(
                    "SELECT 1 FROM line_product_colors "
                    "WHERE line_name=? AND color_name=? COLLATE NOCASE",
                    (product, color),
                ).fetchone():
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
                c.execute(
                    f"UPDATE items SET {', '.join(k + '=?' for k in new)} WHERE id=?",
                    (*new.values(), item_id),
                )
            except sqlite3.IntegrityError:
                raise HTTPException(409, "Такая позиция (товар/цвет/партия) уже есть")
            if "product" in new:
                place_item_in_line(c, item_id, new["product"])
            item = get_item(c, item_id)
        if data.get("qty") is not None and data["qty"] != item["qty"]:
            apply_change(c, item, data["qty"], T_FIX)
        return dict(get_item(c, item_id))


@app.delete("/items/{item_id}")
def delete_item(item_id: int):
    with db() as c, undoable(c, "Удаление позиции"):
        get_item(c, item_id)
        c.execute("DELETE FROM items WHERE id=?", (item_id,))
    return {"ok": True}


@app.post("/items/{item_id}/quick/{amount}")
def quick_consume(item_id: int, amount: int):
    """Кнопки быстрого списания: 1 / 6 / 9 / 12."""
    if amount not in QUICK_AMOUNTS:
        raise HTTPException(400, f"Допустимо: {QUICK_AMOUNTS}")
    with db() as c, undoable(c, "Списание количества"):
        item = get_item(c, item_id)
        return apply_change(c, item, item["qty"] - amount, T_OUT)


@app.post("/items/{item_id}/consume")
def manual_consume(item_id: int, body: Amount):
    with db() as c, undoable(c, "Списание количества"):
        item = get_item(c, item_id)
        return apply_change(c, item, item["qty"] - body.amount, T_OUT)


@app.post("/items/{item_id}/receive")
def receive(item_id: int, body: Amount):
    with db() as c, undoable(c, "Приход количества"):
        item = get_item(c, item_id)
        return apply_change(c, item, item["qty"] + body.amount, T_IN)


# ===== ЖУРНАЛ =====
@app.get("/logs/months")
def log_months():
    """Список месяцев журнала (текущий создаётся автоматически)."""
    with db() as c:
        ensure_months(c)
        ensure_daily_dividers(c)
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
        ensure_daily_dividers(c)
        rows = c.execute(
            "SELECT * FROM logs WHERE substr(ts,1,7)=? ORDER BY ts, id", (month,)
        ).fetchall()
        groups = c.execute(
            "SELECT e.log_id, g.id, g.code, g.url, g.text, "
            "(SELECT COUNT(*) FROM log_note_group_entries all_entries "
            "WHERE all_entries.group_id=g.id) AS member_count "
            "FROM log_note_group_entries e "
            "JOIN log_note_groups g ON g.id=e.group_id "
            "JOIN logs l ON l.id=e.log_id WHERE substr(l.ts,1,7)=?",
            (month,),
        ).fetchall()
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


@app.post("/logs/divider", status_code=201)
def add_divider(body: Divider):
    """Adds an idempotent day divider or an inventory divider."""
    with db() as c, undoable(c, "Добавление разделителя журнала"):
        ensure_months(c)
        if body.kind == "day":
            created = ensure_daily_dividers(c)
            day = datetime.now().date().isoformat()
            row = c.execute(
                "SELECT note FROM logs WHERE id=(SELECT log_id FROM day_dividers WHERE day=?)",
                (day,),
            ).fetchone()
            return {"label": row["note"], "created": bool(created)}
        label = f"==== ИНВЕНТАРИЗАЦИЯ — {datetime.now().strftime('%d.%m.%Y %H:%M:%S')} ===="
        c.execute(
            "INSERT INTO logs (ts, kind, type, note) VALUES (?, 'divider', ?, ?)",
            (now(), body.kind, label),
        )
    return {"label": label}


def validate_log_note_group_fields(data: dict):
    if data.get("url"):
        parsed_url = urllib.parse.urlparse(data["url"])
        if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
            raise HTTPException(400, "Ссылка должна начинаться с http:// или https://")
    if not any(data.get(field) for field in ("code", "url", "text")):
        raise HTTPException(400, "Укажите код, ссылку или текст примечания")


@app.post("/logs/note-groups", status_code=201)
def create_log_note_group(body: LogNoteGroupIn):
    if len(set(body.ids)) != len(body.ids):
        raise HTTPException(400, "Строки журнала выбраны несколько раз")
    data = dump(body)
    validate_log_note_group_fields(data)
    with db() as c, undoable(c, "Объединение примечаний журнала"):
        placeholders = ",".join("?" for _ in body.ids)
        rows = c.execute(
            f"SELECT id, kind, note FROM logs WHERE id IN ({placeholders})",
            body.ids,
        ).fetchall()
        if len(rows) != len(body.ids):
            raise HTTPException(404, "Одна или несколько строк журнала не найдены")
        if any(row["kind"] != "move" for row in rows):
            raise HTTPException(400, "Объединять можно только строки операций")

        previous_notes = {}
        old_group_ids = {
            row["group_id"] for row in c.execute(
                f"SELECT DISTINCT group_id FROM log_note_group_entries "
                f"WHERE log_id IN ({placeholders})",
                body.ids,
            ).fetchall()
        }
        old_entries = c.execute(
            f"SELECT log_id, previous_note FROM log_note_group_entries "
            f"WHERE log_id IN ({placeholders})",
            body.ids,
        ).fetchall()
        previous_notes.update({row["log_id"]: row["previous_note"] for row in old_entries})
        for row in rows:
            previous_notes.setdefault(row["id"], row["note"])

        c.execute(
            "INSERT INTO log_note_groups(code, url, text) VALUES (?, ?, ?)",
            (data.get("code"), data.get("url"), data.get("text")),
        )
        group_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        c.execute(
            f"DELETE FROM log_note_group_entries WHERE log_id IN ({placeholders})",
            body.ids,
        )
        c.executemany(
            "INSERT INTO log_note_group_entries(group_id, log_id, previous_note) "
            "VALUES (?, ?, ?)",
            ((group_id, log_id, previous_notes[log_id]) for log_id in body.ids),
        )
        for old_group_id in old_group_ids:
            remaining = c.execute(
                "SELECT log_id, previous_note FROM log_note_group_entries WHERE group_id=?",
                (old_group_id,),
            ).fetchall()
            if len(remaining) == 1:
                c.execute(
                    "UPDATE logs SET note=? WHERE id=?",
                    (remaining[0]["previous_note"], remaining[0]["log_id"]),
                )
                c.execute(
                    "DELETE FROM log_note_group_entries WHERE group_id=?", (old_group_id,)
                )
        c.execute(
            "DELETE FROM log_note_groups WHERE NOT EXISTS "
            "(SELECT 1 FROM log_note_group_entries WHERE group_id=log_note_groups.id)"
        )
    return {"id": group_id, "ids": body.ids, **{key: data.get(key) for key in ("code", "url", "text")}}


@app.put("/logs/note-groups/{group_id}")
def update_log_note_group(group_id: int, body: LogNoteGroupUpdate):
    data = dump(body)
    if not data:
        raise HTTPException(400, "Не указаны изменения примечания")
    with db() as c, undoable(c, "Изменение общего примечания журнала"):
        group = c.execute(
            "SELECT id, code, url, text FROM log_note_groups WHERE id=?", (group_id,)
        ).fetchone()
        if not group:
            raise HTTPException(404, "Общее примечание не найдено")
        fields = {**dict(group), **data}
        validate_log_note_group_fields(fields)
        c.execute(
            "UPDATE log_note_groups SET code=?, url=?, text=? WHERE id=?",
            (fields["code"], fields["url"], fields["text"], group_id),
        )
    return {"id": group_id, **{key: fields[key] for key in ("code", "url", "text")}}


@app.delete("/logs/note-groups/{group_id}")
def delete_log_note_group(group_id: int):
    with db() as c, undoable(c, "Разъединение примечания журнала"):
        group = c.execute(
            "SELECT id FROM log_note_groups WHERE id=?", (group_id,)
        ).fetchone()
        if not group:
            raise HTTPException(404, "Общее примечание не найдено")
        entries = c.execute(
            "SELECT log_id, previous_note FROM log_note_group_entries WHERE group_id=?",
            (group_id,),
        ).fetchall()
        c.executemany(
            "UPDATE logs SET note=? WHERE id=?",
            ((entry["previous_note"], entry["log_id"]) for entry in entries),
        )
        c.execute("DELETE FROM log_note_group_entries WHERE group_id=?", (group_id,))
        c.execute("DELETE FROM log_note_groups WHERE id=?", (group_id,))
    return {"ok": True}


@app.put("/logs/{log_id}")
def update_log(log_id: int, body: LogUpdate):
    """Правка строки журнала. Остатки в базе НЕ меняются — правится только запись."""
    data = dump(body)
    with db() as c, undoable(c, "Изменение записи журнала"):
        row = c.execute("SELECT * FROM logs WHERE id=?", (log_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Запись не найдена")
        if row["kind"] == "divider":
            allowed = {k: v for k, v in data.items() if k == "note" and v is not None}
        else:
            if "note" in data and c.execute(
                "SELECT 1 FROM log_note_group_entries WHERE log_id=?", (log_id,)
            ).fetchone():
                raise HTTPException(400, "Измените общее примечание всей группы")
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
    with db() as c, undoable(c, "Удаление записи журнала"):
        if not c.execute("SELECT 1 FROM logs WHERE id=?", (log_id,)).fetchone():
            raise HTTPException(404, "Запись не найдена")
        group = c.execute(
            "SELECT group_id FROM log_note_group_entries WHERE log_id=?", (log_id,)
        ).fetchone()
        c.execute("DELETE FROM log_note_group_entries WHERE log_id=?", (log_id,))
        if group:
            remaining = c.execute(
                "SELECT log_id, previous_note FROM log_note_group_entries WHERE group_id=?",
                (group["group_id"],),
            ).fetchall()
            if len(remaining) == 1:
                c.execute(
                    "UPDATE logs SET note=? WHERE id=?",
                    (remaining[0]["previous_note"], remaining[0]["log_id"]),
                )
                c.execute(
                    "DELETE FROM log_note_group_entries WHERE group_id=?",
                    (group["group_id"],),
                )
            if len(remaining) <= 1:
                c.execute(
                    "DELETE FROM log_note_groups WHERE id=?", (group["group_id"],)
                )
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
