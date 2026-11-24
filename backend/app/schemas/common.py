"""Shared Pydantic v2 DTOs and response helpers."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    success: bool = True
    data: T | None = None
    meta: dict[str, Any] | None = None
    errors: list[dict[str, Any]] = Field(default_factory=list)


class PageMeta(BaseModel):
    page: int
    page_size: int
    total: int
    pages: int


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, ser_json_inf_nan="null")


class DecimalModel(BaseModel):
    """Decimal fields are serialised as strings to preserve exact precision."""

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={Decimal: lambda v: format(v.normalize(), "f")},
    )


def ok(data: Any = None, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"success": True, "data": data, "meta": meta, "errors": []}
