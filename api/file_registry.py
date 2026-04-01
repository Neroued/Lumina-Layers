import os
import threading
import time
import uuid
from typing import Optional, Tuple


class FileRegistry:
    """文件注册表，管理生成文件的 UUID 映射。

    支持两种注册方式：
    1. register_path(session_id, path, filename) — 注册磁盘文件路径
    2. register_bytes(session_id, data, filename) — 注册内存字节流（保存为临时文件）
    """

    def __init__(self) -> None:
        self._registry: dict[str, dict] = {}
        # {file_id: {path, filename, session_id, created_at, expires_at, lifecycle}}
        self._lock = threading.Lock()

    def register_path(
        self,
        session_id: str,
        path: str,
        filename: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
    ) -> str:
        """注册磁盘文件，返回 file_id。"""
        file_id = str(uuid.uuid4())
        if filename is None:
            filename = os.path.basename(path)
        now = time.time()
        expires_at = (now + ttl_seconds) if ttl_seconds is not None else None
        with self._lock:
            self._registry[file_id] = {
                "path": path,
                "filename": filename,
                "session_id": session_id,
                "created_at": now,
                "expires_at": expires_at,
                "lifecycle": "ephemeral" if ttl_seconds is not None else "session_bound",
            }
        return file_id

    def register_bytes(
        self,
        session_id: str,
        data: bytes,
        filename: str,
        ttl_seconds: Optional[int] = None,
    ) -> str:
        """注册字节流（写入临时文件），返回 file_id。"""
        import tempfile
        from config import TEMP_DIR

        suffix = os.path.splitext(filename)[1] or ".bin"
        fd, path = tempfile.mkstemp(suffix=suffix, dir=TEMP_DIR)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        return self.register_path(
            session_id=session_id,
            path=path,
            filename=filename,
            ttl_seconds=ttl_seconds,
        )

    def resolve(self, file_id: str) -> Optional[Tuple[str, str]]:
        """解析 file_id，返回 (path, filename) 或 None。"""
        now = time.time()
        with self._lock:
            entry = self._registry.get(file_id)
            if entry is None:
                return None
            expires_at = entry.get("expires_at")
            if expires_at is not None and now >= expires_at:
                path = entry.get("path")
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                self._registry.pop(file_id, None)
                return None
        path = entry["path"]
        if not os.path.exists(path):
            return None
        return path, entry["filename"]

    def cleanup_expired(self) -> int:
        """删除所有已过期条目及磁盘文件，返回清理数量。"""
        now = time.time()
        removed = 0
        with self._lock:
            expired_ids = [
                fid
                for fid, entry in self._registry.items()
                if entry.get("expires_at") is not None and now >= entry["expires_at"]
            ]
            for fid in expired_ids:
                entry = self._registry.get(fid)
                if entry is None:
                    continue
                path = entry.get("path")
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                self._registry.pop(fid, None)
                removed += 1
        return removed

    def cleanup_session(self, session_id: str) -> int:
        """Clean up all registered files for a session and delete from disk.
        清理指定 session 的所有注册文件并删除磁盘文件，返回清理数量。
        """
        to_remove: list[tuple[str, str | None]] = []
        with self._lock:
            for fid, entry in self._registry.items():
                if entry["session_id"] == session_id:
                    to_remove.append((fid, entry.get("path")))
            for fid, path in to_remove:
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                self._registry.pop(fid, None)
        return len(to_remove)

    def cleanup_session_except(self, session_id: str, keep_file_ids: set[str] | None = None) -> int:
        """Delete all registered files for a session except those in *keep_file_ids*.
        删除指定 session 的注册文件（保留 keep_file_ids 中的），返回清理数量。
        """
        if keep_file_ids is None:
            keep_file_ids = set()
        to_remove: list[tuple[str, str | None]] = []
        with self._lock:
            for fid, entry in self._registry.items():
                if entry["session_id"] == session_id and fid not in keep_file_ids:
                    to_remove.append((fid, entry.get("path")))
            for fid, path in to_remove:
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                self._registry.pop(fid, None)
        return len(to_remove)

    def clear_all(self) -> int:
        """清除所有注册文件并删除磁盘文件，返回清理数量。"""
        with self._lock:
            count = 0
            for fid, entry in list(self._registry.items()):
                path = entry.get("path")
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                        count += 1
                    except OSError:
                        pass
                self._registry.pop(fid, None)
            return count
