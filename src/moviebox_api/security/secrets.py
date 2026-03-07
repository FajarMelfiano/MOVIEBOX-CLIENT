"""Secret storage helpers with environment + local backends.

Layer A security model:
- Environment variables still work for compatibility.
- If keyring backend is available, secrets can be stored encrypted by OS keychain.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

SERVICE_NAME = "moviebox-api"
SUPPORTED_SECRET_NAMES = (
    "MOVIEBOX_SUBDL_API_KEY",
    "MOVIEBOX_SUBSOURCE_API_KEY",
)

try:  # pragma: no cover - backend availability depends on runtime environment
    import keyring as _keyring
except Exception:  # pragma: no cover
    _keyring = None

_SECRETS_FILE_PATH = Path.home() / ".config" / "moviebox" / "secrets.json"


def normalize_secret_name(name: str) -> str:
    normalized = name.strip().upper()
    if normalized not in SUPPORTED_SECRET_NAMES:
        allowed = ", ".join(SUPPORTED_SECRET_NAMES)
        raise ValueError(f"Unsupported secret '{name}'. Allowed: {allowed}")
    return normalized


def keyring_available() -> bool:
    return _keyring is not None


def _read_file_secrets() -> dict[str, str]:
    try:
        if not _SECRETS_FILE_PATH.exists():
            return {}
        payload = json.loads(_SECRETS_FILE_PATH.read_text())
    except Exception:
        return {}

    if not isinstance(payload, dict):
        return {}

    normalized: dict[str, str] = {}
    for key, value in payload.items():
        try:
            normalized_name = normalize_secret_name(str(key))
        except Exception:
            continue
        normalized_value = str(value).strip()
        if normalized_value:
            normalized[normalized_name] = normalized_value

    return normalized


def _write_file_secrets(values: dict[str, str]) -> None:
    _SECRETS_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SECRETS_FILE_PATH.write_text(json.dumps(values, indent=2, sort_keys=True))
    os.chmod(_SECRETS_FILE_PATH, 0o600)


def _get_file_secret(name: str) -> str:
    values = _read_file_secrets()
    return values.get(name, "")


def _set_file_secret(name: str, value: str) -> None:
    values = _read_file_secrets()
    values[name] = value
    _write_file_secrets(values)


def _delete_file_secret(name: str) -> None:
    values = _read_file_secrets()
    if name not in values:
        return

    values.pop(name, None)
    if not values:
        try:
            _SECRETS_FILE_PATH.unlink()
        except Exception:
            return
        return

    _write_file_secrets(values)


def get_secret(name: str, default: str = "") -> str:
    normalized = normalize_secret_name(name)

    env_value = os.getenv(normalized, "").strip()
    if env_value:
        return env_value

    if _keyring is None:
        file_value = _get_file_secret(normalized)
        return file_value or default

    try:
        stored_value = _keyring.get_password(SERVICE_NAME, normalized)
    except Exception:
        file_value = _get_file_secret(normalized)
        return file_value or default

    if not stored_value:
        file_value = _get_file_secret(normalized)
        return file_value or default

    value = str(stored_value).strip()
    return value or default


def secret_source(name: str) -> str:
    normalized = normalize_secret_name(name)

    if os.getenv(normalized, "").strip():
        return "env"
    if _keyring is None:
        return "file" if _get_file_secret(normalized) else "none"

    try:
        value = _keyring.get_password(SERVICE_NAME, normalized)
    except Exception:
        return "file" if _get_file_secret(normalized) else "none"

    if str(value or "").strip():
        return "keyring"
    return "file" if _get_file_secret(normalized) else "none"


def set_secret(name: str, value: str) -> None:
    normalized = normalize_secret_name(name)
    normalized_value = value.strip()
    if not normalized_value:
        raise ValueError("Secret value cannot be empty")

    if _keyring is not None:
        try:
            _keyring.set_password(SERVICE_NAME, normalized, normalized_value)
            return
        except Exception:
            pass

    _set_file_secret(normalized, normalized_value)


def delete_secret(name: str) -> None:
    normalized = normalize_secret_name(name)
    if _keyring is not None:
        try:
            _keyring.delete_password(SERVICE_NAME, normalized)
        except Exception:
            pass

    _delete_file_secret(normalized)


def supported_secrets() -> tuple[str, ...]:
    return SUPPORTED_SECRET_NAMES
