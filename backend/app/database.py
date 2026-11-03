"""Доступ к SQLite: подключения, схема, инициализация и настройки."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from . import config

SCHEMA = """
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


class Connection:
    """Тонкая обёртка над sqlite3.Connection: Row-фабрика и типовые запросы."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._conn.row_factory = sqlite3.Row

    def execute(self, sql: str, params=()):
        return self._conn.execute(sql, params)

    def executemany(self, sql: str, params) -> None:
        self._conn.executemany(sql, params)

    def executescript(self, script: str) -> None:
        self._conn.executescript(script)

    def one(self, sql: str, params=()) -> Optional[sqlite3.Row]:
        return self.execute(sql, params).fetchone()

    def all(self, sql: str, params=()) -> list[sqlite3.Row]:
        return self.execute(sql, params).fetchall()

    def scalar(self, sql: str, params=()):
        """Единственное значение первой строки (для агрегатных запросов)."""
        return self.execute(sql, params).fetchone()[0]


class SettingsRepository:
    """Настройки приложения (таблица app_settings, ключ-значение)."""

    def __init__(self, conn: Connection):
        self.conn = conn

    def get(self, key: str) -> Optional[str]:
        row = self.conn.one("SELECT value FROM app_settings WHERE key=?", (key,))
        return row["value"] if row else None

    def save(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO app_settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def delete(self, key: str) -> None:
        self.conn.execute("DELETE FROM app_settings WHERE key=?", (key,))


class Database:
    """Владеет путём к БД, инициализирует схему и выдаёт подключения."""

    def __init__(self, path: Path = config.DB_PATH):
        self.path = path

    @contextmanager
    def connection(self) -> Iterator[Connection]:
        # check_same_thread=False: FastAPI выполняет dependency-генератор и сам
        # эндпоинт в разных потоках threadpool. Соединение при этом одно на запрос
        # и используется строго последовательно (enter -> эндпоинт -> exit),
        # поэтому одновременного доступа из двух потоков не бывает.
        conn = sqlite3.connect(self.path, check_same_thread=False)
        try:
            yield Connection(conn)
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        """Создаёт схему и наполняет служебные таблицы.

        Все изменения совместимы с существующей локальной базой:
        CREATE TABLE IF NOT EXISTS + аддитивные ALTER.
        """
        with self.connection() as c:
            c.executescript(SCHEMA)
            item_columns = {row["name"] for row in c.execute("PRAGMA table_info(items)")}
            if "sort_order" not in item_columns:
                c.execute("ALTER TABLE items ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")
            line_columns = {row["name"] for row in c.execute("PRAGMA table_info(lines)")}
            if "sort_order" not in line_columns:
                c.execute("ALTER TABLE lines ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")
            self._ensure_lines(c)
            self._ensure_item_order(c)
            self._ensure_product_color_display(c)
            self._ensure_product_colors(c)

    def _ensure_lines(self, c: Connection) -> None:
        settings = SettingsRepository(c)
        examples = (
            ("Standart", 0), ("Simple", 1), ("HT", 2), ("Castable", 3),
            ("Durable", 4), ("Silicone", 5), ("Force", 6), ("Flex", 7),
            ("Art", 8), ("Crown", 9), ("Dental", 0), ("Reactive", 1), ("ACF", 2),
        )
        if not settings.get("sample_lines_seeded"):
            c.executemany(
                "INSERT OR IGNORE INTO lines(name, color, sort_order) VALUES (?, ?, ?)",
                ((name, color, index) for index, (name, color) in enumerate(examples)),
            )
            settings.save("sample_lines_seeded", "1")
        if not settings.get("line_order_initialized"):
            rows = c.all("SELECT name FROM lines ORDER BY rowid")
            for index, row in enumerate(rows):
                c.execute("UPDATE lines SET sort_order=? WHERE name=?", (index, row["name"]))
            settings.save("line_order_initialized", "1")

    def _ensure_item_order(self, c: Connection) -> None:
        settings = SettingsRepository(c)
        if settings.get("item_order_initialized"):
            return
        lines = c.all("SELECT name, sort_order FROM lines ORDER BY sort_order, rowid")
        line_order = {row["name"]: index for index, row in enumerate(lines)}
        products = c.all(
            "SELECT product, MIN(id) AS first_id FROM items GROUP BY product ORDER BY first_id")
        for row in products:
            line_order.setdefault(row["product"], len(line_order))
        rows = c.all("SELECT id, product FROM items")
        rows.sort(key=lambda row: (line_order[row["product"]], row["id"]))
        c.executemany(
            "UPDATE items SET sort_order=? WHERE id=?",
            ((index, row["id"]) for index, row in enumerate(rows)),
        )
        settings.save("item_order_initialized", "1")

    def _ensure_product_colors(self, c: Connection) -> None:
        settings = SettingsRepository(c)
        if settings.get("product_colors_initialized"):
            return
        existing = c.all("SELECT name FROM product_colors ORDER BY sort_order, rowid")
        known_colors = {row["name"].casefold() for row in existing}
        color_names = c.all(
            "SELECT color AS name FROM items UNION SELECT color AS name FROM logs "
            "WHERE color IS NOT NULL ORDER BY name COLLATE NOCASE")
        next_order = len(existing)
        for row in color_names:
            name = row["name"].strip()
            if not name or name.casefold() in known_colors:
                continue
            palette_index = next_order % len(config.PRODUCT_COLOR_SWATCHES)
            rgb, opacity = config.PRODUCT_COLOR_SWATCHES[palette_index]
            c.execute(
                "INSERT INTO product_colors(name, palette_index, rgb, opacity, sort_order) "
                "VALUES (?, ?, ?, ?, ?)",
                (name, palette_index, rgb, opacity, next_order),
            )
            known_colors.add(name.casefold())
            next_order += 1

        mappings = c.all(
            "SELECT DISTINCT product, color FROM items ORDER BY product, color COLLATE NOCASE")
        for row in mappings:
            c.execute(
                "INSERT OR IGNORE INTO line_product_colors(line_name, color_name, sort_order) "
                "VALUES (?, ?, (SELECT COALESCE(MAX(sort_order), -1) + 1 "
                "FROM line_product_colors WHERE line_name=?))",
                (row["product"], row["color"], row["product"]),
            )
        settings.save("product_colors_initialized", "1")

    def _ensure_product_color_display(self, c: Connection) -> None:
        columns = {row["name"] for row in c.execute("PRAGMA table_info(product_colors)")}
        rgb_added = "rgb" not in columns
        opacity_added = "opacity" not in columns
        if rgb_added:
            c.execute("ALTER TABLE product_colors ADD COLUMN rgb TEXT NOT NULL DEFAULT '#ff6384'")
        if opacity_added:
            c.execute("ALTER TABLE product_colors ADD COLUMN opacity REAL NOT NULL DEFAULT 0.36")
        if not rgb_added and not opacity_added:
            return

        for index, (rgb, opacity) in enumerate(config.PRODUCT_COLOR_SWATCHES):
            if rgb_added:
                c.execute("UPDATE product_colors SET rgb=? WHERE palette_index=?", (rgb, index))
            if opacity_added:
                c.execute(
                    "UPDATE product_colors SET opacity=? WHERE palette_index=?", (opacity, index))
