from __future__ import annotations

import json

import pytest

from infrastructure.config import credential_manager as credential_module
from infrastructure.config.credential_manager import CredentialManager
from infrastructure.config.settings import (
    CREDENTIAL_TYPE_EMBEDDING,
    CREDENTIAL_TYPE_LLM,
)


@pytest.fixture
def manager(tmp_path, monkeypatch) -> CredentialManager:
    monkeypatch.setattr(credential_module, "GLOBAL_CONFIG_DIR", tmp_path)
    instance = CredentialManager()
    assert instance.load_credentials() is True
    return instance


def test_dpapi_round_trip_uses_current_windows_user() -> None:
    plaintext = b"sk-round-trip-secret"

    ciphertext = CredentialManager._protect_payload(plaintext)

    assert ciphertext != plaintext
    assert plaintext not in ciphertext
    assert CredentialManager._unprotect_payload(ciphertext) == plaintext


def test_credential_is_kept_across_manager_instances_without_plaintext_on_disk(
    manager: CredentialManager,
) -> None:
    secret = "sk-current-provider-secret-123"

    assert manager.set_llm_api_key("openai", f"  {secret}  ") is True
    assert manager.has_credential(CREDENTIAL_TYPE_LLM, "openai") is True
    assert manager.get_llm_api_key("openai") == secret
    assert manager.list_providers(CREDENTIAL_TYPE_LLM) == ["openai"]
    assert secret.encode("utf-8") not in manager._credentials_file.read_bytes()

    restored = CredentialManager()
    assert restored.load_credentials() is True
    assert restored.get_llm_api_key("openai") == secret
    assert restored.has_credential(CREDENTIAL_TYPE_LLM, "openai") is True


def test_replacing_credential_persists_only_the_new_value(
    manager: CredentialManager,
) -> None:
    old_secret = "sk-old-secret-value"
    new_secret = "sk-new-secret-value"
    assert manager.set_llm_api_key("anthropic", old_secret) is True

    assert manager.set_llm_api_key("anthropic", new_secret) is True

    restored = CredentialManager()
    assert restored.load_credentials() is True
    assert restored.get_llm_api_key("anthropic") == new_secret
    encrypted = restored._credentials_file.read_bytes()
    assert old_secret.encode("utf-8") not in encrypted
    assert new_secret.encode("utf-8") not in encrypted


def test_deleting_credential_persists_and_has_returns_false(
    manager: CredentialManager,
) -> None:
    assert manager.set_embedding_api_key("zhipu", "embedding-secret-key") is True
    assert manager.has_credential(CREDENTIAL_TYPE_EMBEDDING, "zhipu") is True

    assert manager.delete_credential(CREDENTIAL_TYPE_EMBEDDING, "zhipu") is True
    assert manager.delete_credential(CREDENTIAL_TYPE_EMBEDDING, "zhipu") is True
    assert manager.has_credential(CREDENTIAL_TYPE_EMBEDDING, "zhipu") is False

    restored = CredentialManager()
    assert restored.load_credentials() is True
    assert restored.get_embedding_api_key("zhipu") == ""
    assert restored.list_providers(CREDENTIAL_TYPE_EMBEDDING) == []


def test_plaintext_legacy_file_is_deleted_without_migration(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(credential_module, "GLOBAL_CONFIG_DIR", tmp_path)
    legacy_secret = "sk-legacy-plaintext-secret"
    legacy_file = tmp_path / "credentials.json"
    legacy_file.write_text(
        json.dumps({"llm": {"openai": {"api_key": legacy_secret}}}),
        encoding="utf-8",
    )

    instance = CredentialManager()
    assert instance.load_credentials() is True

    assert legacy_file.exists() is False
    assert instance.get_llm_api_key("openai") == ""
    assert instance._credentials_file.exists() is True
    assert legacy_secret.encode("utf-8") not in instance._credentials_file.read_bytes()


def test_invalid_encrypted_store_fails_closed(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(credential_module, "GLOBAL_CONFIG_DIR", tmp_path)
    encrypted_file = tmp_path / "credentials.dat"
    encrypted_file.write_bytes(b"not-a-credential-store")

    instance = CredentialManager()

    assert instance.load_credentials() is False
    assert instance.get_llm_api_key("openai") == ""
    assert instance.has_credential(CREDENTIAL_TYPE_LLM, "openai") is False
