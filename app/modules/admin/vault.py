"""Encryption at rest for admin TOTP secrets.

AES-256-GCM with a random 96-bit nonce per secret. The admin's id is the
associated data, so a sealed secret only opens for the account it belongs
to; copying it onto another row fails. The key comes from
DONKE_ADMIN_TOTP_KEY, or is derived from DONKE_AUTH_SECRET with HKDF under a
separate label. Rotating the key requires re-enrolling two-factor sign-in.
"""

import base64
import os
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import Settings
from app.core.errors import AppError

PREFIX = "v1:"
INFO = b"donke admin totp v1"


def _key(settings: Settings) -> bytes:
    material = settings.admin_totp_key or settings.auth_secret
    if material is None:
        raise AppError(503, "totp_unavailable", "Two-factor sign-in is not configured")
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=INFO).derive(
        material.get_secret_value().encode()
    )


def is_sealed(stored: str) -> bool:
    return stored.startswith(PREFIX)


def seal(settings: Settings, admin_id: UUID, secret: str) -> str:
    nonce = os.urandom(12)
    sealed = AESGCM(_key(settings)).encrypt(nonce, secret.encode(), admin_id.bytes)
    return PREFIX + base64.urlsafe_b64encode(nonce + sealed).decode()


def unseal(settings: Settings, admin_id: UUID, stored: str) -> str:
    if not is_sealed(stored):
        raise AppError(500, "totp_unreadable", "Re-enrol two-factor sign-in")
    raw = base64.urlsafe_b64decode(stored.removeprefix(PREFIX))
    try:
        return (
            AESGCM(_key(settings)).decrypt(raw[:12], raw[12:], admin_id.bytes).decode()
        )
    except InvalidTag as error:
        raise AppError(500, "totp_unreadable", "Re-enrol two-factor sign-in") from error
