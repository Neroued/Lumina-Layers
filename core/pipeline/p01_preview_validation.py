"""
P01 — Preview input validation and parameter normalization.
P01 — 预览输入验证与参数规范化。

从 generate_preview_cached 函数开头搬入的逻辑，包括：
- 输入参数校验（image_path, lut_path）
- LUT 路径解析（支持字符串路径和 Gradio File 对象）
- modeling_mode 规范化（None -> HIGH_FIDELITY）
- quantize_colors 范围 clamp（8-256）
"""

import time

from config import ModelingMode


def run(ctx: dict) -> dict:
    """Validate preview inputs and normalize parameters.
    验证预览输入参数并规范化。

    PipelineContext 输入键 / Input keys:
        - image_path (str): 输入图像路径
        - lut_path (str | object): LUT 文件路径或 Gradio File 对象
        - modeling_mode (ModelingMode | str | None): 建模模式
        - quantize_colors (int): K-Means 量化颜色数

    PipelineContext 输出键 / Output keys:
        - actual_lut_path (str): 解析后的实际 LUT 文件路径
        - modeling_mode (ModelingMode): 规范化后的建模模式
        - quantize_colors (int): clamp 到 [8, 256] 范围后的量化颜色数

    Raises:
        KeyError: 缺少必需的输入键时抛出
    """
    # ---- 读取必需输入 ----
    _t0 = time.perf_counter()
    image_path = ctx['image_path']
    lut_path = ctx['lut_path']
    modeling_mode = ctx.get('modeling_mode')
    quantize_colors = ctx.get('quantize_colors', 64)

    # ---- 输入校验 ----
    if image_path is None:
        ctx['error'] = "[ERROR] Please upload an image"
        return ctx
    if lut_path is None:
        ctx['error'] = "[WARNING] Please select or upload calibration file"
        return ctx

    # ---- LUT 路径解析 ----
    if isinstance(lut_path, str):
        actual_lut_path = lut_path
    elif hasattr(lut_path, 'name'):
        actual_lut_path = lut_path.name
    else:
        ctx['error'] = "[ERROR] Invalid LUT file format"
        return ctx

    # ---- modeling_mode 规范化 ----
    if modeling_mode is None or modeling_mode == "none":
        modeling_mode = ModelingMode.HIGH_FIDELITY
        print("[CONVERTER] Warning: modeling_mode was None, using default HIGH_FIDELITY")
    else:
        modeling_mode = ModelingMode(modeling_mode)

    # ---- quantize_colors clamp ----
    quantize_colors = max(8, min(256, quantize_colors))

    # ---- 写入输出 ----
    ctx['actual_lut_path'] = actual_lut_path
    ctx['modeling_mode'] = modeling_mode
    ctx['quantize_colors'] = quantize_colors
    _elapsed = time.perf_counter() - _t0
    ctx.setdefault('_preview_timings', {})['p01_s'] = _elapsed
    print(f"[P01] validation done: {_elapsed:.3f}s")
    return ctx
