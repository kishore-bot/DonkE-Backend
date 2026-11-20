from hashlib import sha256
from secrets import token_urlsafe


def token_digest(token: str) -> bytes:
    return sha256(token.encode()).digest()


def new_token() -> str:
    return token_urlsafe(32)
