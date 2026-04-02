"""
LUT 颜色匹配模块（LUT Color Matcher）

从 image_processing.py 的 _process_high_fidelity_mode Step 5 搬入。
包含 CIELAB KDTree 查询和颜色编码映射逻辑。

LUT color matching using CIELAB KDTree query and color encoding mapping.
Extracted from _process_high_fidelity_mode Step 5.
"""

import time
import logging
import numpy as np
import cv2
from scipy.spatial import KDTree

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


def match_colors_to_lut(
    unique_colors: np.ndarray, lut_rgb: np.ndarray, lut_lab: np.ndarray, kdtree: "KDTree", hue_matcher=None
) -> np.ndarray:
    """LUT 颜色匹配：将唯一颜色匹配到 LUT 条目。
    Match unique colors to LUT entries using CIELAB KDTree or hue-aware matcher.

    Args:
        unique_colors: (N, 3) uint8 唯一颜色数组
        lut_rgb: (M, 3) uint8 LUT RGB 数组
        lut_lab: (M, 3) float64 LUT CIELAB 数组
        kdtree: scipy.spatial.KDTree 基于 CIELAB 的 KDTree
        hue_matcher: 可选的 HueAwareColorMatcher 实例

    Returns:
        (N,) int 数组，每个唯一颜色在 LUT 中的最佳匹配索引
    """
    t0 = time.time()
    if hue_matcher is not None:
        _log.info(f"[IMAGE_PROCESSOR] 🎨 Hue-aware matching enabled")
        unique_indices = hue_matcher.match_colors_batch(unique_colors, k=32)
    else:
        unique_lab = _rgb_to_lab(unique_colors)
        _, unique_indices = kdtree.query(unique_lab)
    _log.info(f"[IMAGE_PROCESSOR] ⏱️ LUT matching: {time.time() - t0:.2f}s")
    return unique_indices


def map_pixels_to_lut(
    quantized_image: np.ndarray,
    unique_colors: np.ndarray,
    unique_indices: np.ndarray,
    lut_rgb: np.ndarray,
    ref_stacks: np.ndarray,
    target_h: int,
    target_w: int,
    layer_count: int,
) -> tuple:
    """像素映射：将所有像素映射到 LUT。
    Map all pixels to LUT entries using optimized color encoding lookup.

    Args:
        quantized_image: (H, W, 3) uint8 量化后的图像
        unique_colors: (N, 3) uint8 唯一颜色数组
        unique_indices: (N,) int 每个唯一颜色对应的 LUT 索引
        lut_rgb: (M, 3) uint8 LUT RGB 数组
        ref_stacks: (M, L) int 材料堆叠配方数组
        target_h: 目标高度
        target_w: 目标宽度
        layer_count: 材料层数

    Returns:
        tuple: (matched_rgb, material_matrix)
            - matched_rgb: (H, W, 3) uint8 匹配后的 RGB 图像
            - material_matrix: (H, W, L) int 材料矩阵
    """
    # 🚀 优化：构建颜色编码查找表
    # 把 RGB 编码成单个整数：R*65536 + G*256 + B
    # 这样可以用 NumPy 向量化操作一次性完成映射
    t0 = time.time()
    _log.info(f"[IMAGE_PROCESSOR] Building color lookup table...")

    # 为每个 unique_color 计算编码
    unique_codes = (
        unique_colors[:, 0].astype(np.int32) * 65536
        + unique_colors[:, 1].astype(np.int32) * 256
        + unique_colors[:, 2].astype(np.int32)
    )

    # 构建编码 → 索引的映射数组（用于 np.searchsorted）
    sort_idx = np.argsort(unique_codes)
    sorted_codes = unique_codes[sort_idx]
    sorted_lut_indices = unique_indices[sort_idx]

    # 计算所有像素的颜色编码
    _log.info(f"[IMAGE_PROCESSOR] Mapping to full image (optimized)...")
    flat_quantized = quantized_image.reshape(-1, 3)
    pixel_codes = (
        flat_quantized[:, 0].astype(np.int32) * 65536
        + flat_quantized[:, 1].astype(np.int32) * 256
        + flat_quantized[:, 2].astype(np.int32)
    )

    # 使用 searchsorted 找到每个像素对应的 unique_color 索引
    insert_positions = np.searchsorted(sorted_codes, pixel_codes)
    # 获取对应的 LUT 索引
    lut_indices_for_pixels = sorted_lut_indices[insert_positions]

    # 一次性映射所有像素
    matched_rgb = lut_rgb[lut_indices_for_pixels].reshape(target_h, target_w, 3)
    material_matrix = ref_stacks[lut_indices_for_pixels].reshape(target_h, target_w, layer_count)
    _log.info(f"[IMAGE_PROCESSOR] ⏱️ Color mapping (optimized): {time.time() - t0:.2f}s")

    return matched_rgb, material_matrix
