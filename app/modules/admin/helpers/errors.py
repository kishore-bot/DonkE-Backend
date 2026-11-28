from app.core.errors import AppError


def invalid_admin() -> AppError:
    return AppError(401, "invalid_admin_session", "Admin authentication failed")
