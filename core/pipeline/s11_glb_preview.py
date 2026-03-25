"""
S11 — GLB 3D preview export.
S11 — GLB 3D 预览导出。

从 converter.py 搬入的 GLB 预览函数：
- _create_preview_mesh: 简化预览网格生成
- _merge_low_frequency_colors: 低频颜色合并
- _build_color_voxel_mesh: 按颜色体素网格构建
- generate_segmented_glb: 分色 GLB 预览
- generate_realtime_glb: 实时 GLB 预览
- generate_empty_bed_glb: 空热床 GLB
"""

import os
import time
from typing import Optional

import cv2
import numpy as np
import trimesh

from config import PrinterConfig, OUTPUT_DIR, BedManager
from core.naming import generate_preview_filename


def _create_preview_mesh(
    matched_rgb: np.ndarray,
    mask_solid: np.ndarray,
    total_layers: int,
    backing_color_id: int = 0,
    backing_z_range: tuple = None,
    preview_colors: list = None,
) -> Optional[trimesh.Trimesh]:
    """Create simplified 3D preview mesh for browser display.
    为浏览器显示创建简化的 3D 预览网格。

    Args:
        matched_rgb (np.ndarray): RGB color array of shape (H, W, 3).
        mask_solid (np.ndarray): Boolean mask of solid pixels of shape (H, W).
        total_layers (int): Total number of Z layers.
        backing_color_id (int): Backing material ID (0-7), default is 0 (White).
        backing_z_range (tuple): Tuple of (start_z, end_z) for backing layer, or None.
        preview_colors (list): List of preview colors for materials.

    Returns:
        trimesh.Trimesh: Simplified preview mesh, downsampled for large models.
    """
    height, width = matched_rgb.shape[:2]
    total_pixels = width * height

    SIMPLIFY_THRESHOLD = 500_000
    TARGET_PIXELS = 300_000

    if total_pixels > SIMPLIFY_THRESHOLD:
        scale_factor = int(np.sqrt(total_pixels / TARGET_PIXELS))
        scale_factor = max(2, min(scale_factor, 16))

        print(f"[PREVIEW] Downsampling by {scale_factor}x ({total_pixels:,} -> ~{TARGET_PIXELS:,} pixels)")

        new_height = height // scale_factor
        new_width = width // scale_factor

        matched_rgb = cv2.resize(matched_rgb, (new_width, new_height), interpolation=cv2.INTER_AREA)
        mask_solid = cv2.resize(
            mask_solid.astype(np.uint8), (new_width, new_height), interpolation=cv2.INTER_NEAREST
        ).astype(bool)

        height, width = new_height, new_width
        shrink = 0.0
    else:
        shrink = 0.0

    # --- numpy vectorized mesh build ---
    _CUBE_FACES = np.array([
        [0,2,1],[0,3,2],
        [4,5,6],[4,6,7],
        [0,1,5],[0,5,4],
        [1,2,6],[1,6,5],
        [2,3,7],[2,7,6],
        [3,0,4],[3,4,7],
    ], dtype=np.int64)  # (12, 3)

    def _boxes_np(px, py, z0_scalar, z1_scalar, colors_rgba):
        """Build voxel boxes for N pixels, all at same z range."""
        n = len(px)
        if n == 0:
            return np.empty((0,3)), np.empty((0,3),dtype=np.int64), np.empty((0,4),dtype=np.uint8)
        x0 = px + shrink
        x1 = px + 1 - shrink
        y0 = py + shrink
        y1 = py + 1 - shrink
        z0 = np.full(n, z0_scalar, dtype=np.float64)
        z1 = np.full(n, z1_scalar, dtype=np.float64)
        # verts: (n,8,3)
        verts = np.stack([
            np.column_stack([x0,y0,z0]),
            np.column_stack([x1,y0,z0]),
            np.column_stack([x1,y1,z0]),
            np.column_stack([x0,y1,z0]),
            np.column_stack([x0,y0,z1]),
            np.column_stack([x1,y0,z1]),
            np.column_stack([x1,y1,z1]),
            np.column_stack([x0,y1,z1]),
        ], axis=1)  # (n,8,3)
        all_verts = verts.reshape(-1, 3)
        offsets = (np.arange(n, dtype=np.int64) * 8)[:,None,None]
        all_faces = (_CUBE_FACES[None] + offsets).reshape(-1, 3)
        if colors_rgba.ndim == 1:
            all_colors = np.tile(colors_rgba, (n*12, 1))
        else:
            all_colors = np.repeat(colors_rgba, 12, axis=0)
        return all_verts, all_faces, all_colors

    ys_all, xs_all = np.where(mask_solid)
    world_ys = (height - 1 - ys_all).astype(np.float64)
    xs_f = xs_all.astype(np.float64)

    all_v_list, all_f_list, all_c_list = [], [], []
    face_offset = 0

    if backing_z_range is not None and preview_colors is not None:
        backing_start, backing_end = backing_z_range
        backing_color_rgba = np.array(preview_colors[backing_color_id], dtype=np.uint8)[:4]
        pixel_colors = np.column_stack([
            matched_rgb[ys_all, xs_all].astype(np.uint8),
            np.full(len(ys_all), 255, dtype=np.uint8)
        ])  # (N,4)

        # backing box
        v, f, c = _boxes_np(xs_f, world_ys, float(backing_start), float(backing_end+1), backing_color_rgba)
        if len(v):
            all_v_list.append(v); all_f_list.append(f + face_offset); all_c_list.append(c)
            face_offset += len(v)

        # bottom box (z 0 -> backing_start)
        if backing_start > 0:
            v, f, c = _boxes_np(xs_f, world_ys, 0.0, float(backing_start), pixel_colors)
            if len(v):
                all_v_list.append(v); all_f_list.append(f + face_offset); all_c_list.append(c)
                face_offset += len(v)

        # top box (backing_end+1 -> total_layers)
        if backing_end + 1 < total_layers:
            v, f, c = _boxes_np(xs_f, world_ys, float(backing_end+1), float(total_layers), pixel_colors)
            if len(v):
                all_v_list.append(v); all_f_list.append(f + face_offset); all_c_list.append(c)
                face_offset += len(v)
    else:
        pixel_colors = np.column_stack([
            matched_rgb[ys_all, xs_all].astype(np.uint8),
            np.full(len(ys_all), 255, dtype=np.uint8)
        ])
        v, f, c = _boxes_np(xs_f, world_ys, 0.0, float(total_layers), pixel_colors)
        if len(v):
            all_v_list.append(v); all_f_list.append(f); all_c_list.append(c)

    if not all_v_list:
        return None

    vertices_np = np.concatenate(all_v_list, axis=0)
    faces_np = np.concatenate(all_f_list, axis=0)
    face_colors_np = np.concatenate(all_c_list, axis=0)

    mesh = trimesh.Trimesh(vertices=vertices_np, faces=faces_np, process=False)
    mesh.visual.face_colors = face_colors_np
    print(f"[PREVIEW] Generated: {len(mesh.vertices):,} vertices, {len(mesh.faces):,} faces")
    return mesh


