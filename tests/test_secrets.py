from types import SimpleNamespace

import pytest

from app.services import secret_service
from app.services.secret_service import ENCRYPTED_PREFIX, SecretService


def test_secret_service_encrypts_with_prefix_and_decrypts(monkeypatch):
    monkeypatch.setattr(
        secret_service,
        "get_settings",
        lambda: SimpleNamespace(secret_encryption_key="unit-test-key", debug=True),
    )
    service = SecretService()

    encrypted = service.encrypt("plain-secret")

    assert encrypted.startswith(ENCRYPTED_PREFIX)
    assert encrypted != "plain-secret"
    assert service.decrypt(encrypted) == "plain-secret"


def test_secret_service_keeps_legacy_plaintext_readable(monkeypatch):
    monkeypatch.setattr(
        secret_service,
        "get_settings",
        lambda: SimpleNamespace(secret_encryption_key="", debug=True),
    )

    assert SecretService().decrypt("legacy-secret") == "legacy-secret"


def test_secret_service_requires_key_outside_debug(monkeypatch):
    monkeypatch.setattr(
        secret_service,
        "get_settings",
        lambda: SimpleNamespace(secret_encryption_key="", debug=False),
    )

    with pytest.raises(secret_service.SecretServiceError):
        SecretService().encrypt("plain-secret")
