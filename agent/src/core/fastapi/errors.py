"""The last line of defense: an unexpected error becomes a safe 500 and an ``unhandled_error`` event."""
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.core.observability.events import emit

logger = logging.getLogger(__name__)

UNHANDLED_ERROR_MESSAGE = "Something went wrong. Please try again."


async def _unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    # The stack trace stays in the service log; the client gets a safe message, the trace gets the event.
    logger.error("unhandled_error method=%s path=%s", request.method, request.url.path, exc_info=exc)
    emit("unhandled_error", method=request.method, route=request.url.path, error=type(exc).__name__)
    return JSONResponse({"detail": UNHANDLED_ERROR_MESSAGE}, status_code=500)


def register_unhandled_error_handler(app: FastAPI) -> None:
    app.add_exception_handler(Exception, _unhandled_error)
