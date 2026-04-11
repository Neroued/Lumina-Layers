"""
Lumina Studio - Image Processing Core (图像处理核心)

Handles image loading, preprocessing, color quantization and matching.
处理图像加载、预处理、色彩量化和匹配。主要逻辑已抽取到 core/pipeline/processing_ops/ 子模块。
"""

import os
import logging
import numpy as np
import cv2
from PIL import Image

from config import PrinterConfig, ModelingMode, ColorSystem

# HEIC/HEIF support (optional dependency)
try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

log = logging.getLogger(__name__)

# ========== processing_ops 子模块导入 ==========
from core.pipeline.processing_ops.lut_loader import load_lut
from core.pipeline.processing_ops.bilateral_filter import apply_bilateral_filter
from core.pipeline.processing_ops.median_filter import apply_median_filter
from core.pipeline.processing_ops.kmeans_quantizer import quantize_colors as kmeans_quantize
from core.pipeline.processing_ops.lut_color_matcher import match_colors_to_lut, map_pixels_to_lut
from core.pipeline.processing_ops.svg_rasterizer import rasterize_svg
from core.pipeline.processing_ops.wireframe_extractor import extract_wireframe_mask


class LuminaImageProcessor:
    """
    Image processor class — 图像处理核心类。

    主要逻辑已抽取到 processing_ops 子模块。
    Handles LUT loading, image processing, and color matching.
    """

    @staticmethod
    def _rgb_to_lab(rgb_array):
        """将 RGB 数组转换为 CIELAB 色彩空间，用于色差计算。

        Args:
            rgb_array: numpy array, shape (N, 3) 或 (H, W, 3), dtype uint8

        Returns:
            numpy array, 同输入 shape, dtype float64, Lab 色彩空间
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

    def __init__(self, lut_path, color_mode, hue_weight: float = 0.0, chroma_gate: float = 15.0):
        """Initialize image processor.
        加载 LUT 文件并初始化图像处理器。
        Args:
            lut_path: LUT 文件路径 (.npy/.npz/.json)
            color_mode: 颜色模式字符串 (CMYW/RYBW/6-Color)
            hue_weight: 色相权重 (0.0-1.0)
            chroma_gate: 色度门限 (0-50)
        """
        self.lut_path = lut_path
        self.color_mode = color_mode
        self.hue_weight = float(hue_weight)
        self.chroma_gate = float(chroma_gate)
        self.hue_matcher = None
        self.enable_cleanup = True
        lut_data = load_lut(lut_path, color_mode)
        self.lut_rgb = lut_data["lut_rgb"]
        self.lut_lab = lut_data["lut_lab"]
        self.ref_stacks = lut_data["ref_stacks"]
        self.kdtree = lut_data["kdtree"]
        self.layer_count = lut_data["layer_count"]
        self._init_hue_matcher()

    def _init_hue_matcher(self):
        """Initialize hue-aware color matcher if hue_weight > 0.
        如果 hue_weight > 0，则初始化色相感知的颜色匹配器。
        """
        if self.hue_weight > 0:
            from core.color_matching_hue_aware import HueAwareColorMatcher

            self.hue_matcher = HueAwareColorMatcher(
                self.lut_rgb, self.lut_lab, hue_weight=self.hue_weight, chroma_gate=self.chroma_gate
            )

    def _load_svg(self, svg_path, target_width_mm, pixels_per_mm: float = 20.0):
        """Rasterize SVG input through shared svg_rasterizer helper.
        通过 svg_rasterizer 辅助函数栅格化 SVG 输入。
        """
        return rasterize_svg(svg_path, target_width_mm, pixels_per_mm)

    def _extract_wireframe_mask(self, rgb_arr, target_w, pixel_scale, wire_width_mm=0.6):
        """Extract wireframe mask through shared wireframe_extractor helper.
        通过 wireframe_extractor 辅助函数提取线框蒙版。
        """
        return extract_wireframe_mask(rgb_arr, pixel_scale, wire_width_mm)

    def process_image(
        self,
        image_path,
        target_width_mm,
        modeling_mode,
        quantize_colors,
        auto_bg,
        bg_tol,
        blur_kernel=0,
        smooth_sigma=10,
    ):
        """Main image processing method.
        主要图像处理方法。

        Returns:
            dict with matched_rgb, material_matrix, mask_solid, dimensions,
                 pixel_scale, mode_info, quantized_image, debug_data
        """
        log.info(
            f"[IMAGE_PROCESSOR] Mode: {modeling_mode.get_display_name()}, blur_kernel={blur_kernel}, smooth_sigma={smooth_sigma}"
        )
        img, target_w, target_h, px_scale, blur_kernel, smooth_sigma = self._load_and_resize_image(
            image_path, target_width_mm, modeling_mode, blur_kernel, smooth_sigma
        )
        rgb_arr, mask_transparent = self._extract_rgba_arrays(img)
        matched_rgb, material_matrix, bg_ref, debug_data = self._run_mode_pipeline(
            modeling_mode, rgb_arr, target_h, target_w, quantize_colors, blur_kernel, smooth_sigma
        )
        matched_rgb, material_matrix = self._apply_cleanup(modeling_mode, matched_rgb, material_matrix)
        mask_transparent = self._merge_auto_bg_mask(auto_bg, bg_ref, bg_tol, mask_transparent)
        material_matrix[mask_transparent] = -1
        # result keys contract: 'matched_rgb', 'material_matrix', 'mask_solid', 'dimensions', 'pixel_scale', 'mode_info', 'quantized_image'
        result = self._build_process_result(
            matched_rgb,
            material_matrix,
            mask_transparent,
            target_w,
            target_h,
            px_scale,
            modeling_mode,
            rgb_arr,
            debug_data,
        )
        return result

    def _extract_rgba_arrays(self, img):
        """Extract RGB data and transparent mask from RGBA image.
        从 RGBA 图像中提取 RGB 数据和透明蒙版。
        """
        img_arr = np.array(img)
        rgb_arr, alpha_arr = img_arr[:, :, :3], img_arr[:, :, 3]
        mask_transparent = alpha_arr < 10
        log.info(f"[IMAGE_PROCESSOR] Found {np.sum(mask_transparent)} transparent pixels (alpha<10)")
        return rgb_arr, mask_transparent

    def _run_mode_pipeline(
        self, modeling_mode, rgb_arr, target_h, target_w, quantize_colors, blur_kernel, smooth_sigma
    ):
        """Run processing pipeline for current modeling mode.
        运行当前建模模式的处理流程。
        """
        if modeling_mode == ModelingMode.HIGH_FIDELITY:
            return self._process_high_fidelity_mode(
                rgb_arr, target_h, target_w, quantize_colors, blur_kernel, smooth_sigma
            )
        matched_rgb, material_matrix, bg_ref = self._process_pixel_mode(rgb_arr, target_h, target_w)
        return matched_rgb, material_matrix, bg_ref, None

    def _merge_auto_bg_mask(self, auto_bg, bg_ref, bg_tol, mask_transparent):
        """Merge auto background mask when enabled.
        如果启用自动背景蒙版，则合并蒙版。
        """
        if not auto_bg:
            return mask_transparent
        bg_mask = np.sum(np.abs(bg_ref - bg_ref[0, 0]), axis=-1) < bg_tol
        return np.logical_or(mask_transparent, bg_mask)

    def _build_process_result(
        self,
        matched_rgb,
        material_matrix,
        mask_transparent,
        target_w,
        target_h,
        px_scale,
        modeling_mode,
        rgb_arr,
        debug_data,
    ):
        """Build process_image result payload.
        构建 process_image 方法的返回值。
        """
        result = {
            "matched_rgb": matched_rgb,
            "material_matrix": material_matrix,
            "mask_solid": ~mask_transparent,
            "dimensions": (target_w, target_h),
            "pixel_scale": px_scale,
            "mode_info": {"mode": modeling_mode},
            "quantized_image": debug_data["quantized_image"] if debug_data else rgb_arr.copy(),
        }
        if debug_data is not None:
            result["debug_data"] = debug_data
        return result

    def _apply_cleanup(self, modeling_mode, matched_rgb, material_matrix):
        """Apply isolated pixel cleanup if enabled.
        如果启用，则应用孤立像素清理。
        """
        if modeling_mode == ModelingMode.HIGH_FIDELITY and self.enable_cleanup:
            try:
                from core.isolated_pixel_cleanup import cleanup_isolated_pixels

                return cleanup_isolated_pixels(material_matrix, matched_rgb, self.lut_rgb, self.ref_stacks)
            except ImportError:
                log.info("[IMAGE_PROCESSOR] isolated_pixel_cleanup module not found, skipping")
        return matched_rgb, material_matrix

    def _load_and_resize_image(self, image_path, target_width_mm, modeling_mode, blur_kernel, smooth_sigma):
        """加载图像并缩放到目标尺寸，对 SVG 自动禁用滤波器。
        Load image and resize to target dimensions. Returns (img, w, h, scale, blur, sigma).
        """
        SVG_PIXELS_PER_MM = 10.0
        is_svg = image_path.lower().endswith(".svg")
        if is_svg:
            log.info("[IMAGE_PROCESSOR] SVG detected - Engaging Ultra-High-Fidelity Vector Mode")
            img = Image.fromarray(self._load_svg(image_path, target_width_mm, pixels_per_mm=SVG_PIXELS_PER_MM))
            blur_kernel, smooth_sigma = 0, 0
            log.info("[IMAGE_PROCESSOR] SVG Mode: Filters disabled (Vector source is clean)")
            target_w, target_h, pixel_scale = img.size[0], img.size[1], 1.0 / SVG_PIXELS_PER_MM
        else:
            img = Image.open(image_path).convert("RGBA")
            self._log_image_info(img, image_path)
            target_w, target_h, pixel_scale = self._calc_dimensions(img, target_width_mm, modeling_mode)
        log.info(f"[IMAGE_PROCESSOR] Using NEAREST interpolation (no anti-aliasing)")
        img = img.resize((target_w, target_h), Image.Resampling.NEAREST)
        return img, target_w, target_h, pixel_scale, blur_kernel, smooth_sigma

    def _log_image_info(self, img, image_path):
        """Log image properties for debugging (reuses already-loaded image).
        记录图像属性信息，用于调试，复用已加载的图像以避免重复 I/O。

        Args:
            img (PIL.Image.Image): Already loaded RGBA image. (已加载的 RGBA 图像)
            image_path (str): Path for display only. (仅用于显示的路径)
        """
        log.info(f"[IMAGE_PROCESSOR] Original image: {image_path}, mode: {img.mode}, size: {img.size}")
        has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
        log.info(f"[IMAGE_PROCESSOR] Has alpha channel: {has_alpha}")
        if has_alpha:
            alpha_img = img if img.mode == "RGBA" else img.convert("RGBA")
            alpha_data = np.array(alpha_img)[:, :, 3]
            log.info(
                f"[IMAGE_PROCESSOR] Alpha stats: min={alpha_data.min()}, max={alpha_data.max()}, "
                f"mean={alpha_data.mean():.1f}, transparent(alpha<10): {np.sum(alpha_data < 10)}"
            )

    def _calc_dimensions(self, img, target_width_mm, modeling_mode):
        """计算目标尺寸和像素比例。 Calculate target dimensions and pixel scale."""
        if modeling_mode == ModelingMode.HIGH_FIDELITY:
            PIXELS_PER_MM = 10
            # Round instead of truncating so crop-derived puzzle pieces don't lose
            # a pixel from float epsilon (e.g. 17.799999999999997mm -> 177px).
            target_w = int(round(target_width_mm * PIXELS_PER_MM))
            pixel_scale = 1.0 / PIXELS_PER_MM
            log.info(f"[IMAGE_PROCESSOR] High-res mode: {PIXELS_PER_MM} px/mm")
        else:
            target_w = int(round(target_width_mm / PrinterConfig.NOZZLE_WIDTH))
            pixel_scale = PrinterConfig.NOZZLE_WIDTH
            log.info(f"[IMAGE_PROCESSOR] Pixel mode: {1.0/pixel_scale:.2f} px/mm")
        target_w = max(1, target_w)
        target_h = max(1, int(round(target_w * img.height / img.width)))
        log.info(
            f"[IMAGE_PROCESSOR] Target: {target_w}x{target_h}px ({target_w*pixel_scale:.1f}x{target_h*pixel_scale:.1f}mm)"
        )
        return target_w, target_h, pixel_scale

    def _process_high_fidelity_mode(self, rgb_arr, target_h, target_w, quantize_colors, blur_kernel, smooth_sigma):
        """高保真模式处理流程：bilateral -> median -> kmeans -> lut match。
        High-fidelity mode image processing with filtering, quantization and LUT matching.

        Returns:
            tuple: (matched_rgb, material_matrix, quantized_image, debug_data)
        """
        import time

        total_start = time.time()
        quantized_image, unique_colors, rgb_processed = self._prepare_high_fidelity_images(
            rgb_arr, quantize_colors, blur_kernel, smooth_sigma
        )
        unique_indices = self._match_high_fidelity_unique_colors(unique_colors)
        matched_rgb, material_matrix = map_pixels_to_lut(
            quantized_image,
            unique_colors,
            unique_indices,
            self.lut_rgb,
            self.ref_stacks,
            target_h,
            target_w,
            self.layer_count,
        )
        log.info(f"[IMAGE_PROCESSOR] Total processing time: {time.time() - total_start:.2f}s")
        debug_data = self._build_high_fidelity_debug_data(
            quantized_image, unique_colors, rgb_processed, blur_kernel, smooth_sigma
        )
        return matched_rgb, material_matrix, quantized_image, debug_data

    def _prepare_high_fidelity_images(self, rgb_arr, quantize_colors, blur_kernel, smooth_sigma):
        """Run filtering + quantization and compute unique colors."""
        import time

        log.info(f"[IMAGE_PROCESSOR] Starting edge-preserving processing...")
        rgb_processed = apply_bilateral_filter(rgb_arr, smooth_sigma)
        rgb_processed = apply_median_filter(rgb_processed, blur_kernel)
        log.info(f"[IMAGE_PROCESSOR] Skipping sharpening to reduce noise...")
        quantized_image = kmeans_quantize(rgb_processed, quantize_colors)
        t0 = time.time()
        unique_colors = np.unique(quantized_image.reshape(-1, 3), axis=0)
        log.info(f"[IMAGE_PROCESSOR] Found {len(unique_colors)} unique colors ({time.time() - t0:.2f}s)")
        return quantized_image, unique_colors, rgb_processed

    def _match_high_fidelity_unique_colors(self, unique_colors):
        """Match unique colors to LUT indices in high-fidelity mode."""
        log.info(f"[IMAGE_PROCESSOR] hue_weight={self.hue_weight}, hue_matcher={'YES' if self.hue_matcher else 'NONE'}")
        return match_colors_to_lut(unique_colors, self.lut_rgb, self.lut_lab, self.kdtree, self.hue_matcher)

    def _build_high_fidelity_debug_data(self, quantized_image, unique_colors, rgb_processed, blur_kernel, smooth_sigma):
        """Build debug payload for high-fidelity mode."""
        filtered_copy = rgb_processed.copy()
        return {
            "quantized_image": quantized_image.copy(),
            "num_colors": len(unique_colors),
            "bilateral_filtered": filtered_copy,
            "sharpened": filtered_copy,
            "filter_settings": {"blur_kernel": blur_kernel, "smooth_sigma": smooth_sigma},
        }

    def _process_pixel_mode(self, rgb_arr, target_h, target_w):
        """像素模式：去重颜色后匹配 LUT，不做平滑处理。
        Pixel art mode: deduplicate colors then match, no smoothing.

        Returns:
            tuple: (matched_rgb, material_matrix, bg_reference)
        """
        log.info(f"[IMAGE_PROCESSOR] Direct pixel-level matching (Pixel Art mode, CIELAB space)...")
        flat_rgb = rgb_arr.reshape(-1, 3)
        unique_colors, inverse = np.unique(flat_rgb, axis=0, return_inverse=True)
        log.info(f"[IMAGE_PROCESSOR] Pixel dedup: {len(flat_rgb)} pixels -> {len(unique_colors)} unique colors")
        if self.hue_matcher is not None:
            log.info(f"[IMAGE_PROCESSOR] Hue-aware matching enabled (hue_weight={self.hue_weight})")
            unique_indices = self.hue_matcher.match_colors_batch(unique_colors, k=32)
        else:
            unique_lab = self._rgb_to_lab(unique_colors)
            _, unique_indices = self.kdtree.query(unique_lab)
        indices = unique_indices[inverse]
        matched_rgb = self.lut_rgb[indices].reshape(target_h, target_w, 3)
        material_matrix = self.ref_stacks[indices].reshape(target_h, target_w, self.layer_count)
        log.info(f"[IMAGE_PROCESSOR] Direct matching complete!")
        return matched_rgb, material_matrix, rgb_arr
