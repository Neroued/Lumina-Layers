"""Common helpers for converter router modules."""

from __future__ import annotations

import pickle
from typing import NoReturn

import cv2
import numpy as np
from fastapi import HTTPException
from PIL import Image

from api.errors import to_http_exception
from api.file_bridge import ndarray_to_png_bytes, pil_to_png_bytes
from api.session_store import SessionStore
from api.structured_logging import bind_session_id, get_logger

EPHEMERAL_PREVIEW_TTL_SECONDS = 600
BATCH_DOWNLOAD_TTL_SECONDS = 3600
log = get_logger(__name__)

# Shared error tuples for except clauses across converter router modules.
# replace.py extends ROUTER_HANDLED_ERRORS with IndexError for array-index
# operations in region-detect / region-replace endpoints.
ROUTER_HANDLED_ERRORS = (
    ValueError,
    TypeError,
    KeyError,
    OSError,
    RuntimeError,
    pickle.UnpicklingError,
    cv2.error,
)
NON_FATAL_GLB_ERRORS = (
    ValueError,
    TypeError,
    OSError,
    RuntimeError,
    cv2.error,
)


def _handle_core_error(e: Exception, context: str) -> NoReturn:
    log.exception(
        "Converter operation failed",
        extra={
            "event": "converter_error",
            "error_type": type(e).__name__,
            "error_message": str(e),
            "context": context,
        },
    )
    raise to_http_exception(e, context)


def _require_session(store: SessionStore, session_id: str) -> dict:
    bind_session_id(session_id)
    data = store.get(session_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return data


def _require_preview_cache(session_data: dict) -> dict:
    cache = session_data.get("preview_cache")
    if cache is None:
        raise HTTPException(status_code=409, detail="No preview cache. Call POST /api/convert/preview first.")
    return cache


def _image_to_png_bytes(img: object) -> bytes:
    if isinstance(img, np.ndarray):
        return ndarray_to_png_bytes(img)
    if isinstance(img, Image.Image):
        return pil_to_png_bytes(img)
    raise TypeError(f"Unsupported image type: {type(img)}")
