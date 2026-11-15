import uuid
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


class ApiError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        rid = str(uuid.uuid4())
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        return response


async def api_error_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message, "request_id": getattr(request.state, "request_id", None)}},
    )