def _merge_low_frequency_colors(
    unique_colors: np.ndarray,
    pixel_counts: np.ndarray,
    max_meshes: int,
) -> np.ndarray:
    """Merge low-frequency colors into their nearest high-frequency neighbors.
    将低频颜色合并到最近的高频邻居。

    Args:
        unique_colors (np.ndarray): (N, 3) uint8 array of unique RGB colors.
        pixel_counts (np.ndarray): (N,) int array of pixel counts per color.
        max_meshes (int): Maximum number of colors to keep.

    Returns:
        np.ndarray: (N, 3) uint8 array where tail colors are replaced by nearest kept color.
    """
    n = len(unique_colors)
    if n <= max_meshes:
        return unique_colors.copy()

    order = np.argsort(-pixel_counts)
    keep_indices = order[:max_meshes]
    tail_indices = order[max_meshes:]

    kept_colors = unique_colors[keep_indices].astype(np.float64)
    merged = unique_colors.copy()

    tail_rgb = unique_colors[tail_indices].astype(np.float64)
    # Vectorized nearest-neighbor via broadcasting: (T, 1, 3) - (1, K, 3)
    diff = tail_rgb[:, None, :] - kept_colors[None, :, :]
    dist_sq = np.sum(diff**2, axis=2)
    nearest = np.argmin(dist_sq, axis=1)

    merged[tail_indices] = unique_colors[keep_indices[nearest]]
    return merged


