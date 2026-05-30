from __future__ import annotations

import base64
import hashlib


class ConfigDecryptError(ValueError):
    """Raised when encrypted config cannot be decrypted with the provided password."""


def _load_fernet():
    try:
        from cryptography.fernet import Fernet, InvalidToken
    except ImportError as exc:
        raise RuntimeError(
            "cryptography is required for .env.enc support. "
            "Install it into the local environment before encrypting config."
        ) from exc
    return Fernet, InvalidToken


def _password_key(password: str) -> bytes:
    if not password:
        raise ValueError("Password must not be empty.")
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_env_text(plaintext: str, password: str) -> str:
    Fernet, _ = _load_fernet()
    token = Fernet(_password_key(password)).encrypt(plaintext.encode("utf-8"))
    return token.decode("ascii")


def decrypt_env_text(ciphertext: str, password: str) -> str:
    Fernet, InvalidToken = _load_fernet()
    try:
        plaintext = Fernet(_password_key(password)).decrypt(ciphertext.encode("ascii"))
    except InvalidToken as exc:
        raise ConfigDecryptError("Cannot decrypt .env.enc. The password is wrong or the file is corrupted.") from exc
    return plaintext.decode("utf-8")

