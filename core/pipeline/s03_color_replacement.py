"""
S03 — Color replacement (global + region + matched_rgb override).
S03 — 颜色替换（全局替换 + 区域替换 + matched_rgb 覆盖）。

从 converter.py 搬入的颜色替换逻辑和辅助函数：
- _normalize_color_replacements_input: 统一替换输入格式
- _apply_region_replacement: 区域替换
- _apply_regions_to_raster_outputs: 按区域覆盖 raster 输出
- _compute_connected_region_mask_4n: 4 邻接连通域掩码计算
- matched_rgb_path 覆盖逻辑
"""

import time
import logging
from collections import deque
import numpy as np

from core.pipeline.pipeline_utils import _hex_to_rgb_tuple

_log = logging.getLogger(__name__)


def _normalize_color_replacements_input(color_replacements):
    """Normalize color replacement input to unified {hex: hex} dict.
    兼容 dict / replacement_regions(list) 两种替换输入，统一为 {hex: hex}。

    Args:
        color_replacements: dict 或 list 格式的颜色替换输入

    Returns:
        dict: 统一格式的 {src_hex: dst_hex} 映射
    """
    if not color_replacements:
        return {}

    if isinstance(color_replacements, dict):
        out = {}
        for src, dst in color_replacements.items():
            if not isinstance(src, str) or not isinstance(dst, str):
                continue
            s = src.strip().lower()
            d = dst.strip().lower()
            if s and d:
                out[s] = d
        return out

    if isinstance(color_replacements, list):
        out = {}
        for item in color_replacements:
            if not isinstance(item, dict):
                continue
            src = (
                (
                    item.get("matched")
                    or item.get("matched_hex")
                    or item.get("source")
                    or item.get("quantized")
                    or item.get("quantized_hex")
                    or item.get("selected_color")
                    or ""
                )
                .strip()
                .lower()
            )
            dst = (
                (item.get("replacement") or item.get("replacement_hex") or item.get("replacement_color") or "")
                .strip()
                .lower()
            )
            if src and dst:
                out[src] = dst
        return out

    return {}


def _apply_region_replacement(image_rgb, region_mask, replacement_rgb):
    """Apply replacement color only within region_mask coverage area.
    仅在 region_mask 覆盖区域应用替换色。

    Args:
        image_rgb (np.ndarray): (H, W, 3) uint8 RGB 图像
        region_mask (np.ndarray): (H, W) bool 区域掩码
        replacement_rgb: (R, G, B) 替换颜色

    Returns:
        np.ndarray: 替换后的 RGB 图像副本
    """
    out = image_rgb.copy()
    out[region_mask] = np.array(replacement_rgb, dtype=np.uint8)
    return out


def _apply_regions_to_raster_outputs(
    matched_rgb, material_matrix, mask_solid, replacement_regions, lut_index_resolver, ref_stacks
):
    """Apply region replacements in order to raster outputs (matched_rgb + material_matrix).
    按 regions 顺序覆盖 raster 输出（matched_rgb + material_matrix）。

    Args:
        matched_rgb (np.ndarray): (H, W, 3) uint8 匹配后的 RGB
        material_matrix (np.ndarray): (H, W, N) int 材料矩阵
        mask_solid (np.ndarray): (H, W) bool 实体掩码
        replacement_regions (list): 区域替换列表
        lut_index_resolver (callable): RGB → LUT 索引的解析函数
        ref_stacks (np.ndarray): LUT 参考堆叠数组

    Returns:
        tuple: (out_rgb, out_mat) 更新后的 RGB 和材料矩阵
    """
    out_rgb = matched_rgb.copy()
    out_mat = material_matrix.copy()

    for item in replacement_regions or []:
        region_mask = item.get("mask")
        replacement_hex = item.get("replacement")
        if region_mask is None or not replacement_hex:
            continue

        effective_mask = region_mask & mask_solid
        if not np.any(effective_mask):
            continue

        replacement_rgb = _hex_to_rgb_tuple(replacement_hex)
        out_rgb[effective_mask] = np.array(replacement_rgb, dtype=np.uint8)

        lut_idx = int(lut_index_resolver(replacement_rgb))
        out_mat[effective_mask] = ref_stacks[lut_idx]

    return out_rgb, out_mat


