from app.core.pagination import decode_cursor, encode_cursor, paginate


def test_cursor_roundtrip():
    value = encode_cursor(123)
    assert decode_cursor(value) == 123


def test_paginate_bounds():
    page = paginate(limit=1000, cursor=None, default_limit=20, max_limit=50)
    assert page.limit == 50
    assert page.offset == 0
