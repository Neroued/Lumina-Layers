"""Unit tests for file-logger startup fallback behavior."""

from __future__ import annotations

import io
from pathlib import Path

import api.logger as logger_module


def test_setup_file_logging_does_not_crash_on_unwritable_log_target(monkeypatch) -> None:
    """Logger setup should degrade gracefully when the log file cannot be opened."""

    original_stdout = logger_module.sys.stdout
    original_stderr = logger_module.sys.__stderr__
    monkeypatch.setattr(logger_module, "_logging_initialized", False)
    monkeypatch.setattr(logger_module, "_tee_instance", None)

    def _raise_permission_error(log_path: Path, console_stream=None) -> object:
        raise PermissionError("access denied")

    monkeypatch.setattr(logger_module, "_Tee", _raise_permission_error)

    result = logger_module.setup_file_logging(log_path=Path("logs") / "blocked.log")

    assert result is None
    assert logger_module._logging_initialized is False
    assert logger_module._tee_instance is None
    assert logger_module.sys.stdout is original_stdout
    assert logger_module.sys.__stderr__ is original_stderr


def test_setup_file_logging_falls_back_to_secondary_path(monkeypatch) -> None:
    """Logger setup should try later candidates when the preferred one fails."""

    original_stdout = logger_module.sys.stdout
    monkeypatch.setattr(logger_module, "_logging_initialized", False)
    monkeypatch.setattr(logger_module, "_tee_instance", None)

    primary = Path("logs") / "primary.log"
    secondary = Path("fallback-logs") / "secondary.log"
    monkeypatch.setattr(
        logger_module,
        "_resolve_log_candidates",
        lambda explicit_path=None: [primary, secondary],
    )

    created_streams: list[tuple[Path, io.StringIO]] = []

    def _tee_factory(log_path: Path, console_stream=None) -> io.StringIO:
        if log_path == primary:
            raise PermissionError("primary blocked")
        stream = io.StringIO()
        created_streams.append((log_path, stream))
        return stream

    monkeypatch.setattr(logger_module, "_Tee", _tee_factory)

    result = logger_module.setup_file_logging()

    assert result == secondary
    assert logger_module._logging_initialized is True
    assert logger_module._tee_instance is created_streams[0][1]
    assert created_streams[0][0] == secondary
    logger_module.sys.stdout = original_stdout
    monkeypatch.setattr(logger_module, "_logging_initialized", False)
    monkeypatch.setattr(logger_module, "_tee_instance", None)
