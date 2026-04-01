"""Pytest global configuration for test stability and smoke tagging."""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import HealthCheck, settings

SMOKE_TEST_FILES = {
    "test_api_app_unit.py",
    "test_api_errors_unit.py",
    "test_converter_structure_contract_unit.py",
    "test_logging_exception_governance_unit.py",
    "test_heightmap_upload_unit.py",
    "test_converter_preview_unit.py",
}


def pytest_configure(config: pytest.Config) -> None:
    """Register deterministic Hypothesis defaults for CI and local runs."""
    settings.register_profile(
        "lumina",
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    settings.load_profile("lumina")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Mark selected fast, high-signal tests as smoke for PR gate runs."""
    smoke_marker = pytest.mark.smoke
    for item in items:
        filename = Path(str(item.fspath)).name
        if filename in SMOKE_TEST_FILES:
            item.add_marker(smoke_marker)
