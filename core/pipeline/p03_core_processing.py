"""
P03 — Core image processing (quantization + LUT matching).
P03 — 核心图像处理（量化 + LUT 匹配）。

从 generate_preview_cached 函数搬入的逻辑，包括：
- 创建 LuminaImageProcessor 实例
- 调用 process_image 进行图像处理
- 提取处理结果（matched_rgb, material_matrix, mask_solid 等）
"""


import time
import numpy as np


def run(ctx: dict) -> dict:
    """Execute core image processing: quantization and LUT color matching.
    执行核心图像处理：量化与 LUT 颜色匹配。

    PipelineContext 输入键 / Input keys:
        - actual_lut_path (str): 解析后的实际 LUT 文件路径
        - color_mode (str): 颜色模式字符串
        - hue_weight (float): 色相权重
        - chroma_gate (float): 色度门限
        - image_path (str): 输入图像路径
        - target_width_mm (float): 目标宽度（毫米）
        - modeling_mode (ModelingMode): 建模模式
        - quantize_colors (int): 量化颜色数
        - auto_bg (bool): 是否自动移除背景
        - bg_tol (int): 背景容差
        - enable_cleanup (bool): 是否启用孤立像素清理

    PipelineContext 输出键 / Output keys:
        - matched_rgb (np.ndarray): LUT 匹配后的 RGB 图像 (H, W, 3)
        - material_matrix (np.ndarray): 材料矩阵 (H, W, N)
        - mask_solid (np.ndarray): 实体掩码 (H, W) bool
        - target_w (int): 目标宽度（像素）
        - target_h (int): 目标高度（像素）
        - debug_data (dict | None): 调试数据
        - quantized_image (np.ndarray | None): 量化后的图像

    Raises:
        KeyError: 缺少必需的输入键时抛出
    """
    from core.image_processing import LuminaImageProcessor
    _t0 = time.perf_counter()

    # ---- 读取必需输入 ----
    actual_lut_path = ctx['actual_lut_path']
    color_mode = ctx['color_mode']
    hue_weight = ctx.get('hue_weight', 0.0)
    chroma_gate = ctx.get('chroma_gate', 15.0)
    image_path = ctx['image_path']
    target_width_mm = ctx['target_width_mm']
    modeling_mode = ctx['modeling_mode']
    quantize_colors = ctx['quantize_colors']
    auto_bg = ctx['auto_bg']
    bg_tol = ctx['bg_tol']
    enable_cleanup = ctx.get('enable_cleanup', True)

    # ---- 核心处理 ----
    print("[P03][DEBUG-COMPARE] ========== PREVIEW PATH P03 START ==========")
    print(f"[P03][DEBUG-COMPARE] image_path={image_path}")
    print(f"[P03][DEBUG-COMPARE] lut_path={actual_lut_path}")
    print(f"[P03][DEBUG-COMPARE] color_mode={color_mode}, modeling_mode={modeling_mode}")
    print(f"[P03][DEBUG-COMPARE] quantize_colors={quantize_colors}, blur_kernel=0, smooth_sigma=10")
    print(f"[P03][DEBUG-COMPARE] auto_bg={auto_bg}, bg_tol={bg_tol}, enable_cleanup={enable_cleanup}")
    print(f"[P03][DEBUG-COMPARE] hue_weight={hue_weight}, chroma_gate={chroma_gate}")

    processor = LuminaImageProcessor(actual_lut_path, color_mode, hue_weight=hue_weight, chroma_gate=chroma_gate)
    processor.enable_cleanup = enable_cleanup

    print(f"[P03][DEBUG-COMPARE] LUT loaded: lut_rgb.shape={processor.lut_rgb.shape}, "
              f"ref_stacks.shape={processor.ref_stacks.shape}, layer_count={processor.layer_count}")
    print(f"[P03][DEBUG-COMPARE] LUT first 5 RGB: {processor.lut_rgb[:5].tolist()}")

    result = processor.process_image(
        image_path=image_path,
        target_width_mm=target_width_mm,
        modeling_mode=modeling_mode,
        quantize_colors=quantize_colors,
        auto_bg=auto_bg,
        bg_tol=bg_tol,
        blur_kernel=0,
        smooth_sigma=10
    )

    # ---- 提取结果 ----
    matched_rgb = result['matched_rgb']
    material_matrix = result['material_matrix']
    mask_solid = result['mask_solid']
    target_w, target_h = result['dimensions']

    # ---- 调试日志：打印匹配结果摘要 ----
    print(f"[P03][DEBUG-COMPARE] matched_rgb shape={matched_rgb.shape}, dtype={matched_rgb.dtype}")
    print(f"[P03][DEBUG-COMPARE] material_matrix shape={material_matrix.shape}, dtype={material_matrix.dtype}")
    print(f"[P03][DEBUG-COMPARE] mask_solid: True={np.sum(mask_solid)}, False={np.sum(~mask_solid)}")
    print(f"[P03][DEBUG-COMPARE] dimensions: {target_w}x{target_h}")

    # 打印 matched_rgb 唯一颜色
    solid_pixels = matched_rgb[mask_solid]
    if len(solid_pixels) > 0:
        unique_colors_preview = np.unique(solid_pixels.reshape(-1, 3), axis=0)
        print(f"[P03][DEBUG-COMPARE] Unique matched colors (solid): {len(unique_colors_preview)}")
        for i, c in enumerate(unique_colors_preview[:20]):
            hex_c = f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}"
            count = np.sum(np.all(solid_pixels == c, axis=-1))
            print(f"[P03][DEBUG-COMPARE]   color[{i}]: RGB({c[0]},{c[1]},{c[2]}) {hex_c} count={count}")

    # 打印 material_matrix 唯一值
    if mask_solid.any():
        mat_solid = material_matrix[mask_solid]
        if mat_solid.ndim == 2:
            top_layer = mat_solid[:, 0]
        else:
            top_layer = mat_solid
        unique_mats, mat_counts = np.unique(top_layer, return_counts=True)
        print(f"[P03][DEBUG-COMPARE] material_matrix top-layer unique values: {unique_mats.tolist()}")
        print(f"[P03][DEBUG-COMPARE] material_matrix top-layer counts: {mat_counts.tolist()}")

    # 打印几个固定采样点的像素值
    sample_coords = [(0, 0), (target_h//4, target_w//4), (target_h//2, target_w//2),
                     (target_h*3//4, target_w*3//4), (target_h-1, target_w-1)]
    for y, x in sample_coords:
        if 0 <= y < target_h and 0 <= x < target_w:
            rgb_val = matched_rgb[y, x]
            mat_val = material_matrix[y, x]
            solid = mask_solid[y, x]
            print(f"[P03][DEBUG-COMPARE] pixel({x},{y}): RGB=({rgb_val[0]},{rgb_val[1]},{rgb_val[2]}) "
                      f"mat={mat_val.tolist() if hasattr(mat_val, 'tolist') else mat_val} solid={solid}")

    # 打印 quantized_image 摘要
    q_img = result.get('quantized_image')
    if q_img is not None:
        q_unique = np.unique(q_img.reshape(-1, 3), axis=0)
        print(f"[P03][DEBUG-COMPARE] quantized_image unique colors: {len(q_unique)}")
        print(f"[P03][DEBUG-COMPARE] quantized_image first 5: {q_unique[:5].tolist()}")

    print("[P03][DEBUG-COMPARE] ========== PREVIEW PATH P03 END ==========")

    # ---- 写入输出 ----
    ctx['matched_rgb'] = matched_rgb
    ctx['material_matrix'] = material_matrix
    ctx['mask_solid'] = mask_solid
    ctx['target_w'] = target_w
    ctx['target_h'] = target_h
    ctx['debug_data'] = result.get('debug_data') if isinstance(result, dict) else None
    ctx['quantized_image'] = result.get('quantized_image')
    _elapsed = time.perf_counter() - _t0
    ctx.setdefault('_preview_timings', {})['p03_s'] = _elapsed
    print(f"[P03] core_processing done: {_elapsed:.3f}s")
    return ctx
