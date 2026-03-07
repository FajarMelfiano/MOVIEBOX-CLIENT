"""Secret storage helpers with environment + keyring backends.

Layer A security model:
- Environment variables still work for compatibility.
- If keyring backend is available, secrets can be stored encrypted by OS keychain.
"""

from __future__ import annotations

import os
from typing import Any

SERVICE_NAME = "moviebox-api"
SUPPORTED_SECRET_NAMES = (
    "MOVIEBOX_SUBDL_API_KEY",
    "MOVIEBOX_SUBSOURCE_API_KEY",
)

try:  # pragma: no cover - backend availability depends on runtime environment
    import keyring as _keyring
except Exception:  # pragma: no cover
    _keyring = None


def normalize_secret_name(name: str) -> str:
    normalized = name.strip().upper()
    if normalized not in SUPPORTED_SECRET_NAMES:
        allowed = ", ".join(SUPPORTED_SECRET_NAMES)
        raise ValueError(f"Unsupported secret '{name}'. Allowed: {allowed}")
    return normalized


def keyring_available() -> bool:
    return _keyring is not None


def get_secret(name: str, default: str = "") -> str:
    normalized = normalize_secret_name(name)

    env_value = os.getenv(normalized, "").strip()
    if env_value:
        return env_value

    if _keyring is None:
        return default

    try:
        stored_value = _keyring.get_password(SERVICE_NAME, normalized)
    except Exception:
        return default

    if not stored_value:
        return default

    value = str(stored_value).strip()
    return value or default


def secret_source(name: str) -> str:
    normalized = normalize_secret_name(name)

    if os.getenv(normalized, "").strip():
        return "env"
    if _keyring is None:
        return "none"

    try:
        value = _keyring.get_password(SERVICE_NAME, normalized)
    except Exception:
        return "none"

    return "keyring" if str(value or "").strip() else "none"


def set_secret(name: str, value: str) -> None:
    normalized = normalize_secret_name(name)
    normalized_value = value.strip()
    if not normalized_value:
        raise ValueError("Secret value cannot be empty")

    if _keyring is None:
        raise RuntimeError("Keyring backend is unavailable. Install keyring and a system keyring backend.")

    _keyring.set_password(SERVICE_NAME, normalized, normalized_value)


def delete_secret(name: str) -> None:
    normalized = normalize_secret_name(name)
    if _keyring is None:
        return

    try:
        _keyring.delete_password(SERVICE_NAME, normalized)
    except Exception:
        return


def supported_secrets() -> tuple[str, ...]:
    return SUPPORTED_SECRET_NAMES
