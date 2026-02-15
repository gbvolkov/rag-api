import mimetypes
import re


OCTET_STREAM = "application/octet-stream"

_MIME_PATTERN = re.compile(r"^[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+$")


def normalize_mime(raw_mime: str | None) -> str:
    if not raw_mime:
        return OCTET_STREAM

    base = raw_mime.split(";", 1)[0].strip().lower()
    if not base or not _MIME_PATTERN.match(base):
        return OCTET_STREAM
    return base


def effective_preview_mime(stored_mime: str, filename: str) -> str:
    normalized = normalize_mime(stored_mime)
    if normalized != OCTET_STREAM:
        return normalized

    guessed, _encoding = mimetypes.guess_type(filename)
    guessed_normalized = normalize_mime(guessed)
    if guessed_normalized != OCTET_STREAM:
        return guessed_normalized

    return OCTET_STREAM
