from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class LivePulseError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code


async def livepulse_error_handler(_request: Request, exc: LivePulseError) -> JSONResponse:
    request_id = getattr(_request.state, "request_id", "unknown")
    body: dict[str, Any] = {
        "error": {"code": exc.code, "message": exc.message, "request_id": request_id}
    }
    return JSONResponse(status_code=exc.status_code, content=body)
