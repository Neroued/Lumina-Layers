"""Lumina Studio file logger.
Lumina Studio 文件日志模块。

Wraps sys.stdout with a _Tee so every print() call is:
  1. Forwarded to the original console stream (unchanged).
  2. Written to logs/lumina_YYYYMMDD_HHMMSS.log with a [HH:MM:SS.mmm] prefix.

Usage (call once at startup):
    from api.logger import setup_file_logging
    setup_file_logging()

Performance notes:
- Timestamp formatting occurs only when a line is actually written.
- File is opened with line-buffering (buffering=1); no explicit flush needed per-line.
- ANSI escape codes are stripped before writing to the log file.
"""

import io
import os
import re
import sys
import tempfile
import time
import threading
from datetime import datetime
from pathlib import Path

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mGKHF]")
_REPO_ROOT = Path(__file__).resolve().parents[1]
_logging_initialized = False
_tee_instance: "_Tee | None" = None


class _Tee(io.TextIOBase):
    """Tee stdout to both the original console stream and a timestamped log file.

    Each line written to the log file is prefixed with [HH:MM:SS.mmm].
    ANSI colour codes are stripped from log file output.
    Thread-safe via an internal lock.
    """

    def __init__(self, log_path: Path, console_stream=None) -> None:
        self._console = console_stream or sys.__stdout__
        self._file = open(log_path, "a", encoding="utf-8", buffering=1)
        self._at_line_start = True
        self._lock = threading.Lock()

    # ---- io.TextIOBase protocol ----

    @property
    def encoding(self) -> str:
        return getattr(self._console, "encoding", "utf-8")

    @property
    def errors(self) -> str:
        return getattr(self._console, "errors", "replace")

    def readable(self) -> bool:
        return False

    def writable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return False

    def fileno(self) -> int:
        # Delegate to console so uvicorn/subprocess pipes still work.
        try:
            return self._console.fileno()
        except (AttributeError, io.UnsupportedOperation):
            raise io.UnsupportedOperation("fileno")

    def isatty(self) -> bool:
        return False

    # ---- Core write / flush ----

    def write(self, s: str) -> int:
        if not s:
            return 0

        # Forward to console; fall back to encoded replacement on narrow terminals (e.g. GBK).
        try:
            self._console.write(s)
        except UnicodeEncodeError:
            enc = getattr(self._console, "encoding", None) or "utf-8"
            safe = s.encode(enc, errors="replace").decode(enc, errors="replace")
            try:
                self._console.write(safe)
            except Exception:
                pass
        try:
            self._console.flush()
        except Exception:
            pass

        # Strip ANSI codes and prefix each new line with [HH:MM:SS.mmm].
        clean = _ANSI_RE.sub("", s)
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]  # HH:MM:SS.mmm

        with self._lock:
            for part in clean.splitlines(keepends=True):
                if self._at_line_start:
                    self._file.write(f"[{ts}] ")
                self._file.write(part)
                self._at_line_start = part.endswith("\n")

        return len(s)

    def flush(self) -> None:
        try:
            self._console.flush()
        except Exception:
            pass
        try:
            self._file.flush()
        except Exception:
            pass

    def close(self) -> None:
        try:
            self._file.flush()
            self._file.close()
        except Exception:
            pass
        super().close()


def setup_file_logging(log_path=None) -> Path | None:
    """Install stdout tee to logs/lumina_YYYYMMDD_HHMMSS.log.

    Safe to call multiple times — only initializes once.
    If log_path is provided, appends to that existing file instead of
    creating a new timestamped file (used by worker processes).
    Returns the log file path, or None if already initialized.
    """
    global _logging_initialized, _tee_instance

    if _logging_initialized:
        return None

    tee: _Tee | None = None
    selected_path: Path | None = None
    for candidate_path in _resolve_log_candidates(Path(log_path) if log_path is not None else None):
        try:
            candidate_path.parent.mkdir(parents=True, exist_ok=True)
            tee = _Tee(candidate_path, console_stream=sys.stdout)
            selected_path = candidate_path
            break
        except OSError as exc:
            _emit_log_setup_warning(candidate_path, exc)

    if tee is None or selected_path is None:
        _logging_initialized = False
        _tee_instance = None
        return None

    sys.stdout = tee
    _tee_instance = tee
    _logging_initialized = True

    # First log line mirrors old lumina_*.log convention.
    print(f"[LOG] {selected_path}")
    return selected_path


def _resolve_log_candidates(explicit_path: Path | None) -> list[Path]:
    """Return candidate log paths in preference order.
    返回按优先级排序的日志路径候选列表。

    Args:
        explicit_path: Preferred path supplied by the caller. (调用方提供的优先路径)

    Returns:
        list[Path]: Candidate log paths. (候选日志路径列表)
    """

    filename = explicit_path.name if explicit_path is not None else f"lumina_{time.strftime('%Y%m%d_%H%M%S')}.log"
    candidates: list[Path] = []

    if explicit_path is not None:
        candidates.append(explicit_path)
    else:
        env_dir = os.environ.get("LUMINA_LOG_DIR")
        if env_dir:
            candidates.append(Path(env_dir) / filename)
        candidates.append(_REPO_ROOT / "logs" / filename)

    candidates.append(Path(tempfile.gettempdir()) / "lumina-logs" / filename)

    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            deduped.append(candidate)
    return deduped


def _emit_log_setup_warning(log_path: Path, exc: OSError) -> None:
    """Emit a stderr warning when one log target cannot be opened.
    当某个日志目标无法打开时向 stderr 输出警告。

    Args:
        log_path: Failing log path. (失败的日志路径)
        exc: Raised OS error. (触发的系统错误)
    """

    try:
        sys.__stderr__.write(
            f"[LOG][WARNING] File logging disabled for '{log_path}': {type(exc).__name__}: {exc}\n"
        )
        sys.__stderr__.flush()
    except Exception:
        pass
