"""
LUT 文件加载与格式检测模块（LUT Loader）

从 image_processing.py 的 _load_lut 方法提取。
支持 2色/4色/6色/8色/合并 LUT 格式检测和堆叠配方重建。

LUT file loading and format detection.
Extracted from LuminaImageProcessor._load_lut.
"""

import os
import logging
import numpy as np
import cv2
from scipy.spatial import KDTree

from config import PrinterConfig, ColorSystem, get_asset_path
from utils.lut_manager import LUTManager

_log = logging.getLogger(__name__)


def _rgb_to_lab(rgb_array: np.ndarray) -> np.ndarray:
    """将 RGB 数组转换为 CIELAB 空间。
    Convert RGB array to CIELAB color space.

    Args:
        rgb_array: numpy array, shape (N, 3) 或 (H, W, 3), dtype uint8

    Returns:
        numpy array, 同 shape, dtype float64, Lab 值
    """
    original_shape = rgb_array.shape
    if rgb_array.ndim == 2:
        rgb_3d = rgb_array.reshape(1, -1, 3).astype(np.uint8)
    else:
        rgb_3d = rgb_array.astype(np.uint8)
    bgr = cv2.cvtColor(rgb_3d, cv2.COLOR_RGB2BGR)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2Lab).astype(np.float64)
    if len(original_shape) == 2:
        return lab.reshape(original_shape)
    return lab


