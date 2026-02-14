from fastapi import HTTPException


def api_error(status_code: int, code: str, message: str, detail: dict | None = None, hint: str | None = None) -> HTTPException:
    payload = {
        "code": code,
        "message": message,
        "detail": detail or {},
        "hint": hint,
    }
    return HTTPException(status_code=status_code, detail=payload)
