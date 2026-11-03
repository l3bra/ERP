"""Пути и константы приложения."""

import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # backend/
PROJECT_DIR = BASE_DIR.parent                               # корень проекта

DB_PATH = BASE_DIR / "warehouse.db"
FRONTEND_PATH = PROJECT_DIR / "frontend" / "index.html"
FRONTEND_DIST_INDEX = PROJECT_DIR / "frontend" / "dist" / "index.html"
FRONTEND_DIST_ASSETS = PROJECT_DIR / "frontend" / "dist" / "assets"
FRONTEND_LEGACY_INDEX = PROJECT_DIR / "frontend" / "index-legacy.html"

MOYSKLAD_API = "https://api.moysklad.ru/api/remap/1.2/"
MOYSKLAD_MAPPINGS_PATH = BASE_DIR / "moysklad_mappings.json"

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
