"""Converter router cleanup module."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.dependencies import get_file_registry
from api.file_registry import FileRegistry
from api.schemas.converter import (
    CleanupSessionFilesRequest,
    CleanupSessionFilesResponse,
)

router = APIRouter()


@router.post("/cleanup-session-files")
def cleanup_session_files(
    body: CleanupSessionFilesRequest,
    registry: FileRegistry = Depends(get_file_registry),
) -> CleanupSessionFilesResponse:
    """Delete intermediate files for a session, preserving specified file IDs.
    删除 session 的中间文件（预览 PNG、GLB 等），保留指定的文件 ID（如已下载的 3MF）。
    """
    cleaned = registry.cleanup_session_except(
        body.session_id,
        keep_file_ids=set(body.keep_file_ids) if body.keep_file_ids else None,
    )
    return CleanupSessionFilesResponse(status="success", cleaned=cleaned)