def _build_color_voxel_mesh(
    mask: np.ndarray,
    height: int,
    width: int,
    total_layers: int,
    shrink: float,
    rgba: np.ndarray,
) -> Optional[trimesh.Trimesh]:
    """Build a voxelized Trimesh for pixels indicated by *mask*.
    为 mask 指示的像素构建体素化 Trimesh。

    Args:
        mask (np.ndarray): (H, W) bool array of pixels belonging to this color.
        height (int): Image height after downsampling.
        width (int): Image width after downsampling.
        total_layers (int): Number of Z layers for the voxel height.
        shrink (float): Inset amount for voxel gaps.
        rgba (np.ndarray): (4,) uint8 RGBA color for face coloring.

    Returns:
        trimesh.Trimesh or None: Generated mesh, or None if mask has no True pixels.
    """
    ys, xs = np.where(mask)
    n_pixels = len(ys)
    if n_pixels == 0:
        return None

    _FACE_TPL = np.array(
        [
            [0, 2, 1], [0, 3, 2],
            [4, 5, 6], [4, 6, 7],
            [0, 1, 5], [0, 5, 4],
            [1, 2, 6], [1, 6, 5],
            [2, 3, 7], [2, 7, 6],
            [3, 0, 4], [3, 4, 7],
        ],
        dtype=np.int64,
    )

    x0 = xs.astype(np.float64) + shrink
    x1 = xs.astype(np.float64) + 1.0 - shrink
    world_y = (height - 1 - ys).astype(np.float64)
    y0 = world_y + shrink
    y1 = world_y + 1.0 - shrink
    z0 = np.zeros(n_pixels, dtype=np.float64)
    z1 = np.full(n_pixels, float(total_layers), dtype=np.float64)

    v = np.empty((n_pixels, 8, 3), dtype=np.float64)
    v[:, 0, 0] = x0;  v[:, 0, 1] = y0;  v[:, 0, 2] = z0
    v[:, 1, 0] = x1;  v[:, 1, 1] = y0;  v[:, 1, 2] = z0
    v[:, 2, 0] = x1;  v[:, 2, 1] = y1;  v[:, 2, 2] = z0
    v[:, 3, 0] = x0;  v[:, 3, 1] = y1;  v[:, 3, 2] = z0
    v[:, 4, 0] = x0;  v[:, 4, 1] = y0;  v[:, 4, 2] = z1
    v[:, 5, 0] = x1;  v[:, 5, 1] = y0;  v[:, 5, 2] = z1
    v[:, 6, 0] = x1;  v[:, 6, 1] = y1;  v[:, 6, 2] = z1
    v[:, 7, 0] = x0;  v[:, 7, 1] = y1;  v[:, 7, 2] = z1

    offsets = (np.arange(n_pixels, dtype=np.int64) * 8).reshape(-1, 1, 1)
    all_faces = (_FACE_TPL.reshape(1, 12, 3) + offsets).reshape(-1, 3)
    all_colors = np.broadcast_to(rgba, (n_pixels * 12, 4)).copy()

    mesh = trimesh.Trimesh(vertices=v.reshape(-1, 3), faces=all_faces, process=False)
    mesh.visual.face_colors = all_colors
    return mesh



def _build_backing_plate_mesh(
    mask_solid: np.ndarray,
    height: int,
    pixel_scale: float,
    rgba: np.ndarray,
) -> Optional[trimesh.Trimesh]:
    """用 cv2.findContours 轮廓拉伸构建底板，替代逐像素体素方案。
    顶点数从 ~3M 降至 <5k，节省约 2.5s。
    """
    from shapely.geometry import Polygon
    mask_u8 = mask_solid.astype(np.uint8) * 255
    contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_TC89_KCOS)
    if not contours:
        return None

    extrude_h = float(PrinterConfig.LAYER_HEIGHT)
    meshes = []
    for cnt in contours:
        if len(cnt) < 3:
            continue
        pts = cnt.squeeze(1).astype(np.float64)
        world_pts = np.column_stack([
            pts[:, 0] * pixel_scale,
            (height - pts[:, 1]) * pixel_scale,
        ])
        try:
            poly = Polygon(world_pts)
            if not poly.is_valid:
                poly = poly.buffer(0)
            if poly.is_empty or poly.area < 1e-4:
                continue
            m = trimesh.creation.extrude_polygon(poly, height=extrude_h)
            meshes.append(m)
        except Exception:
            continue

    if not meshes:
        return None

    result = trimesh.util.concatenate(meshes) if len(meshes) > 1 else meshes[0]
    result.visual.face_colors = np.tile(rgba, (len(result.faces), 1))
    return result


