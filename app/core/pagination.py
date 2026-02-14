import base64
from dataclasses import dataclass


@dataclass
class Page:
    limit: int
    offset: int


def decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        value = base64.urlsafe_b64decode(cursor.encode("utf-8")).decode("utf-8")
        return max(int(value), 0)
    except Exception:
        return 0


def encode_cursor(offset: int | None) -> str | None:
    if offset is None:
        return None
    return base64.urlsafe_b64encode(str(offset).encode("utf-8")).decode("utf-8")


def paginate(limit: int, cursor: str | None, default_limit: int, max_limit: int) -> Page:
    clamped_limit = min(max(limit or default_limit, 1), max_limit)
    offset = decode_cursor(cursor)
    return Page(limit=clamped_limit, offset=offset)
