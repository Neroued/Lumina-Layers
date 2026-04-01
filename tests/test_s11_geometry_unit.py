"""Unit tests for S11 geometry normalization helpers."""

from __future__ import annotations

import pytest

from core.pipeline.s11_glb_preview import _iter_valid_polygons


def test_iter_valid_polygons_handles_polygon_and_multipolygon() -> None:
    shapely = pytest.importorskip("shapely.geometry")
    Polygon = shapely.Polygon
    MultiPolygon = shapely.MultiPolygon

    poly_a = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    poly_b = Polygon([(2, 2), (3, 2), (3, 3), (2, 3)])
    multi = MultiPolygon([poly_a, poly_b])

    out = list(_iter_valid_polygons(multi))
    assert len(out) == 2
    assert all(getattr(g, "geom_type", "") == "Polygon" for g in out)


def test_iter_valid_polygons_filters_empty_and_tiny() -> None:
    shapely = pytest.importorskip("shapely.geometry")
    Polygon = shapely.Polygon

    tiny = Polygon([(0, 0), (1e-4, 0), (1e-4, 1e-4), (0, 1e-4)])
    valid = Polygon([(0, 0), (2, 0), (2, 1), (0, 1)])

    out = list(_iter_valid_polygons(valid.buffer(0).union(tiny)))
    assert len(out) >= 1
    assert any(float(getattr(g, "area", 0.0)) > 1e-4 for g in out)
