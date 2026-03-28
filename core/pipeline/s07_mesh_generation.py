"""
S07 — Multi-material 3D mesh generation (parallel ThreadPoolExecutor).
S07 — 多材质 3D 网格生成（支持并行 ThreadPoolExecutor）。

从 converter.py 搬入的网格生成逻辑：
- get_mesher() 调用
- ThreadPoolExecutor 并行网格生成
- scene 构建与 transform 应用
"""

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import trimesh

from config import PrinterConfig
from core.mesh_generators import get_mesher


def _timed_generate_mesh(mesher, full_matrix, mat_id, target_h):
    """Wrapper that returns (mesh, elapsed_s) measured inside the worker thread."""
    _t = time.perf_counter()
    result = mesher.generate_mesh(full_matrix, mat_id, target_h)
    return result, time.perf_counter() - _t


def run(ctx: dict) -> dict:
    """Generate multi-material 3D meshes with optional parallel execution.
    生成多材质 3D 网格，支持可选的并行执行。

    PipelineContext 输入键 / Input keys:
        - full_matrix (np.ndarray): (Z, H, W) int 体素矩阵
        - slot_names (list[str]): 材料槽位名称列表
        - preview_colors (dict): 材料预览颜色
        - modeling_mode (ModelingMode): 建模模式
        - target_h (int): 图像高度（像素）
        - pixel_scale (float): mm/px 缩放因子

    PipelineContext 输出键 / Output keys:
        - scene (trimesh.Scene): 包含所有材质网格的 3D 场景
        - valid_slot_names (list[str]): 成功生成网格的材料名称列表
        - transform (np.ndarray): 4x4 变换矩阵（像素→mm）
    """
    full_matrix = ctx['full_matrix']
    slot_names = ctx['slot_names']
    preview_colors = ctx['preview_colors']
    modeling_mode = ctx['modeling_mode']
    target_h = ctx['target_h']
    pixel_scale = ctx['pixel_scale']

    _bench_enabled = ctx.get('_bench_enabled', True)
    _mesh_t0 = time.perf_counter() if _bench_enabled else None

    # Build transform matrix: pixel/voxel coords → mm
    scene = trimesh.Scene()

    transform = np.eye(4)
    transform[0, 0] = pixel_scale
    transform[1, 1] = pixel_scale
    transform[2, 2] = PrinterConfig.LAYER_HEIGHT

    print(f"[S07] Transform: XY={pixel_scale}mm/px, Z={PrinterConfig.LAYER_HEIGHT}mm/layer")

    mesher = get_mesher(modeling_mode)
    print(f"[S07] Using mesher: {mesher.__class__.__name__}")

    valid_slot_names = []
    num_materials = len(slot_names)
    print(f"[S07] Generating meshes for {num_materials} materials...")

    max_workers = min(4, num_materials)
    parallel_enabled = max_workers > 1 and os.getenv("LUMINA_DISABLE_PARALLEL_MESH", "0") != "1"
    mesh_results = {}
    mesh_errors = {}
    mat_timings = {}
    if parallel_enabled:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_map = {
                pool.submit(_timed_generate_mesh, mesher, full_matrix, mat_id, target_h): mat_id
                for mat_id in range(num_materials)
            }
            for future in as_completed(future_map):
                mat_id = future_map[future]
                try:
                    mesh_results[mat_id], mat_timings[mat_id] = future.result()
                except Exception as e:
                    mesh_errors[mat_id] = e
    else:
        for mat_id in range(num_materials):
            try:
                mesh_results[mat_id], mat_timings[mat_id] = _timed_generate_mesh(mesher, full_matrix, mat_id, target_h)
            except Exception as e:
                mesh_errors[mat_id] = e

    for mat_id in range(num_materials):
        if mat_id in mesh_errors:
            e = mesh_errors[mat_id]
            print(f"[S07] Error generating mesh for material {mat_id} ({slot_names[mat_id]}): {e}")
            print(f"[S07] Continuing with other materials...")
            continue
        mesh = mesh_results.get(mat_id)
        if mesh:
            mesh.apply_transform(transform)
            mesh.visual.face_colors = preview_colors[mat_id]
            name = slot_names[mat_id]
            mesh.metadata['name'] = name
            scene.add_geometry(
                mesh,
                node_name=name,
                geom_name=name
            )
            valid_slot_names.append(name)
            _mt = mat_timings.get(mat_id, 0.0)
            print(f"[S07]   {name}: {len(mesh.vertices):,}v {len(mesh.faces):,}f  {_mt:.3f}s")

    if _bench_enabled and _mesh_t0 is not None:
        _mesh_elapsed = time.perf_counter() - _mesh_t0
        _hifi_timings = ctx.setdefault('_hifi_timings', {})
        _hifi_timings['mesh_gen_s'] = _mesh_elapsed
        print(f"[S07] mesh_gen done: {_mesh_elapsed:.3f}s")

    ctx['scene'] = scene
    ctx['valid_slot_names'] = valid_slot_names
    ctx['transform'] = transform
    ctx['mesher'] = mesher

    return ctx
