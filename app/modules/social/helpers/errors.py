from app.core.errors import AppError


def missing(code: str) -> AppError:
    return AppError(404, code, "Social record not found")


def conflict(code: str, detail: str) -> AppError:
    return AppError(409, code, detail)