def generate_empty_bed_glb(
    bed_w: int = None,
    bed_h: int = None,
    is_dark: bool = False,
) -> Optional[str]:
    """Generate a GLB file containing only the print bed (no model).
    生成仅包含打印热床的 GLB 文件（无模型）。

    Args:
        bed_w (int): Bed width in mm. Defaults to BedManager default.
        bed_h (int): Bed height in mm. Defaults to BedManager default.
        is_dark (bool): Use dark PEI theme.

    Returns:
        str: Path to GLB file, or None on failure.
    """
    try:
        # Lazy import: _create_bed_mesh lives in converter.py until P06 is wired
        from core.converter import _create_bed_mesh

        if bed_w is None or bed_h is None:
            bed_w, bed_h = BedManager.get_bed_size(BedManager.DEFAULT_BED)
        bed_mesh = _create_bed_mesh(bed_w, bed_h, is_dark=is_dark)
        if bed_mesh is None:
            return None
        glb_scene = trimesh.Scene()
        glb_scene.add_geometry(bed_mesh, node_name="bed")
        glb_path = os.path.join(OUTPUT_DIR, f"empty_bed_{bed_w}x{bed_h}.glb")
        glb_scene.export(glb_path)
        return glb_path
    except Exception as e:
        print(f"[EMPTY_BED] Failed: {e}")
        return None


