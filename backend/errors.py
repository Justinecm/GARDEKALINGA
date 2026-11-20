"""One error shape for every API response:
{"error": {"code": "...", "message": "...", "fields": {...}}}
"""
from __future__ import annotations

import logging

from flask import Flask, jsonify
from pydantic import ValidationError
from werkzeug.exceptions import HTTPException

log = logging.getLogger("gardekalinga")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, fields: dict | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.fields = fields or {}


def error_response(status: int, code: str, message: str, fields: dict | None = None):
    body = {"error": {"code": code, "message": message}}
    if fields:
        body["error"]["fields"] = fields
    return jsonify(body), status


def pydantic_fields(exc: ValidationError) -> dict:
    out: dict[str, str] = {}
    for e in exc.errors():
        loc = ".".join(str(p) for p in e.get("loc", ())) or "_"
        out[loc] = e.get("msg", "Invalid value")
    return out


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def _api_error(e: ApiError):
        return error_response(e.status, e.code, e.message, e.fields)

    @app.errorhandler(ValidationError)
    def _validation(e: ValidationError):
        return error_response(422, "validation_error", "Some fields are not valid.", pydantic_fields(e))

    @app.errorhandler(HTTPException)
    def _http(e: HTTPException):
        code = (e.name or "error").lower().replace(" ", "_")
        return error_response(e.code or 500, code, e.description or e.name)

    @app.errorhandler(Exception)
    def _unexpected(e: Exception):  # never leak stack traces
        log.exception("unhandled error")
        return error_response(500, "server_error", "Something went wrong on the server. Please try again.")
