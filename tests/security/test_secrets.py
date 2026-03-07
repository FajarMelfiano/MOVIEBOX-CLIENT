import pytest

from moviebox_api.security import secrets as secrets_mod


class _FakeKeyring:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get_password(self, service_name: str, username: str):
        return self.values.get((service_name, username))

    def set_password(self, service_name: str, username: str, password: str):
        self.values[(service_name, username)] = password

    def delete_password(self, service_name: str, username: str):
        self.values.pop((service_name, username), None)


def test_get_secret_prefers_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MOVIEBOX_SUBDL_API_KEY", "env-value")

    assert secrets_mod.get_secret("MOVIEBOX_SUBDL_API_KEY") == "env-value"
    assert secrets_mod.secret_source("MOVIEBOX_SUBDL_API_KEY") == "env"


def test_get_secret_reads_keyring_when_env_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MOVIEBOX_SUBDL_API_KEY", raising=False)
    fake_keyring = _FakeKeyring(
        {
            (secrets_mod.SERVICE_NAME, "MOVIEBOX_SUBDL_API_KEY"): "stored-value",
        }
    )
    monkeypatch.setattr(secrets_mod, "_keyring", fake_keyring)

    assert secrets_mod.get_secret("MOVIEBOX_SUBDL_API_KEY") == "stored-value"
    assert secrets_mod.secret_source("MOVIEBOX_SUBDL_API_KEY") == "keyring"


def test_set_secret_raises_without_keyring(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(secrets_mod, "_keyring", None)

    with pytest.raises(RuntimeError, match="Keyring backend is unavailable"):
        secrets_mod.set_secret("MOVIEBOX_SUBDL_API_KEY", "abc")


def test_set_secret_writes_to_keyring(monkeypatch: pytest.MonkeyPatch):
    fake_keyring = _FakeKeyring()
    monkeypatch.setattr(secrets_mod, "_keyring", fake_keyring)

    secrets_mod.set_secret("MOVIEBOX_SUBSOURCE_API_KEY", "my-value")

    assert fake_keyring.get_password(secrets_mod.SERVICE_NAME, "MOVIEBOX_SUBSOURCE_API_KEY") == "my-value"
