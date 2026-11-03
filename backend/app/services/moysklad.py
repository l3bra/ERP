"""Интеграция с МойСклад: API-клиент, настройки и сопоставления товаров."""

import gzip
import json
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zlib
from pathlib import Path
from typing import Optional

from fastapi import HTTPException

from .. import config
from ..database import Connection, SettingsRepository
from .inventory import InventoryService


class MoyskladClient:
    """Клиент JSON API Remap 1.2. Только GET: изменения в МойСклад не выполняются."""

    def __init__(self, token: str, timeout: int = 30):
        self.token = token
        self.timeout = timeout

    @staticmethod
    def validate_url(path: str) -> str:
        """Проверяет, что ссылка ведёт на https-хост API МойСклад с тем же префиксом пути."""
        url = urllib.parse.urljoin(config.MOYSKLAD_API, path)
        parsed = urllib.parse.urlsplit(url)
        base = urllib.parse.urlsplit(config.MOYSKLAD_API)
        if parsed.scheme != "https" or parsed.netloc != base.netloc or not parsed.path.startswith(base.path):
            raise HTTPException(502, "МойСклад вернул некорректную ссылку")
        return url

    def get(self, path: str) -> dict:
        request = urllib.request.Request(
            self.validate_url(path),
            method="GET",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json;charset=utf-8",
                "Accept-Encoding": "gzip",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
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
                if self.token:
                    upstream_message = upstream_message.replace(self.token, "[скрыто]")
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

    def get_all(self, path: str) -> list[dict]:
        """Обходит пагинацию через meta.nextHref с защитой от циклов."""
        rows = []
        next_path = path
        visited = set()
        while next_path:
            url = self.validate_url(next_path)
            if url in visited or len(visited) >= 100:
                raise HTTPException(502, "МойСклад вернул некорректную пагинацию")
            visited.add(url)
            response = self.get(url)
            page = response.get("rows")
            if not isinstance(page, list):
                raise HTTPException(502, "МойСклад не вернул список записей")
            rows.extend(page)
            next_path = (response.get("meta") or {}).get("nextHref")
        return rows

    def stores(self) -> list[dict]:
        rows = self.get_all("entity/store?limit=1000")
        stores = []
        for row in rows:
            meta = row.get("meta") or {}
            href = meta.get("href")
            if href and row.get("name"):
                stores.append({"href": href, "name": row["name"]})
        return stores

    def stock_items(self, store_href: str) -> list[dict]:
        query = urllib.parse.urlencode({
            "filter": f"store={store_href};stockMode=all",
            "limit": 1000,
        })
        rows = self.get_all(f"report/stock/all?{query}")
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


class MoyskladMappingsStore:
    """Файловое хранилище сопоставлений (moysklad_mappings.json, version 1).

    Каждая запись имеет постоянный UUID (mapping_id). Запись атомарная.
    При первом чтении переносит сопоставления из старой таблицы moysklad_mappings.
    """

    def __init__(self, path: Path = config.MOYSKLAD_MAPPINGS_PATH):
        self.path = path
        self._lock = threading.RLock()

    def read(self, conn: Connection) -> list[dict]:
        with self._lock:
            if not self.path.exists():
                legacy_rows = conn.all(
                    "SELECT local_name, assortment_href FROM moysklad_mappings")
                mappings = [
                    {**dict(row), "mapping_id": str(uuid.uuid4())}
                    for row in legacy_rows
                ]
                if mappings:
                    self.write(mappings)
                return mappings

            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise HTTPException(500, "Не удалось прочитать файл сопоставлений МойСклад") from error
            if not isinstance(data, dict) or data.get("version") != 1 \
                    or not isinstance(data.get("mappings"), list):
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
                self.write(mappings)
            return mappings

    def write(self, mappings: list[dict]) -> None:
        with self._lock:
            temporary_path = self.path.with_name(self.path.name + ".tmp")
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
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
                os.replace(temporary_path, self.path)
            except OSError as error:
                raise HTTPException(500, "Не удалось сохранить файл сопоставлений МойСклад") from error


# Общий экземпляр хранилища: блокировка записи действует между запросами
DEFAULT_MAPPINGS_STORE = MoyskladMappingsStore()


class MoyskladService:
    """Оркестрация МойСклад: токен, склад, сравнение остатков, сопоставления."""

    def __init__(self, conn: Connection):
        self.conn = conn
        self.settings = SettingsRepository(conn)
        self.mappings = DEFAULT_MAPPINGS_STORE

    def _require_token(self) -> str:
        token = self.settings.get("moysklad_token")
        if not token:
            raise HTTPException(400, "Сначала укажите токен МойСклад во вкладке «МойСклад»")
        return token

    def config(self) -> dict:
        return {
            "configured": bool(self.settings.get("moysklad_token")),
            "store_href": self.settings.get("moysklad_store_href"),
        }

    def save_token(self, token: str) -> dict:
        self.settings.save("moysklad_token", token)
        return {"configured": True}

    def delete_token(self) -> dict:
        self.settings.delete("moysklad_token")
        self.settings.delete("moysklad_store_href")
        return {"configured": False}

    def stores(self) -> list[dict]:
        return MoyskladClient(self._require_token()).stores()

    def select_store(self, href: str) -> dict:
        token = self._require_token()
        if not any(store["href"] == href for store in MoyskladClient(token).stores()):
            raise HTTPException(400, "Выберите склад из списка МойСклад")
        self.settings.save("moysklad_store_href", href)
        return {"store_href": href}

    def local_groups(self) -> dict:
        """Локальные остатки и сопоставления (для вкладки МойСклад)."""
        groups = InventoryService(self.conn).local_stock_groups()
        mappings = self.mappings.read(self.conn)
        return {
            "groups": [dict(row) for row in groups],
            "mappings": {row["local_name"].casefold(): row["assortment_href"] for row in mappings},
            "mapping_ids": {row["local_name"].casefold(): row["mapping_id"] for row in mappings},
        }

    def compare(self) -> dict:
        """Локальные группы + сопоставления + остатки выбранного склада МойСклад."""
        token = self._require_token()
        store_href = self.settings.get("moysklad_store_href")
        if not store_href:
            raise HTTPException(400, "Выберите склад МойСклад для сравнения")
        groups = InventoryService(self.conn).local_stock_groups()
        mappings = self.mappings.read(self.conn)
        return {
            "groups": [dict(row) for row in groups],
            "mappings": {row["local_name"].casefold(): row["assortment_href"] for row in mappings},
            "mapping_ids": {row["local_name"].casefold(): row["mapping_id"] for row in mappings},
            "stock_items": MoyskladClient(token).stock_items(store_href),
        }

    def save_mapping(self, body) -> dict:
        """Сохраняет или снимает сопоставление локального названия с товаром МойСклад."""
        if not self.conn.one(
            "SELECT 1 FROM items WHERE color=? COLLATE NOCASE LIMIT 1",
            (body.local_name,),
        ):
            raise HTTPException(404, "Название не найдено в базе")
        if body.assortment_href is not None:
            MoyskladClient.validate_url(body.assortment_href)
        mappings = self.mappings.read(self.conn)
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
        self.mappings.write(mappings)
        return {
            "mapping_id": mapping_id,
            "local_name": body.local_name,
            "assortment_href": body.assortment_href,
        }
