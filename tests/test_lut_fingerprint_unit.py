"""Unit tests for LUT fingerprint computation.
LUT 指纹计算单元测试。
"""

import hashlib
import os
import tempfile

import pytest

from utils.lut_manager import LUTManager


class TestComputeFingerprint:
    """Tests for LUTManager.compute_fingerprint."""

    def test_deterministic(self, tmp_path: str) -> None:
        """Same file content produces the same fingerprint."""
        path = os.path.join(str(tmp_path), "test.json")
        content = b'{"entries": [1, 2, 3]}'
        with open(path, "wb") as f:
            f.write(content)

        fp1 = LUTManager.compute_fingerprint(path)
        fp2 = LUTManager.compute_fingerprint(path)
        assert fp1 == fp2
        assert len(fp1) == 32  # First 32 hex chars of SHA-256

    def test_matches_hashlib(self, tmp_path: str) -> None:
        """Fingerprint matches hashlib SHA-256 (first 32 chars)."""
        path = os.path.join(str(tmp_path), "test.npy")
        content = os.urandom(1024)
        with open(path, "wb") as f:
            f.write(content)

        expected = hashlib.sha256(content).hexdigest()[:32]
        actual = LUTManager.compute_fingerprint(path)
        assert actual == expected

    def test_different_content_different_fingerprint(self, tmp_path: str) -> None:
        """Different file contents produce different fingerprints."""
        path_a = os.path.join(str(tmp_path), "a.json")
        path_b = os.path.join(str(tmp_path), "b.json")

        with open(path_a, "wb") as f:
            f.write(b"content A")
        with open(path_b, "wb") as f:
            f.write(b"content B")

        fp_a = LUTManager.compute_fingerprint(path_a)
        fp_b = LUTManager.compute_fingerprint(path_b)
        assert fp_a != fp_b

    def test_same_content_different_path(self, tmp_path: str) -> None:
        """Same content at different paths produces the same fingerprint."""
        content = b"identical content"

        path_a = os.path.join(str(tmp_path), "dir1", "lut.json")
        path_b = os.path.join(str(tmp_path), "dir2", "lut.json")

        os.makedirs(os.path.dirname(path_a), exist_ok=True)
        os.makedirs(os.path.dirname(path_b), exist_ok=True)

        with open(path_a, "wb") as f:
            f.write(content)
        with open(path_b, "wb") as f:
            f.write(content)

        assert LUTManager.compute_fingerprint(path_a) == LUTManager.compute_fingerprint(path_b)

    def test_large_file(self, tmp_path: str) -> None:
        """Handles files larger than the 8192-byte read chunk."""
        path = os.path.join(str(tmp_path), "large.npy")
        content = os.urandom(32768)  # 32 KB
        with open(path, "wb") as f:
            f.write(content)

        expected = hashlib.sha256(content).hexdigest()[:32]
        actual = LUTManager.compute_fingerprint(path)
        assert actual == expected

    def test_missing_file_raises(self) -> None:
        """Raises OSError for non-existent file."""
        with pytest.raises(OSError):
            LUTManager.compute_fingerprint("/nonexistent/path/lut.json")
