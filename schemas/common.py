import re
from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")

_UNSAFE = re.compile(r"[\x00-\x1f\x7f<>]")
_SPACES = re.compile(r"\s+")


def clean_text(value: object) -> object:
    if not isinstance(value, str):
        return value
    value = _SPACES.sub(" ", value).strip()
    if _UNSAFE.search(value):
        raise ValueError("must not contain < > or control characters")
    return value


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int