def load_lut(lut_path: str, color_mode: str) -> dict:
    """加载 LUT 文件并返回处理后的数据。
    Load and validate LUT file. Supports 2-Color, 4-Color, 6-Color, 8-Color, and Merged.

    统一通过 LUTManager.load_lut_with_metadata() 加载，支持 .npy/.json/.npz 三种格式。
    自动检测 LUT 类型并重建堆叠配方。

    Args:
        lut_path: LUT 文件路径 (.npy/.npz/.json)
        color_mode: 颜色模式字符串 (CMYW/RYBW/6-Color/8-Color/BW/Merged 等)

    Returns:
        dict: 包含以下键的字典
            - lut_rgb: (N, 3) uint8 LUT RGB 数组
            - lut_lab: (N, 3) float64 LUT CIELAB 数组
            - ref_stacks: (N, L) int 材料堆叠配方数组
            - kdtree: scipy.spatial.KDTree 基于 CIELAB 的 KDTree
            - layer_count: int 材料层数
    """
    layer_count = ColorSystem.get(color_mode).get("layer_count", PrinterConfig.COLOR_LAYERS)

    # ── 统一加载入口 ──────────────────────────────────────────────
    try:
        rgb, stacks, metadata = LUTManager.load_lut_with_metadata(lut_path)
    except (OSError, ValueError, TypeError, KeyError) as e:
        raise ValueError(f"LUT file corrupted: {e}")

    if rgb is None or len(rgb) == 0:
        raise ValueError(f"LUT file is empty or corrupted: {lut_path}")

    # Flatten to (N, 3) if loaded as grid (e.g. old .npy with shape (rows, cols, 3))
    measured_colors = rgb.reshape(-1, 3)
    total_colors = measured_colors.shape[0]

    # Determine if stacks data is usable (non-None, non-empty, has columns)
    has_stacks = (
        stacks is not None
        and isinstance(stacks, np.ndarray)
        and stacks.ndim == 2
        and stacks.shape[0] > 0
        and stacks.shape[1] > 0
    )

    _log.info(f"[IMAGE_PROCESSOR] Loading LUT with {total_colors} points (has_stacks={has_stacks})...")

    # ── .npz 合并 LUT：直接使用 rgb + stacks ─────────────────────
    if lut_path.endswith(".npz"):
        if has_stacks:
            lut_rgb = measured_colors
            ref_stacks = stacks
            if ref_stacks.ndim == 2:
                layer_count = int(ref_stacks.shape[1])
            lut_lab = _rgb_to_lab(lut_rgb)
            kdtree = KDTree(lut_lab)
            _log.info(f"Merged LUT loaded: {len(lut_rgb)} colors (.npz format, Lab KDTree)")
            return {
                "lut_rgb": lut_rgb,
                "lut_lab": lut_lab,
                "ref_stacks": ref_stacks,
                "kdtree": kdtree,
                "layer_count": layer_count,
            }
        else:
            raise ValueError(f"Merged LUT file missing stacks: {lut_path}")

    # ── 如果 stacks 有数据（来自 JSON recipe 或其他格式），直接使用 ──
    if has_stacks and stacks.shape[0] == total_colors:
        lut_rgb = measured_colors
        ref_stacks = stacks
        if ref_stacks.ndim == 2:
            layer_count = int(ref_stacks.shape[1])
        _log.info(f"LUT loaded: {len(lut_rgb)} colors (stacks from file, {layer_count} layers)")
        lut_lab = _rgb_to_lab(lut_rgb)
        kdtree = KDTree(lut_lab)
        return {
            "lut_rgb": lut_rgb,
            "lut_lab": lut_lab,
            "ref_stacks": ref_stacks,
            "kdtree": kdtree,
            "layer_count": layer_count,
        }

    # ── 回退：stacks 为空（旧 .npy 文件），从索引重建堆叠配方 ──────
    valid_rgb = []
    valid_stacks = []
    lut_rgb = None
    ref_stacks = None

    # Branch 0: 2-Color BW (32)
    if color_mode == "BW (Black & White)" or color_mode == "BW" or total_colors == 32:
        _log.info("[IMAGE_PROCESSOR] Detected 2-Color BW mode")

        # Generate all 32 combinations (2^5 = 32)
        for i in range(32):
            if i >= total_colors:
                break

            # Rebuild 2-base stacking (0..31)
            digits = []
            temp = i
            for _ in range(5):
                digits.append(temp % 2)
                temp //= 2
            stack = digits[::-1]  # [顶...底] format

            valid_rgb.append(measured_colors[i])
            valid_stacks.append(stack)

        lut_rgb = np.array(valid_rgb)
        ref_stacks = np.array(valid_stacks)
        if isinstance(ref_stacks, np.ndarray) and ref_stacks.ndim == 2:
            layer_count = int(ref_stacks.shape[1])

        _log.info(f"LUT loaded: {len(lut_rgb)} colors (2-Color BW mode)")

    # Branch 1: 8-Color Max (2738)
    elif "8-Color" in color_mode or total_colors == 2738:
        _log.info("[IMAGE_PROCESSOR] Detected 8-Color Max mode")

        # Load pre-generated 8-color stacks (预计算资产豁免，保持 np.load)
        stacks_path = get_asset_path("smart_8color_stacks.npy")

        smart_stacks = np.load(stacks_path).tolist()

        # 约定转换：smart_8color_stacks.npy 存储底到顶约定（stack[0]=背面），
        # 转换为顶到底约定（stack[0]=观赏面, stack[4]=背面），与 4 色模式统一
        smart_stacks = [tuple(reversed(s)) for s in smart_stacks]
        _log.info(
            "[IMAGE_PROCESSOR] Stacks converted from bottom-to-top to top-to-bottom convention (matching 4-color mode)."
        )

        if len(smart_stacks) != total_colors:
            _log.warning(f"Stacks count ({len(smart_stacks)}) != LUT count ({total_colors})")
            min_len = min(len(smart_stacks), total_colors)
            smart_stacks = smart_stacks[:min_len]
            measured_colors = measured_colors[:min_len]

        lut_rgb = measured_colors
        ref_stacks = np.array(smart_stacks)
        if isinstance(ref_stacks, np.ndarray) and ref_stacks.ndim == 2:
            layer_count = int(ref_stacks.shape[1])

        _log.info(f"LUT loaded: {len(lut_rgb)} colors (8-Color mode)")

    # Branch 2: 6-Color Smart 1296
    elif "6-Color" in color_mode or total_colors == 1296:
        _log.info("[IMAGE_PROCESSOR] Detected 6-Color Smart 1296 mode")

        from core.calibration import get_top_1296_colors

        smart_stacks = get_top_1296_colors()
        # 约定转换：get_top_1296_colors() 返回底到顶约定（stack[0]=背面），
        # 转换为顶到底约定（stack[0]=观赏面, stack[4]=背面），与 4 色模式统一
        smart_stacks = [tuple(reversed(s)) for s in smart_stacks]
        _log.info(
            "[IMAGE_PROCESSOR] Stacks converted from bottom-to-top to top-to-bottom convention (matching 4-color mode)."
        )

        if len(smart_stacks) != total_colors:
            _log.warning(f"Stacks count ({len(smart_stacks)}) != LUT count ({total_colors})")
            min_len = min(len(smart_stacks), total_colors)
            smart_stacks = smart_stacks[:min_len]
            measured_colors = measured_colors[:min_len]

        lut_rgb = measured_colors
        ref_stacks = np.array(smart_stacks)
        if isinstance(ref_stacks, np.ndarray) and ref_stacks.ndim == 2:
            layer_count = int(ref_stacks.shape[1])

        _log.info(f"LUT loaded: {len(lut_rgb)} colors (6-Color mode)")

    # Branch 3: 5-Color Extended (2468)
    elif "5-Color Extended" in color_mode or total_colors == 2468:
        _log.info("[IMAGE_PROCESSOR] Detected 5-Color Extended (2468) mode")

        # Fallback: generate stacks from index
        # First 1024: base 5-layer (4^5 combinations), pad to 6 layers
        # Next 1444: extended 6-layer from select_extended_1444_colors()
        _ref_stacks = []

        # Generate base 1024 stacks (5-layer, pad with air(-1) at viewing end)
        # Air at index 0 offsets the base viewing surface by 1 Z level
        # so it doesn't share the same Z as extended viewing surfaces.
        for i in range(min(1024, total_colors)):
            digits = []
            temp = i
            for _ in range(5):
                digits.append(temp % 4)
                temp //= 4
            stack = (-1,) + tuple(reversed(digits))
            _ref_stacks.append(stack)

        # Generate extended 1444 stacks using select_extended_1444_colors
        if total_colors > 1024:
            from core.calibration import select_extended_1444_colors

            base_5layer = [tuple(reversed([i // 4**j % 4 for j in range(5)])) for i in range(1024)]
            extended_stacks = select_extended_1444_colors(base_5layer)

            # Add extended stacks (already in correct 6-layer format)
            for i in range(min(len(extended_stacks), total_colors - 1024)):
                _ref_stacks.append(extended_stacks[i])

        lut_rgb = measured_colors
        ref_stacks = np.array(_ref_stacks)
        if isinstance(ref_stacks, np.ndarray) and ref_stacks.ndim == 2:
            layer_count = int(ref_stacks.shape[1])

        _log.info(f"LUT loaded: {len(lut_rgb)} colors (5-Color Extended)")

    # Branch 4: Merged LUT (non-standard size or "Merged" mode)
    elif color_mode == "Merged" or total_colors not in (32, 1024, 1296, 2468, 2738):
        _log.info(f"[IMAGE_PROCESSOR] Detected non-standard LUT size ({total_colors}), trying companion .npz...")

        # 尝试查找同名 .npz 文件
        npz_path = lut_path.rsplit(".", 1)[0] + ".npz"
        if os.path.exists(npz_path):
            try:
                npz_rgb, npz_stacks, npz_meta = LUTManager.load_lut_with_metadata(npz_path)
                lut_rgb = npz_rgb
                ref_stacks = npz_stacks
                if isinstance(ref_stacks, np.ndarray) and ref_stacks.ndim == 2:
                    layer_count = int(ref_stacks.shape[1])
                lut_lab = _rgb_to_lab(lut_rgb)
                kdtree = KDTree(lut_lab)
                _log.info(f"Merged LUT loaded from companion .npz: {len(lut_rgb)} colors (Lab KDTree)")
                return {
                    "lut_rgb": lut_rgb,
                    "lut_lab": lut_lab,
                    "ref_stacks": ref_stacks,
                    "kdtree": kdtree,
                    "layer_count": layer_count,
                }
            except (OSError, ValueError, TypeError, KeyError) as e:
                _log.warning(f"Failed to load companion .npz: {e}")

        # 无 .npz 伴随文件，使用 RGB 数据但无堆叠信息
        # 生成占位堆叠（全0）
        _log.info(f"No companion .npz found, using placeholder stacks")
        lut_rgb = measured_colors
        ref_stacks = np.zeros((total_colors, layer_count), dtype=np.int32)

        _log.info(f"LUT loaded: {len(lut_rgb)} colors (Merged mode, placeholder stacks)")

    # Branch 5: 4-Color Standard (1024)
    else:
        _log.info("[IMAGE_PROCESSOR] Detected 4-Color Standard mode")

        # Keep original outlier filtering logic (Blue Check)
        base_blue = np.array([30, 100, 200])
        dropped = 0

        for i in range(1024):
            if i >= total_colors:
                break

            # Rebuild 4-base stacking (0..1023)
            digits = []
            temp = i
            for _ in range(5):
                digits.append(temp % 4)
                temp //= 4
            stack = digits[::-1]

            real_rgb = measured_colors[i]

            # Filter outliers: close to blue but doesn't contain blue
            dist = np.linalg.norm(real_rgb - base_blue)
            if dist < 60 and 3 not in stack:  # 3 is Blue in RYBW/CMYW
                dropped += 1
                continue

            valid_rgb.append(real_rgb)
            valid_stacks.append(stack)

        lut_rgb = np.array(valid_rgb)
        ref_stacks = np.array(valid_stacks)
        if isinstance(ref_stacks, np.ndarray) and ref_stacks.ndim == 2:
            layer_count = int(ref_stacks.shape[1])

        _log.info(f"LUT loaded: {len(lut_rgb)} colors (filtered {dropped} outliers)")

    # Build KD-Tree in CIELAB space for perceptually accurate color matching
    lut_lab = _rgb_to_lab(lut_rgb)
    kdtree = KDTree(lut_lab)

    return {
        "lut_rgb": lut_rgb,
        "lut_lab": lut_lab,
        "ref_stacks": ref_stacks,
        "kdtree": kdtree,
        "layer_count": layer_count,
    }
