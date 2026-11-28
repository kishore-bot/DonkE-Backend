from app.core.errors import AppError


def unauthorized() -> AppError:
    return AppError(401, "invalid_session", "Sign in to continue")
