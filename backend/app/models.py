"""Pydantic-модели запросов API."""

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, validator


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
