"""Application-level encryption for credentials persisted by provider connections."""

import base64
import binascii
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr


class CredentialEncryptionError(RuntimeError):
    """The credential vault is unavailable or ciphertext cannot be decrypted."""


@dataclass(frozen=True, slots=True, repr=False)
class EncryptedCredentials:
    token: str

    def __post_init__(self) -> None:
        try:
            raw = base64.b64decode(self.token.encode("ascii"), altchars=b"-_", validate=True)
        except (binascii.Error, UnicodeEncodeError, ValueError) as exc:
            raise ValueError("credentials must be a Fernet ciphertext") from exc
        if len(raw) < 73 or raw[0] != 0x80 or (len(raw) - 57) % 16:
            raise ValueError("credentials must be a Fernet ciphertext")

    def __repr__(self) -> str:
        return "EncryptedCredentials([REDACTED])"


class CredentialCipher:
    __slots__ = ("_fernet",)

    def __init__(self, key: SecretStr | str | None) -> None:
        raw_key = key.get_secret_value() if isinstance(key, SecretStr) else key
        if not raw_key:
            raise CredentialEncryptionError("credential encryption is not configured")
        try:
            self._fernet = Fernet(raw_key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise CredentialEncryptionError("credential encryption key is invalid") from exc

    def encrypt(self, credentials: str | bytes) -> EncryptedCredentials:
        raw = credentials.encode("utf-8") if isinstance(credentials, str) else credentials
        return EncryptedCredentials(self._fernet.encrypt(raw).decode("ascii"))

    def decrypt(self, encrypted: EncryptedCredentials) -> bytes:
        if not isinstance(encrypted, EncryptedCredentials):
            raise CredentialEncryptionError("credentials must be stored as encrypted ciphertext")
        try:
            return self._fernet.decrypt(encrypted.token.encode("ascii"))
        except (InvalidToken, UnicodeEncodeError) as exc:
            raise CredentialEncryptionError("stored credentials could not be decrypted") from exc
