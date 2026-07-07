"""Optional dependency loaders for agent transports.

This module centralizes lazy imports for optional HTTP backends
used by the agent transport layer.
"""


def _require_fastapi(*, validate_schema: bool = False):
    """Import FastAPI lazily and return required symbols.

    Raises
    ------
    ImportError
        If FastAPI is not installed.
    """
    try:
        from fastapi import FastAPI, Request
        from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
        from pydantic import BaseModel
    except ImportError as exc:
        raise ImportError(
            "FastAPI backend requires the 'fastapi' extra. Install it with: pip install protolink[fastapi]"
        ) from exc

    return FastAPI, Request, JSONResponse, HTMLResponse, StreamingResponse, BaseModel


def _require_starlette():
    """Import Starlette lazily and return required symbols.

    Raises
    ------
    ImportError
        If Starlette is not installed.
    """
    try:
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import HTMLResponse, JSONResponse, StreamingResponse
    except ImportError as exc:
        raise ImportError(
            "Starlette backend requires the 'starlette' extra. Install it with: pip install protolink[starlette]"
        ) from exc

    return Starlette, Request, JSONResponse, HTMLResponse, StreamingResponse


def _require_grpc():
    """Import gRPC lazily and return the ``grpc`` module.

    Raises
    ------
    ImportError
        If grpcio is not installed.
    """
    try:
        import grpc
    except ImportError as exc:
        raise ImportError(
            "GRPCTransport requires the 'grpcio' package. Install it with: pip install protolink[grpc]"
        ) from exc

    return grpc
