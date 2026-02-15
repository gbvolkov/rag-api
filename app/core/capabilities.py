from __future__ import annotations

import importlib.util

from app.core.errors import api_error


def module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def require_feature(enabled: bool, feature_name: str, hint: str | None = None) -> None:
    if enabled:
        return
    raise api_error(
        403,
        "capability_disabled",
        f"Capability '{feature_name}' is disabled",
        {"feature": feature_name},
        hint=hint,
    )


def require_module(module_name: str, capability_name: str, install_hint: str | None = None) -> None:
    if module_available(module_name):
        return
    raise api_error(
        424,
        "missing_dependency",
        f"Capability '{capability_name}' requires optional dependency '{module_name}'",
        {"module": module_name, "capability": capability_name},
        hint=install_hint,
    )


def require_choice(
    value: str,
    allowed: set[str],
    *,
    code: str,
    message: str,
    field: str,
) -> None:
    if value in allowed:
        return
    raise api_error(400, code, message, {field: value, "allowed": sorted(allowed)})

