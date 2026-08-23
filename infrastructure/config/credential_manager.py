"""Per-user API credential storage backed by Windows DPAPI.

Only the Windows account that saved the credentials can decrypt them. The
encrypted payload is kept separate from ordinary application settings and is
written atomically so an interrupted save cannot leave half a credential file.

The former ``credentials.json`` format intentionally is not migrated: it
stored API keys as plaintext. It is deleted when this manager first loads.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from datetime import datetime
import json
import os
from threading import RLock
from typing import Any, Dict, List, Optional

from .settings import (
    CREDENTIALS_FILE,
    CREDENTIAL_TYPE_EMBEDDING,
    CREDENTIAL_TYPE_LLM,
    GLOBAL_CONFIG_DIR,
)


_FILE_MAGIC = b"CDAI-CREDENTIALS\x00\x01"
_DPAPI_ENTROPY = b"Circuit Design AI credential store v1"
_DPAPI_DESCRIPTION = "Circuit Design AI API credentials"
_CRYPTPROTECT_UI_FORBIDDEN = 0x01
_MISSING = object()


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _blob_from_bytes(value: bytes) -> tuple[_DataBlob, Any]:
    """Return a DPAPI DATA_BLOB and keep its backing buffer alive."""

    buffer = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
    blob = _DataBlob(
        len(value),
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    return blob, buffer


class CredentialManager:
    """Store provider API keys in one Windows-user-protected local file."""

    def __init__(self):
        self._credentials_file = GLOBAL_CONFIG_DIR / CREDENTIALS_FILE
        self._legacy_credentials_file = GLOBAL_CONFIG_DIR / "credentials.json"
        self._credentials: Dict[str, Dict[str, Dict[str, Any]]] = self._empty_store()
        self._lock = RLock()
        self._loaded = False

    @staticmethod
    def _empty_store() -> Dict[str, Dict[str, Dict[str, Any]]]:
        return {
            CREDENTIAL_TYPE_LLM: {},
            CREDENTIAL_TYPE_EMBEDDING: {},
        }

    def load_credentials(self) -> bool:
        """Load and decrypt saved credentials, failing closed on any error."""

        with self._lock:
            try:
                GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
                self._discard_legacy_plaintext()

                if not self._credentials_file.exists():
                    self._credentials = self._empty_store()
                    if not self._save_credentials_internal():
                        raise OSError("无法创建加密凭证文件")
                else:
                    encoded = self._credentials_file.read_bytes()
                    if not encoded.startswith(_FILE_MAGIC):
                        raise ValueError("凭证文件格式无效")
                    plaintext = self._unprotect_payload(encoded[len(_FILE_MAGIC) :])
                    parsed = json.loads(plaintext.decode("utf-8"))
                    self._credentials = self._validate_store(parsed)

                self._loaded = True
                self._log_info("加密凭证加载成功")
                return True
            except Exception as exc:
                self._credentials = self._empty_store()
                self._loaded = True
                self._log_error(f"加密凭证加载失败: {exc}")
                return False

    def _discard_legacy_plaintext(self) -> None:
        """Delete the obsolete plaintext store without importing its values."""

        if self._legacy_credentials_file == self._credentials_file:
            return
        if self._legacy_credentials_file.exists():
            self._legacy_credentials_file.unlink()
            self._log_warning("已删除旧版明文凭证文件，请重新填写 API Key")

    @staticmethod
    def _validate_store(value: Any) -> Dict[str, Dict[str, Dict[str, Any]]]:
        if not isinstance(value, dict):
            raise ValueError("凭证数据必须是对象")

        result: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for provider_type in (CREDENTIAL_TYPE_LLM, CREDENTIAL_TYPE_EMBEDDING):
            providers = value.get(provider_type, {})
            if not isinstance(providers, dict):
                raise ValueError(f"凭证分组格式无效: {provider_type}")

            checked: Dict[str, Dict[str, Any]] = {}
            for provider_id, credential in providers.items():
                if not isinstance(provider_id, str) or not isinstance(credential, dict):
                    raise ValueError(f"厂商凭证格式无效: {provider_type}")
                api_key = credential.get("api_key", "")
                if not isinstance(api_key, str):
                    raise ValueError(f"API Key 格式无效: {provider_type}/{provider_id}")
                normalized = dict(credential)
                normalized["api_key"] = api_key.strip()
                checked[provider_id] = normalized
            result[provider_type] = checked
        return result

    def _save_credentials_internal(self) -> bool:
        """Encrypt and atomically replace the credential file (lock held)."""

        temporary_file = self._credentials_file.with_suffix(
            self._credentials_file.suffix + ".tmp"
        )
        try:
            GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            serialized = json.dumps(
                self._credentials,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            encrypted = _FILE_MAGIC + self._protect_payload(serialized)

            with temporary_file.open("wb") as handle:
                handle.write(encrypted)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_file, self._credentials_file)
            self._log_info("加密凭证保存成功")
            return True
        except Exception as exc:
            try:
                temporary_file.unlink(missing_ok=True)
            except OSError:
                pass
            self._log_error(f"加密凭证保存失败: {exc}")
            return False

    @staticmethod
    def _protect_payload(plaintext: bytes) -> bytes:
        return CredentialManager._call_dpapi("CryptProtectData", plaintext)

    @staticmethod
    def _unprotect_payload(ciphertext: bytes) -> bytes:
        return CredentialManager._call_dpapi("CryptUnprotectData", ciphertext)

    @staticmethod
    def _call_dpapi(operation: str, value: bytes) -> bytes:
        """Protect or unprotect bytes for the current Windows user."""

        if os.name != "nt":
            raise OSError("API 凭证存储需要 Windows DPAPI")
        if not value:
            raise ValueError("DPAPI 输入不能为空")

        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        function = getattr(crypt32, operation)
        function.argtypes = [
            ctypes.POINTER(_DataBlob),
            wintypes.LPCWSTR if operation == "CryptProtectData" else ctypes.c_void_p,
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]
        function.restype = wintypes.BOOL
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p

        input_blob, input_buffer = _blob_from_bytes(value)
        entropy_blob, entropy_buffer = _blob_from_bytes(_DPAPI_ENTROPY)
        output_blob = _DataBlob()
        description = _DPAPI_DESCRIPTION if operation == "CryptProtectData" else None

        # Both backing buffers must remain live until the native call returns.
        _ = input_buffer, entropy_buffer
        succeeded = function(
            ctypes.byref(input_blob),
            description,
            ctypes.byref(entropy_blob),
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output_blob),
        )
        if not succeeded:
            error_code = ctypes.get_last_error()
            raise OSError(error_code, ctypes.FormatError(error_code))

        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            kernel32.LocalFree(ctypes.cast(output_blob.pbData, ctypes.c_void_p))

    def get_credential(
        self,
        provider_type: str,
        provider_id: str,
    ) -> Optional[Dict[str, Any]]:
        with self._lock:
            credential = self._credentials.get(provider_type, {}).get(provider_id)
            if not credential:
                return None
            result = dict(credential)
            api_key = result.get("api_key", "")
            if isinstance(api_key, str):
                result["api_key"] = api_key.strip()
            return result

    def set_credential(
        self,
        provider_type: str,
        provider_id: str,
        credential_data: Dict[str, Any],
    ) -> bool:
        with self._lock:
            type_credentials = self._credentials.setdefault(provider_type, {})
            previous = type_credentials.get(provider_id, _MISSING)

            store_data = dict(credential_data)
            api_key = store_data.get("api_key", "")
            if isinstance(api_key, str):
                store_data["api_key"] = api_key.strip()
            store_data["updated_at"] = datetime.now().isoformat()
            type_credentials[provider_id] = store_data

            if self._save_credentials_internal():
                self._log_info(f"凭证已保存: {provider_type}/{provider_id}")
                return True

            if previous is _MISSING:
                type_credentials.pop(provider_id, None)
            else:
                type_credentials[provider_id] = previous
            return False

    def delete_credential(self, provider_type: str, provider_id: str) -> bool:
        with self._lock:
            type_credentials = self._credentials.get(provider_type, {})
            previous = type_credentials.get(provider_id, _MISSING)
            if previous is _MISSING:
                return True

            del type_credentials[provider_id]
            if self._save_credentials_internal():
                self._log_info(f"凭证已删除: {provider_type}/{provider_id}")
                return True

            type_credentials[provider_id] = previous
            return False

    def has_credential(self, provider_type: str, provider_id: str) -> bool:
        with self._lock:
            credential = self._credentials.get(provider_type, {}).get(provider_id, {})
            return bool(credential.get("api_key"))

    def list_providers(self, provider_type: str) -> List[str]:
        with self._lock:
            return [
                provider_id
                for provider_id, credential in self._credentials.get(provider_type, {}).items()
                if credential.get("api_key")
            ]

    def validate_credential(
        self,
        provider_type: str,
        provider_id: str,
    ) -> tuple[bool, str]:
        credential = self.get_credential(provider_type, provider_id)
        if not credential:
            return False, "凭证不存在"
        api_key = credential.get("api_key", "")
        if not api_key:
            return False, "API Key 为空"
        if len(api_key) < 10:
            return False, "API Key 长度过短"
        return True, ""

    def get_llm_api_key(self, provider_id: str) -> str:
        credential = self.get_credential(CREDENTIAL_TYPE_LLM, provider_id)
        return credential.get("api_key", "") if credential else ""

    def set_llm_api_key(self, provider_id: str, api_key: str) -> bool:
        return self.set_credential(CREDENTIAL_TYPE_LLM, provider_id, {"api_key": api_key})

    def get_embedding_api_key(self, provider_id: str) -> str:
        credential = self.get_credential(CREDENTIAL_TYPE_EMBEDDING, provider_id)
        return credential.get("api_key", "") if credential else ""

    def set_embedding_api_key(self, provider_id: str, api_key: str) -> bool:
        return self.set_credential(
            CREDENTIAL_TYPE_EMBEDDING,
            provider_id,
            {"api_key": api_key},
        )

    def _log_info(self, message: str) -> None:
        try:
            from infrastructure.utils.logger import get_logger

            get_logger("credential_manager").info(message)
        except Exception:
            print(f"[INFO] CredentialManager: {message}")

    def _log_warning(self, message: str) -> None:
        try:
            from infrastructure.utils.logger import get_logger

            get_logger("credential_manager").warning(message)
        except Exception:
            print(f"[WARNING] CredentialManager: {message}")

    def _log_error(self, message: str) -> None:
        try:
            from infrastructure.utils.logger import get_logger

            get_logger("credential_manager").error(message)
        except Exception:
            print(f"[ERROR] CredentialManager: {message}")


__all__ = ["CredentialManager"]
