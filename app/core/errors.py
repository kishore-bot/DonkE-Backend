from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code


async def handle_app_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    body = ErrorResponse(error=ErrorBody(code=exc.code, message=str(exc)))
    headers = {"Cache-Control": "no-store"}
    if exc.status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    return JSONResponse(body.model_dump(), status_code=exc.status, headers=headers)


async def handle_validation_error(request: Request, _: Exception) -> JSONResponse:
    return await handle_app_error(
        request, AppError(422, "invalid_request", "Check the request fields")
    )
