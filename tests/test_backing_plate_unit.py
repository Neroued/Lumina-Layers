"""
Lumina Studio - Backing Plate 单元测试 (Unit Tests)

验证 _build_color_contour_mesh 在边界情况下的行为：
- 全 False mask 返回 None
- 单像素 mask 生成有效 mesh
- L 形 mask 生成有效 mesh（含顶点、面、颜色）
- Z 范围正确

Requirements: 1.5
"""

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.converter import _build_color_contour_mesh

BACKING_PLATE_RGBA = np.array([245, 245, 245, 255], dtype=np.uint8)


# ============================================================================
# Test: 全 False mask 返回 None
# ============================================================================

class TestAllFalseMask:
    """Verify _build_color_contour_mesh returns None for all-False masks."""

    def test_all_false_3x3(self):
        """A 3x3 all-False mask should return None."""
        mask = np.zeros((3, 3), dtype=bool)
        result = _build_color_contour_mesh(
            mask=mask, height=3, total_layers=1, rgba=BACKING_PLATE_RGBA,
        )
        assert result is None

    def test_all_false_1x1(self):
        """A 1x1 all-False mask should return None."""
        mask = np.array([[False]])
        result = _build_color_contour_mesh(
            mask=mask, height=1, total_layers=1, rgba=BACKING_PLATE_RGBA,
        )
        assert result is None


# ============================================================================
# Test: 非空 mask 生成有效 mesh
# ============================================================================

class TestSinglePixelMask:
    """Verify single-pixel mask produces a valid mesh."""

    def test_single_pixel_returns_mesh(self):
        """A 1x1 True mask should produce a non-None mesh."""
        mask = np.array([[True]])
        mesh = _build_color_contour_mesh(
            mask=mask, height=1, total_layers=1, rgba=BACKING_PLATE_RGBA,
        )
        assert mesh is not None

    def test_single_pixel_has_geometry(self):
        """Mesh should have vertices and faces."""
        mask = np.array([[True]])
        mesh = _build_color_contour_mesh(
            mask=mask, height=1, total_layers=1, rgba=BACKING_PLATE_RGBA,
        )
        assert len(mesh.vertices) > 0
        assert len(mesh.faces) > 0

    def test_single_pixel_z_range(self):
        """Z range should be [0, total_layers]."""
        mask = np.array([[True]])
        mesh = _build_color_contour_mesh(
            mask=mask, height=1, total_layers=5, rgba=BACKING_PLATE_RGBA,
        )
        assert mesh is not None
        assert mesh.vertices[:, 2].min() == pytest.approx(0.0, abs=1e-9)
        assert mesh.vertices[:, 2].max() == pytest.approx(5.0, abs=1e-9)

    def test_single_pixel_face_color(self):
        """All face colors should match the given RGBA."""
        mask = np.array([[True]])
        mesh = _build_color_contour_mesh(
            mask=mask, height=1, total_layers=1, rgba=BACKING_PLATE_RGBA,
        )
        assert mesh is not None
        colors = mesh.visual.face_colors
        assert np.all(colors == BACKING_PLATE_RGBA)


# ============================================================================
# Test: 多像素 mask
# ============================================================================

class TestMultiPixelMask:
    """Verify multi-pixel masks produce valid meshes."""

    @staticmethod
    def _make_l_mask():
        """L-shaped mask: col=0 rows 0-2, col=1 row=2."""
        mask = np.zeros((3, 2), dtype=bool)
        mask[0, 0] = True
        mask[1, 0] = True
        mask[2, 0] = True
        mask[2, 1] = True
        return mask

    def test_l_shape_returns_mesh(self):
        """L-shaped mask should produce a non-None mesh."""
        mask = self._make_l_mask()
        mesh = _build_color_contour_mesh(
            mask=mask, height=3, total_layers=1, rgba=BACKING_PLATE_RGBA,
        )
        assert mesh is not None

    def test_l_shape_has_geometry(self):
        """Mesh should have vertices and faces."""
        mask = self._make_l_mask()
        mesh = _build_color_contour_mesh(
            mask=mask, height=3, total_layers=1, rgba=BACKING_PLATE_RGBA,
        )
        assert len(mesh.vertices) > 0
        assert len(mesh.faces) > 0

    def test_l_shape_z_range(self):
        """Z range should be [0, total_layers]."""
        mask = self._make_l_mask()
        mesh = _build_color_contour_mesh(
            mask=mask, height=3, total_layers=3, rgba=BACKING_PLATE_RGBA,
        )
        assert mesh is not None
        assert mesh.vertices[:, 2].min() == pytest.approx(0.0, abs=1e-9)
        assert mesh.vertices[:, 2].max() == pytest.approx(3.0, abs=1e-9)

    def test_l_shape_face_color(self):
        """All face colors should match the given RGBA."""
        mask = self._make_l_mask()
        mesh = _build_color_contour_mesh(
            mask=mask, height=3, total_layers=1, rgba=BACKING_PLATE_RGBA,
        )
        assert mesh is not None
        colors = mesh.visual.face_colors
        assert np.all(colors == BACKING_PLATE_RGBA)

    def test_full_mask_returns_mesh(self):
        """A full 5x5 mask should produce a valid mesh."""
        mask = np.ones((5, 5), dtype=bool)
        mesh = _build_color_contour_mesh(
            mask=mask, height=5, total_layers=10, rgba=BACKING_PLATE_RGBA,
        )
        assert mesh is not None
        assert len(mesh.faces) > 0
