"""Unit tests for LUT info and merge API endpoints.

Validates:
- GET /api/lut/{name}/info returns correct info or 404 (Requirement 6.7)
- POST /api/lut/merge returns 400 for invalid requests (Requirement 6.8)
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import app
from config import LUTMetadata

client: TestClient = TestClient(app)


# =========================================================================
# 1. GET /api/lut/{name}/info — success scenario (Requirement 6.7)
# =========================================================================


class TestLutInfoSuccess:
    """Verify the info endpoint returns correct mode and count."""

    @patch("api.routers.lut.LUTMerger.detect_color_mode", return_value=("8-Color", 2738))
    @patch("api.routers.lut.LUTManager.get_lut_path", return_value="/fake/path.npy")
    def test_info_returns_200_with_correct_fields(
        self, mock_path, mock_detect
    ) -> None:
        response = client.get("/api/lut/TestLUT/info")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "TestLUT"
        assert data["color_mode"] == "8-Color"
        assert data["color_count"] == 2738


# =========================================================================
# 2. GET /api/lut/{name}/info — 404 scenario (Requirement 6.7)
# =========================================================================


class TestLutInfoNotFound:
    """Verify the info endpoint returns 404 for non-existent LUT."""

    @patch("api.routers.lut.LUTManager.get_lut_path", return_value=None)
    def test_info_returns_404_when_lut_not_found(self, mock_path) -> None:
        response = client.get("/api/lut/NonExistent/info")
        assert response.status_code == 404
        assert "LUT not found" in response.json()["detail"]


# =========================================================================
# 3. POST /api/lut/merge — empty secondary list (Requirement 6.8)
# =========================================================================


class TestMergeEmptySecondary:
    """Verify merge returns 400 when secondary_names is empty."""

    def test_merge_empty_secondary_returns_400(self) -> None:
        payload = {
            "primary_name": "SomeLUT",
            "secondary_names": [],
            "dedup_threshold": 3.0,
        }
        response = client.post("/api/lut/merge", json=payload)
        assert response.status_code == 400
        assert "At least one secondary LUT" in response.json()["detail"]


# =========================================================================
# 4. POST /api/lut/merge — Primary mode not 6/8-Color (Requirement 6.8)
# =========================================================================


class TestMergePrimaryModeInvalid:
    """Verify merge returns 400 when primary LUT is not 6-Color or 8-Color."""

    @patch("api.routers.lut.LUTMerger.detect_color_mode", return_value=("4-Color", 1024))
    @patch("api.routers.lut.LUTManager.get_lut_path", return_value="/fake/primary.npy")
    def test_merge_4color_primary_returns_400(self, mock_path, mock_detect) -> None:
        payload = {
            "primary_name": "FourColorLUT",
            "secondary_names": ["SecondaryLUT"],
            "dedup_threshold": 3.0,
        }
        response = client.post("/api/lut/merge", json=payload)
        assert response.status_code == 400
        assert "Primary LUT must be 6-Color or 8-Color" in response.json()["detail"]


# =========================================================================
# 5. POST /api/lut/merge — compatibility failure (Requirement 6.8)
# =========================================================================


class TestMergeCompatibilityFailure:
    """Verify merge returns 400 when LUT modes are incompatible."""

    @patch(
        "api.routers.lut.LUTMerger.validate_compatibility",
        return_value=(False, "Incompatible color modes"),
    )
    @patch("api.routers.lut.LUTMerger.load_lut_with_stacks")
    @patch("api.routers.lut.LUTMerger.detect_color_mode")
    @patch("api.routers.lut.LUTManager.get_lut_path")
    def test_merge_incompatible_modes_returns_400(
        self, mock_path, mock_detect, mock_load, mock_validate
    ) -> None:
        import numpy as np

        # get_lut_path returns a path for both primary and secondary
        mock_path.side_effect = ["/fake/primary.npy", "/fake/secondary.npy"]
        # detect_color_mode: primary is 8-Color, secondary is 8-Color (incompatible)
        mock_detect.side_effect = [("8-Color", 2738), ("8-Color", 2738)]
        # load_lut_with_stacks returns dummy data
        dummy_rgb = np.zeros((10, 3), dtype=np.uint8)
        dummy_stacks = np.zeros((10, 5), dtype=np.int32)
        mock_load.return_value = (dummy_rgb, dummy_stacks)

        payload = {
            "primary_name": "PrimaryLUT",
            "secondary_names": ["SecondaryLUT"],
            "dedup_threshold": 3.0,
        }
        response = client.post("/api/lut/merge", json=payload)
        assert response.status_code == 400
        assert "Incompatible" in response.json()["detail"]


# =========================================================================
# 6. POST /api/lut/compare — success scenario
# =========================================================================


class TestCompareSuccess:
    """Verify compare returns 200 with same-recipe stats."""

    @patch("api.routers.lut.LUTMerger.validate_print_params", return_value=(True, []))
    @patch(
        "api.routers.lut.LUTMerger.compare_luts_by_recipe",
        return_value={
            "stats": {
                "matched_recipe_count": 2,
                "recipe_coverage_a": 1.0,
                "recipe_coverage_b": 1.0,
                "mean_delta_e00": 1.25,
                "median_delta_e00": 1.25,
                "p95_delta_e00": 1.8,
                "max_delta_e00": 2.0,
                "identical_rgb_count": 1,
                "recipes_only_in_a": 0,
                "recipes_only_in_b": 0,
            },
            "warnings": [],
            "worst_diffs": [
                {
                    "recipe": ["White", "Red", "Yellow", "Blue", "White"],
                    "rgb_a": [255, 0, 0],
                    "rgb_b": [254, 5, 0],
                    "hex_a": "#FF0000",
                    "hex_b": "#FE0500",
                    "delta_e00": 2.0,
                }
            ],
        },
    )
    @patch("api.routers.lut.LUTMerger.normalize_stacks_for_compare")
    @patch("api.routers.lut.LUTManager.load_lut_with_metadata")
    @patch("api.routers.lut.LUTMerger.load_lut_with_stacks")
    @patch("api.routers.lut.LUTMerger.detect_color_mode")
    @patch("api.routers.lut.LUTManager.get_lut_path")
    def test_compare_returns_200_with_stats(
        self,
        mock_path,
        mock_detect,
        mock_load,
        mock_load_meta,
        mock_normalize,
        mock_compare,
        mock_validate,
    ) -> None:
        import numpy as np

        dummy_rgb = np.array([[255, 0, 0], [0, 255, 0]], dtype=np.uint8)
        dummy_stacks = np.array([[0, 5, 3, 6, 0], [0, 1, 2, 3, 4]], dtype=np.int32)

        mock_path.side_effect = ["/fake/a.json", "/fake/b.json"]
        mock_detect.side_effect = [("4-Color", 1024), ("4-Color", 1024)]
        mock_load.side_effect = [(dummy_rgb, dummy_stacks), (dummy_rgb, dummy_stacks)]
        mock_load_meta.side_effect = [
            (dummy_rgb, dummy_stacks, LUTMetadata(color_mode="4-Color (RYBW)")),
            (dummy_rgb, dummy_stacks, LUTMetadata(color_mode="4-Color (RYBW)")),
        ]
        mock_normalize.side_effect = [dummy_stacks, dummy_stacks]

        payload = {
            "lut_a_name": "LUT_A",
            "lut_b_name": "LUT_B",
            "top_n": 5,
        }
        response = client.post("/api/lut/compare", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["lut_a_name"] == "LUT_A"
        assert data["lut_b_name"] == "LUT_B"
        assert data["stats"]["matched_recipe_count"] == 2
        assert data["stats"]["mean_delta_e00"] == 1.25
        assert data["worst_diffs"][0]["delta_e00"] == 2.0


# =========================================================================
# 7. POST /api/lut/compare — 404 scenario
# =========================================================================


class TestCompareNotFound:
    """Verify compare returns 404 when a LUT is missing."""

    @patch("api.routers.lut.LUTManager.get_lut_path", return_value=None)
    def test_compare_returns_404_when_lut_not_found(self, mock_path) -> None:
        payload = {
            "lut_a_name": "MissingLUT",
            "lut_b_name": "OtherLUT",
            "top_n": 5,
        }
        response = client.post("/api/lut/compare", json=payload)
        assert response.status_code == 404
        assert "LUT not found" in response.json()["detail"]


# =========================================================================
# 8. POST /api/lut/compare — no shared recipes warning
# =========================================================================


class TestCompareNoSharedRecipes:
    """Verify compare surfaces the empty shared-recipe warning."""

    @patch("api.routers.lut.LUTMerger.validate_print_params", return_value=(True, []))
    @patch(
        "api.routers.lut.LUTMerger.compare_luts_by_recipe",
        return_value={
            "stats": {
                "matched_recipe_count": 0,
                "recipe_coverage_a": 0.0,
                "recipe_coverage_b": 0.0,
                "mean_delta_e00": 0.0,
                "median_delta_e00": 0.0,
                "p95_delta_e00": 0.0,
                "max_delta_e00": 0.0,
                "identical_rgb_count": 0,
                "recipes_only_in_a": 10,
                "recipes_only_in_b": 12,
            },
            "warnings": [],
            "worst_diffs": [],
        },
    )
    @patch("api.routers.lut.LUTMerger.normalize_stacks_for_compare")
    @patch("api.routers.lut.LUTManager.load_lut_with_metadata")
    @patch("api.routers.lut.LUTMerger.load_lut_with_stacks")
    @patch("api.routers.lut.LUTMerger.detect_color_mode")
    @patch("api.routers.lut.LUTManager.get_lut_path")
    def test_compare_includes_no_shared_recipe_warning(
        self,
        mock_path,
        mock_detect,
        mock_load,
        mock_load_meta,
        mock_normalize,
        mock_compare,
        mock_validate,
    ) -> None:
        import numpy as np

        dummy_rgb = np.array([[255, 0, 0]], dtype=np.uint8)
        dummy_stacks = np.array([[0, 5, 3, 6, 0]], dtype=np.int32)

        mock_path.side_effect = ["/fake/a.json", "/fake/b.json"]
        mock_detect.side_effect = [("4-Color", 1024), ("4-Color", 1024)]
        mock_load.side_effect = [(dummy_rgb, dummy_stacks), (dummy_rgb, dummy_stacks)]
        mock_load_meta.side_effect = [
            (dummy_rgb, dummy_stacks, LUTMetadata(color_mode="4-Color (RYBW)")),
            (dummy_rgb, dummy_stacks, LUTMetadata(color_mode="4-Color (RYBW)")),
        ]
        mock_normalize.side_effect = [dummy_stacks, dummy_stacks]

        payload = {
            "lut_a_name": "LUT_A",
            "lut_b_name": "LUT_B",
            "top_n": 5,
        }
        response = client.post("/api/lut/compare", json=payload)

        assert response.status_code == 200
        warnings = response.json()["warnings"]
        assert any("No shared recipes found" in warning for warning in warnings)
