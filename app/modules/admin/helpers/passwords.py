from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

HASHER = PasswordHasher()


# Verification cost for a missing username. This hash is never attached to an account.
DUMMY_HASH = "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQyNGNoYXJhY3Q$3pDP9EbuNjlGk1gUFYRhZbp8F0S6rxQ4T91c78Opy0s"


def password_matches(hash_value: str, password: str) -> bool:
    try:
        return HASHER.verify(hash_value, password)
    except InvalidHashError, VerificationError:
        return False