def generate_segmented_glb(cache: dict, max_meshes: int = 64, output_path: Optional[str] = None) -> Optional[str]:
    """Generate a color-segmented GLB preview with one named Mesh per color.
    生成按颜色分段的 GLB 预览，每种颜色一个独立 Mesh。

    Args:
        cache (dict): Preview cache dict containing at least:
            - matched_rgb: (H, W, 3) uint8 array
            - mask_solid: (H, W) bool array
            - target_w, target_h: pixel dimensions
            - target_width_mm: physical width in mm
        max_meshes (int): Maximum Mesh count before merging (default 64).

    Returns:
        str: Path to the exported GLB file, or None on failure.
    """
    if cache is None:
        return None

    matched_rgb = cache.get("matched_rgb")
    mask_solid = cache.get("mask_solid")
    target_w = cache.get("target_w")
    target_width_mm = cache.get("target_width_mm")

    if matched_rgb is None or mask_solid is None:
        return None

    try:
        _glb_t0 = time.perf_counter()

        # 1. Downsample large images
        _t = time.perf_counter()
        height, width = matched_rgb.shape[:2]
        total_pixels = width * height
        SIMPLIFY_THRESHOLD = 500_000
        TARGET_PIXELS = 300_000

        if total_pixels > SIMPLIFY_THRESHOLD:
            scale_factor = int(np.sqrt(total_pixels / TARGET_PIXELS))
            scale_factor = max(2, min(scale_factor, 16))
            print(f"[SEGMENTED_GLB] Downsampling by {scale_factor}x")

            new_h = height // scale_factor
            new_w = width // scale_factor
            matched_rgb = cv2.resize(matched_rgb, (new_w, new_h), interpolation=cv2.INTER_NEAREST)
            mask_solid = cv2.resize(
                mask_solid.astype(np.uint8),
                (new_w, new_h),
                interpolation=cv2.INTER_NEAREST,
            ).astype(bool)
            height, width = new_h, new_w
            shrink = 0.0
        else:
            shrink = 0.0
        _t_downsample = time.perf_counter() - _t

        # 2. Extract unique colors and pixel counts (solid pixels only)
        _t = time.perf_counter()
        solid_pixels = matched_rgb[mask_solid]  # (N, 3)
        if len(solid_pixels) == 0:
            print("[SEGMENTED_GLB] No solid pixels, returning None")
            return None

        unique_colors, inverse, pixel_counts = np.unique(
            solid_pixels,
            axis=0,
            return_inverse=True,
            return_counts=True,
        )
        n_unique = len(unique_colors)
        print(f"[SEGMENTED_GLB] Found {n_unique} unique colors")
        _t_unique = time.perf_counter() - _t

        # 3. Merge low-frequency colors if exceeding max_meshes
        _t = time.perf_counter()
        if n_unique > max_meshes:
            print(f"[SEGMENTED_GLB] Merging {n_unique} colors down to {max_meshes}")
            merged_colors = _merge_low_frequency_colors(unique_colors, pixel_counts, max_meshes)
            new_solid = merged_colors[inverse]
            matched_rgb_work = matched_rgb.copy()
            matched_rgb_work[mask_solid] = new_solid
            solid_pixels = matched_rgb_work[mask_solid]
            unique_colors, _, pixel_counts = np.unique(
                solid_pixels,
                axis=0,
                return_inverse=True,
                return_counts=True,
            )
            matched_rgb = matched_rgb_work
            print(f"[SEGMENTED_GLB] After merge: {len(unique_colors)} colors")
        _t_merge = time.perf_counter() - _t

        # 4. Build per-color Meshes + Extract 2D contours (single pass)
        _t = time.perf_counter()
        total_layers = 25
        scene = trimesh.Scene()
        contours_data: dict[str, list[list[list[float]]]] = {}

        pixel_scale = target_width_mm / width if width > 0 else 0.42
        scale_transform = np.eye(4)
        scale_transform[0, 0] = pixel_scale
        scale_transform[1, 1] = pixel_scale
        scale_transform[2, 2] = PrinterConfig.LAYER_HEIGHT

        for color_rgb in unique_colors:
            r, g, b = int(color_rgb[0]), int(color_rgb[1]), int(color_rgb[2])
            hex_name = f"{r:02x}{g:02x}{b:02x}"
            rgba = np.array([r, g, b, 255], dtype=np.uint8)

            color_match = np.all(matched_rgb == color_rgb, axis=2) & mask_solid

            mesh = _build_color_voxel_mesh(
                color_match,
                height,
                width,
                total_layers,
                shrink,
                rgba,
            )
            if mesh is not None:
                mesh.apply_transform(scale_transform)
                min_z = mesh.vertices[:, 2].min()
                if min_z != 0.0:
                    mesh.vertices[:, 2] -= min_z
                scene.add_geometry(mesh, node_name=f"color_{hex_name}")

            # Reuse same color_match for contour extraction
            mask_u8 = color_match.astype(np.uint8) * 255
            cv_contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if cv_contours:
                color_contour_list: list[list[list[float]]] = []
                for cnt in cv_contours:
                    if len(cnt) < 3:
                        continue
                    pts = cnt.squeeze(1).astype(float)
                    world_pts = [
                        [float(px * pixel_scale), float((height - py) * pixel_scale)]
                        for px, py in pts
                    ]
                    color_contour_list.append(world_pts)
                if color_contour_list:
                    contours_data[hex_name] = color_contour_list

        _t_mesh_loop = time.perf_counter() - _t

        if len(scene.geometry) == 0:
            print("[SEGMENTED_GLB] No meshes generated")
            return None

        # 4.5 Build backing plate mesh (contour extrusion)
        _t = time.perf_counter()
        backing_mesh = _build_backing_plate_mesh(
            mask_solid=mask_solid,
            height=height,
            pixel_scale=pixel_scale,
            rgba=np.array([245, 245, 245, 255], dtype=np.uint8),
        )
        if backing_mesh is not None:
            scene.add_geometry(backing_mesh, node_name="backing_plate")
            print(f"[SEGMENTED_GLB] Backing plate added ({backing_mesh.vertices.shape[0]} vertices)")
        _t_backing = time.perf_counter() - _t

        cache['color_contours'] = contours_data
        print(f"[SEGMENTED_GLB] Extracted contours for {len(contours_data)} colors")

        # 6. Export GLB
        _t = time.perf_counter()
        glb_path = output_path if output_path else os.path.join(OUTPUT_DIR, "segmented_preview.glb")
        scene.export(glb_path)
        _t_export = time.perf_counter() - _t

        _t_glb_total = time.perf_counter() - _glb_t0
        print(f"[SEGMENTED_GLB] Exported {len(scene.geometry)} meshes -> {glb_path}")
        print(f"[SEGMENTED_GLB] Timing: downsample={_t_downsample:.2f}s, "
              f"unique={_t_unique:.2f}s, merge={_t_merge:.2f}s, "
              f"mesh_loop={_t_mesh_loop:.2f}s, backing={_t_backing:.2f}s, "
              f"export={_t_export:.2f}s, total={_t_glb_total:.2f}s")
        return glb_path

    except Exception as e:
        print(f"[SEGMENTED_GLB] Failed: {e}")
        import traceback

        traceback.print_exc()
        return None


