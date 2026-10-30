import re
from decimal import Decimal
from typing import Annotated, Generic, TypeVar

from pydantic import AfterValidator, BaseModel, PlainSerializer, StringConstraints

T = TypeVar("T")

_UNSAFE = re.compile(r"[\x00-\x1f\x7f<>]")
_SPACES = re.compile(r"\s+")


def clean_text(value: str) -> str:
    value = _SPACES.sub(" ", value).strip()
    if _UNSAFE.search(value):
        raise ValueError("must not contain < > or control characters")
    return value


Text = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
    AfterValidator(clean_text),
]
Text100 = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
    AfterValidator(clean_text),
]
Text255 = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
    AfterValidator(clean_text),
]
Reason = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=5, max_length=1000),
    AfterValidator(clean_text),
]

Coordinate = Annotated[
    Decimal, PlainSerializer(float, return_type=float, when_used="json")
]


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int