def _compute_connected_region_mask_4n(quantized_image, mask_solid, x, y):
    """Compute connected region mask using 4-neighbor connectivity from click point.
    基于 4 邻接计算点击像素所属连通域掩码。

    Args:
        quantized_image (np.ndarray): (H, W, 3) uint8 量化图像
        mask_solid (np.ndarray): (H, W) bool 实体掩码
        x (int): 点击 X 坐标
        y (int): 点击 Y 坐标

    Returns:
        np.ndarray: (H, W) bool 连通域掩码
    """
    h, w = quantized_image.shape[:2]
    if not (0 <= x < w and 0 <= y < h) or not mask_solid[y, x]:
        return np.zeros((h, w), dtype=bool)

    target = quantized_image[y, x]
    out = np.zeros((h, w), dtype=bool)
    q = deque([(x, y)])
    out[y, x] = True

    while q:
        cx, cy = q.popleft()
        for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
            if 0 <= nx < w and 0 <= ny < h and not out[ny, nx]:
                if mask_solid[ny, nx] and np.array_equal(quantized_image[ny, nx], target):
                    out[ny, nx] = True
                    q.append((nx, ny))

    return out


def run(ctx: dict) -> dict:
    """Apply color replacements: global, region, and matched_rgb override.
    应用颜色替换：全局替换、区域替换、matched_rgb 覆盖。

    PipelineContext 输入键 / Input keys:
        - matched_rgb (np.ndarray): (H, W, 3) uint8 匹配后的 RGB
        - material_matrix (np.ndarray): (H, W, N) int 材料矩阵
        - mask_solid (np.ndarray): (H, W) bool 实体掩码
        - processor (LuminaImageProcessor): 处理器实例（用于 KDTree 查询）
        - color_replacements (dict | None): 全局颜色替换映射
        - replacement_regions (list | None): 区域替换列表
        - matched_rgb_path (str | None): 预计算 matched_rgb .npy 文件路径

    PipelineContext 输出键 / Output keys:
        - matched_rgb (np.ndarray): 更新后的 RGB（如有替换）
        - material_matrix (np.ndarray): 更新后的材料矩阵（如有替换）
    """
    _t0 = time.perf_counter()

    matched_rgb = ctx["matched_rgb"]
    material_matrix = ctx["material_matrix"]
    mask_solid = ctx["mask_solid"]
    processor = ctx["processor"]
    color_replacements = ctx.get("color_replacements")
    replacement_regions = ctx.get("replacement_regions")
    matched_rgb_path = ctx.get("matched_rgb_path")

    print("[S03][DEBUG-COMPARE] ========== GENERATION PATH S03 START ==========")
    print(f"[S03][DEBUG-COMPARE] matched_rgb_path={matched_rgb_path}")
    print(f"[S03][DEBUG-COMPARE] color_replacements={color_replacements}")
    print(f"[S03][DEBUG-COMPARE] replacement_regions count={len(replacement_regions) if replacement_regions else 0}")

    # Log incoming matched_rgb summary before any override
    solid_before = matched_rgb[mask_solid]
    if len(solid_before) > 0:
        unique_before = np.unique(solid_before.reshape(-1, 3), axis=0)
        print(f"[S03][DEBUG-COMPARE] BEFORE override: {len(unique_before)} unique matched colors")
        for i, c in enumerate(unique_before[:10]):
            hex_c = f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}"
            count = np.sum(np.all(solid_before == c, axis=-1))
            print(f"[S03][DEBUG-COMPARE]   before[{i}]: RGB({c[0]},{c[1]},{c[2]}) {hex_c} count={count}")

    # ---- Override matched_rgb with pre-computed array if provided ----
    if matched_rgb_path is not None:
        try:
            override_rgb = np.load(matched_rgb_path)
            print(f"[S03][DEBUG-COMPARE] matched_rgb_path loaded: shape={override_rgb.shape}, dtype={override_rgb.dtype}")
            if override_rgb.shape != matched_rgb.shape:
                _log.warning(
                    f"[S03] matched_rgb_path shape {override_rgb.shape} "
                    f"does not match processed shape {matched_rgb.shape}, ignoring override"
                )
            else:
                # Detect pixels that differ between original and override
                diff_mask = np.any(matched_rgb != override_rgb, axis=-1) & mask_solid
                print(f"[S03][DEBUG-COMPARE] Override diff: {np.sum(diff_mask)} pixels differ "
                      f"out of {np.sum(mask_solid)} solid pixels "
                      f"({np.sum(diff_mask)/max(1,np.sum(mask_solid))*100:.2f}%)")
                if np.any(diff_mask):
                    diff_pixels = override_rgb[diff_mask]  # (N, 3)
                    unique_colors = np.unique(diff_pixels, axis=0)
                    for color in unique_colors:
                        color_mask = np.all(override_rgb == color, axis=-1) & diff_mask
                        repl_lab = processor._rgb_to_lab(color.reshape(1, 3))
                        _, lut_idx = processor.kdtree.query(repl_lab)
                        new_stacks = processor.ref_stacks[lut_idx[0]]
                        material_matrix[color_mask] = new_stacks
                    _log.info(
                        f"[S03] matched_rgb override applied: "
                        f"{np.sum(diff_mask)} pixels updated across {len(unique_colors)} colors"
                    )
                matched_rgb = override_rgb
        except (OSError, ValueError, TypeError) as e:
            _log.warning(
                f"[S03] Failed to load matched_rgb_path '{matched_rgb_path}': {e}, " f"using original processed result"
            )

    # ---- Apply global color replacements ----
    effective_color_replacements = _normalize_color_replacements_input(color_replacements)
    if replacement_regions:
        api_format_replacements = _normalize_color_replacements_input(replacement_regions)
        if api_format_replacements:
            effective_color_replacements.update(api_format_replacements)
            # Remove API-format items (no mask) from replacement_regions to avoid
            # _apply_regions_to_raster_outputs skipping them silently
            replacement_regions = [r for r in replacement_regions if r.get("mask") is not None]

    if effective_color_replacements:
        from core.color_replacement import ColorReplacementManager

        manager = ColorReplacementManager.from_dict(effective_color_replacements)
        old_rgb = matched_rgb.copy()
        matched_rgb = manager.apply_to_image(matched_rgb)
        _log.info(f"[S03] Applied {len(manager)} color replacements")

        # Update material_matrix: find the replacement color's LUT entry
        for orig_hex, repl_hex in effective_color_replacements.items():
            orig_rgb_tuple = ColorReplacementManager._hex_to_color(orig_hex)
            repl_rgb_tuple = ColorReplacementManager._hex_to_color(repl_hex)
            orig_mask = np.all(old_rgb == orig_rgb_tuple, axis=-1)
            if not np.any(orig_mask):
                continue
            repl_lab = processor._rgb_to_lab(np.array([repl_rgb_tuple], dtype=np.uint8))
            _, lut_idx = processor.kdtree.query(repl_lab)
            lut_idx = lut_idx[0]
            new_stacks = processor.ref_stacks[lut_idx]
            material_matrix[orig_mask] = new_stacks
            lut_color = processor.lut_rgb[lut_idx]
            _log.info(
                f"[S03] material_matrix: {orig_hex} -> LUT#{lut_idx} "
                f"rgb({lut_color[0]},{lut_color[1]},{lut_color[2]}) stacks={new_stacks}"
            )

    # ---- Apply region replacements in-order ----
    if replacement_regions:

        def _resolve_lut_index_for_rgb(replacement_rgb):
            repl_lab = processor._rgb_to_lab(np.array([replacement_rgb], dtype=np.uint8))
            _, lut_idx = processor.kdtree.query(repl_lab)
            return lut_idx[0]

        matched_rgb, material_matrix = _apply_regions_to_raster_outputs(
            matched_rgb,
            material_matrix,
            mask_solid,
            replacement_regions,
            _resolve_lut_index_for_rgb,
            processor.ref_stacks,
        )

    ctx["matched_rgb"] = matched_rgb
    ctx["material_matrix"] = material_matrix

    # Log final matched_rgb summary after all replacements
    solid_after = matched_rgb[mask_solid]
    if len(solid_after) > 0:
        unique_after = np.unique(solid_after.reshape(-1, 3), axis=0)
        print(f"[S03][DEBUG-COMPARE] AFTER all replacements: {len(unique_after)} unique matched colors")
        for i, c in enumerate(unique_after[:10]):
            hex_c = f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}"
            count = np.sum(np.all(solid_after == c, axis=-1))
            print(f"[S03][DEBUG-COMPARE]   after[{i}]: RGB({c[0]},{c[1]},{c[2]}) {hex_c} count={count}")

    # Log sample pixels after replacement
    target_h, target_w = matched_rgb.shape[:2]
    sample_coords = [(0, 0), (target_h//4, target_w//4), (target_h//2, target_w//2),
                     (target_h*3//4, target_w*3//4), (target_h-1, target_w-1)]
    for y, x in sample_coords:
        if 0 <= y < target_h and 0 <= x < target_w:
            rgb_val = matched_rgb[y, x]
            mat_val = material_matrix[y, x]
            solid = mask_solid[y, x]
            print(f"[S03][DEBUG-COMPARE] pixel({x},{y}): RGB=({rgb_val[0]},{rgb_val[1]},{rgb_val[2]}) "
                  f"mat={mat_val.tolist() if hasattr(mat_val, 'tolist') else mat_val} solid={solid}")

    print("[S03][DEBUG-COMPARE] ========== GENERATION PATH S03 END ==========")

    _elapsed = time.perf_counter() - _t0
    _hifi_timings = ctx.get("_hifi_timings", {})
    _hifi_timings["color_replace_s"] = _elapsed
    ctx["_hifi_timings"] = _hifi_timings
    _log.info(f"[S03] color_replace done: {_elapsed:.3f}s")
    return ctx