def generate_realtime_glb(cache: dict) -> Optional[str]:
    """Generate a lightweight GLB preview from cached preview data.
    从缓存的预览数据生成轻量级 GLB 预览。

    Called during preview stage so the 3D thumbnail updates immediately
    without waiting for the full 3MF export.

    Args:
        cache (dict): Preview cache dict from generate_preview_cached.

    Returns:
        str: Path to GLB file, or None on failure.
    """
    if cache is None:
        return None

    matched_rgb = cache.get("matched_rgb")
    mask_solid = cache.get("mask_solid")
    target_w = cache.get("target_w")
    target_h = cache.get("target_h")
    target_width_mm = cache.get("target_width_mm")
    color_conf = cache.get("color_conf")

    if matched_rgb is None or mask_solid is None:
        return None

    try:
        total_layers = 25
        preview_colors = color_conf.get("preview") if color_conf else None

        preview_mesh = _create_preview_mesh(
            matched_rgb,
            mask_solid,
            total_layers,
            backing_color_id=cache.get("backing_color_id", 0),
            preview_colors=preview_colors,
        )

        if preview_mesh is None:
            print("[REALTIME_GLB] Preview mesh is None (model too large?)")
            return None

        # Scale from pixel/voxel coords to mm
        mesh_width = preview_mesh.bounds[1][0] - preview_mesh.bounds[0][0]
        pixel_scale = target_width_mm / mesh_width if mesh_width > 0 else 0.42
        transform = np.eye(4)
        transform[0, 0] = pixel_scale
        transform[1, 1] = pixel_scale
        transform[2, 2] = PrinterConfig.LAYER_HEIGHT
        preview_mesh.apply_transform(transform)

        glb_path = os.path.join(OUTPUT_DIR, "realtime_preview.glb")
        preview_mesh.export(glb_path)
        print(f"[REALTIME_GLB] Exported: {glb_path}")
        return glb_path

    except Exception as e:
        print(f"[REALTIME_GLB] Failed: {e}")
        return None


def run(ctx: dict) -> dict:
    """Generate GLB 3D preview for the converted model.
    为转换后的模型生成 GLB 3D 预览。

    PipelineContext 输入键 / Input keys:
        - matched_rgb (np.ndarray): (H, W, 3) 匹配后的 RGB
        - mask_solid (np.ndarray): (H, W) bool 实体掩码
        - total_layers (int): 总层数
        - backing_color_id (int): 底板材料 ID
        - backing_metadata (dict): 底板元数据
        - preview_colors (dict): 材料预览颜色
        - pixel_scale (float): mm/px 缩放因子
        - loop_info (dict | None): 挂件环信息
        - loop_added (bool): 挂件环是否已添加
        - image_path (str): 原始图像路径
        - modeling_mode (ModelingMode): 建模模式
        - enable_outline (bool): 启用描边
        - outline_width (float): 描边宽度
        - outline_added (bool): 描边是否已添加
        - target_h (int): 图像高度（像素）
        - transform (np.ndarray): 4x4 变换矩阵

    PipelineContext 输出键 / Output keys:
        - glb_path (str | None): GLB 预览文件路径
    """
    _t0 = time.perf_counter()

    matched_rgb = ctx["matched_rgb"]
    mask_solid = ctx["mask_solid"]
    pixel_scale = ctx["pixel_scale"]
    image_path = ctx["image_path"]

    _prog = ctx.get("progress")
    if _prog is not None:
        _prog(0.90, "生成 3D 预览中... | Generating 3D preview...")

    height, width = matched_rgb.shape[:2]
    target_width_mm = pixel_scale * width
    base_name = os.path.splitext(os.path.basename(image_path))[0]
    out_path = os.path.join(OUTPUT_DIR, generate_preview_filename(base_name))

    cache = {
        "matched_rgb": matched_rgb,
        "mask_solid": mask_solid,
        "target_w": width,
        "target_h": height,
        "target_width_mm": target_width_mm,
    }
    glb_path = generate_segmented_glb(cache, output_path=out_path)

    ctx["glb_path"] = glb_path

    _elapsed = time.perf_counter() - _t0
    print(f"[S11] glb_preview done: {_elapsed:.3f}s")
    ctx.setdefault('_hifi_timings', {})['glb_preview_s'] = _elapsed
    return ctx
