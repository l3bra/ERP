"""Общие вспомогательные функции."""

from datetime import datetime
from typing import Any


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def dump(model) -> dict[str, Any]:
    """Словарь только явно переданных полей Pydantic-модели."""
    return model.model_dump(exclude_unset=True) if hasattr(model, "model_dump") \
        else model.dict(exclude_unset=True)
