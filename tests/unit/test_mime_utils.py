from app.core.mime_utils import OCTET_STREAM, effective_preview_mime, normalize_mime


def test_normalize_mime_valid_with_params():
    assert normalize_mime("Text/Plain; charset=UTF-8") == "text/plain"


def test_normalize_mime_invalid_or_missing_to_octet_stream():
    assert normalize_mime(None) == OCTET_STREAM
    assert normalize_mime("") == OCTET_STREAM
    assert normalize_mime("not-a-mime") == OCTET_STREAM


def test_effective_preview_mime_guesses_from_filename_when_generic():
    assert effective_preview_mime("application/octet-stream", "file.pdf") == "application/pdf"


def test_effective_preview_mime_stays_generic_for_unknown_extension():
    assert effective_preview_mime("application/octet-stream", "file.unknownext") == OCTET_STREAM
