"""
K-Means 颜色量化模块（K-Means Color Quantizer）

从 image_processing.py 的 _process_high_fidelity_mode Step 4 搬入。
包含预缩放优化、K-Means++ 初始化、后量化去噪。

K-Means color quantization with pre-scaling optimization.
Extracted from _process_high_fidelity_mode Step 4.
"""

import time
import numpy as np
import cv2
from scipy.spatial import KDTree

# 模块级 K-Means 缓存：key = md5(rgb)[:16]_{n_colors}_{seed}
_kmeans_cache: dict = {}
_KMEANS_CACHE_MAX = 4


def quantize_colors(rgb: np.ndarray, n_colors: int, seed: int = 42) -> np.ndarray:
    """K-Means 颜色量化（含预缩放优化、K-Means++ 初始化、后量化去噪）。
    K-Means color quantization with pre-scaling optimization and post-quantization cleanup.

    Args:
        rgb: (H, W, 3) uint8 RGB 图像数组
        n_colors: 量化目标颜色数
        seed: 随机种子，默认 42

    Returns:
        (H, W, 3) uint8 量化后的 RGB 图像数组
    """
    h, w = rgb.shape[:2]
    total_pixels = h * w

    # 缓存查找：用轻量指纹（shape + 采样像素 + 参数）避免全量 hash
    _sample = rgb[::max(1, rgb.shape[0]//32), ::max(1, rgb.shape[1]//32)].tobytes()
    _cache_key = f"{rgb.shape}_{len(_sample)}_{hash(_sample)}_{n_colors}_{seed}"
    if _cache_key in _kmeans_cache:
        print(f"[IMAGE_PROCESSOR] K-Means cache hit: {_cache_key}")
        return _kmeans_cache[_cache_key].copy()

    # 方案 3：预缩放优化
    # 如果像素数超过 50 万，先缩小做 K-Means，再映射回原图
    KMEANS_PIXEL_THRESHOLD = 500_000

    t0 = time.time()
    if total_pixels > KMEANS_PIXEL_THRESHOLD:
        # 计算缩放比例，目标 50 万像素
        scale_factor = np.sqrt(total_pixels / KMEANS_PIXEL_THRESHOLD)
        small_h = int(h / scale_factor)
        small_w = int(w / scale_factor)

        print(f"[IMAGE_PROCESSOR] 🚀 Pre-scaling optimization: {w}×{h} → {small_w}×{small_h} ({total_pixels:,} → {small_w*small_h:,} pixels)")

        # 缩小图片
        rgb_small = cv2.resize(rgb, (small_w, small_h), interpolation=cv2.INTER_AREA)

        # 在小图上做 K-Means（使用 K-Means++ 初始化）
        pixels_small = rgb_small.reshape(-1, 3).astype(np.float32)
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 0.5)
        flags = cv2.KMEANS_PP_CENTERS  # K-Means++ 初始化

        t_kmeans = time.time()
        print(f"[IMAGE_PROCESSOR] K-Means++ on downscaled image ({n_colors} colors)...")
        cv2.setRNGSeed(seed)  # 固定随机种子，确保 K-Means 结果可复现
        _, _, centers = cv2.kmeans(
            pixels_small, n_colors, None, criteria, 5, flags
        )
        print(f"[IMAGE_PROCESSOR] ⏱️ K-Means: {time.time() - t_kmeans:.2f}s")

        # 用得到的 centers 直接映射原图（不再迭代，只做最近邻查找）
        t_map = time.time()
        print(f"[IMAGE_PROCESSOR] Mapping centers to full image...")
        centers = centers.astype(np.float32)
        pixels_full = rgb.reshape(-1, 3).astype(np.float32)

        # 批量计算每个像素到所有 centers 的距离，找最近的
        # 使用 KDTree 加速
        centers_tree = KDTree(centers)
        _, labels = centers_tree.query(pixels_full)
        print(f"[IMAGE_PROCESSOR] ⏱️ KDTree query: {time.time() - t_map:.2f}s")

        centers = centers.astype(np.uint8)
        quantized_pixels = centers[labels]
        quantized_image = quantized_pixels.reshape(h, w, 3)

        print(f"[IMAGE_PROCESSOR] ✅ Pre-scaling optimization complete!")
    else:
        # 小图直接做 K-Means
        print(f"[IMAGE_PROCESSOR] K-Means++ quantization to {n_colors} colors...")
        pixels = rgb.reshape(-1, 3).astype(np.float32)
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 0.2)
        flags = cv2.KMEANS_PP_CENTERS

        cv2.setRNGSeed(seed)  # 固定随机种子，确保 K-Means 结果可复现
        _, labels, centers = cv2.kmeans(
            pixels, n_colors, None, criteria, 10, flags
        )

        centers = centers.astype(np.uint8)
        quantized_pixels = centers[labels.flatten()]
        quantized_image = quantized_pixels.reshape(h, w, 3)
    print(f"[IMAGE_PROCESSOR] ⏱️ Total quantization: {time.time() - t0:.2f}s")

    # [CRITICAL FIX] Post-Quantization Cleanup
    # Removes isolated "salt-and-pepper" noise pixels that survive quantization
    t0 = time.time()
    print(f"[IMAGE_PROCESSOR] Applying post-quantization cleanup (Denoising)...")
    quantized_image = cv2.medianBlur(quantized_image, 3)  # Kernel size 3 is optimal for detail preservation
    print(f"[IMAGE_PROCESSOR] ⏱️ Post-quantization cleanup: {time.time() - t0:.2f}s")

    print(f"[IMAGE_PROCESSOR] Quantization complete!")
    # 写入缓存（LRU 简化：超限时清空最旧条目）
    if len(_kmeans_cache) >= _KMEANS_CACHE_MAX:
        oldest = next(iter(_kmeans_cache))
        del _kmeans_cache[oldest]
    _kmeans_cache[_cache_key] = quantized_image.copy()
    return quantized_image
