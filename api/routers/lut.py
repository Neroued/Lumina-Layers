"""Lumina Studio API — LUT Management Router.
Lumina Studio API — LUT 管理路由。

Provides endpoints for LUT preset listing, information queries, and merge operations.
提供 LUT 预设列表、信息查询和合并操作端点。
"""

import os
import shutil
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from api.schemas.lut import (
    CompareDiffItem,
    CompareRequest,
    CompareResponse,
    CompareStats,
    LutInfoResponse,
    MergeRequest,
    MergeResponse,
    MergeStats,
    PaletteEntrySchema,
)
from api.schemas.responses import LUTListResponse, LutInfo, LutColorsResponse, LutColorEntry
from config import LUTMetadata
from core.lut_merger import LUTMerger
from utils.lut_manager import LUTManager

router = APIRouter(prefix="/api/lut", tags=["LUT"])

_VALID_PRIMARY_MODES = {"6-Color", "8-Color", "8-Color Max"}


def _dedupe_warnings(warnings: list[str]) -> list[str]:
    """Preserve warning order while removing duplicates.
    保持警告顺序并移除重复项。
    """
    seen: set[str] = set()
    result: list[str] = []
    for warning in warnings:
        if warning and warning not in seen:
            seen.add(warning)
            result.append(warning)
    return result


@router.get("/list")
def list_luts() -> LUTListResponse:
    """Return all available LUT presets as a list of LutInfo objects.
    返回所有可用 LUT 预设，以 LutInfo 对象列表形式返回。
    """
    lut_dict: dict[str, str] = LUTManager.get_all_lut_files()
    lut_list: list[LutInfo] = [
        LutInfo(
            name=display_name,
            color_mode=LUTManager.infer_color_mode(display_name, file_path),
            path=file_path,
        )
        for display_name, file_path in lut_dict.items()
    ]
    return LUTListResponse(luts=lut_list)


_ALLOWED_LUT_EXTENSIONS = {".npy", ".json", ".npz"}


@router.post("/upload")
async def upload_lut(file: UploadFile = File(..., description="LUT 文件 (.npy/.json/.npz)")) -> dict:
    """Upload a LUT file to the Custom preset directory.
    上传 LUT 文件到 Custom 预设目录。
    """
    filename = file.filename or "unknown"
    ext = Path(filename).suffix.lower()
    if ext not in _ALLOWED_LUT_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail=f"不支持的文件类型: {ext}，仅支持 .npy/.json/.npz",
        )

    # Save to temp file first (chunked read with size limit)
    from config import TEMP_DIR

    MAX_LUT_SIZE = 50 * 1024 * 1024  # 50 MB
    total_read = 0
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext, dir=TEMP_DIR) as tmp:
        while True:
            chunk = await file.read(1024 * 1024)  # 1 MB chunks
            if not chunk:
                break
            total_read += len(chunk)
            if total_read > MAX_LUT_SIZE:
                tmp_path = tmp.name
                os.unlink(tmp_path)
                raise HTTPException(
                    status_code=413,
                    detail=f"文件过大，最大允许 {MAX_LUT_SIZE // (1024*1024)} MB",
                )
            tmp.write(chunk)
        tmp_path = tmp.name

    try:
        import numpy as np

        stem = Path(filename).stem
        custom_dir = os.path.join(LUTManager.LUT_PRESET_DIR, "Custom")
        os.makedirs(custom_dir, exist_ok=True)

        # Auto-convert .npy to Keyed JSON
        if ext == ".npy":
            dest_ext = ".json"
            rgb = np.load(tmp_path)
            if rgb.ndim == 3:
                rgb = rgb.reshape(-1, 3)
            elif rgb.ndim == 1:
                rgb = rgb.reshape(-1, 3)
            metadata = LUTManager.infer_default_metadata(stem, tmp_path, len(rgb))
            stacks = np.zeros((len(rgb), 0), dtype=np.int32)
            dest_path = os.path.join(custom_dir, f"{stem}{dest_ext}")
            counter = 1
            while os.path.exists(dest_path):
                dest_path = os.path.join(custom_dir, f"{stem}_{counter}{dest_ext}")
                counter += 1
            LUTManager.save_keyed_json(dest_path, rgb, stacks, metadata)
        else:
            dest_path = os.path.join(custom_dir, filename)
            counter = 1
            while os.path.exists(dest_path):
                dest_path = os.path.join(custom_dir, f"{stem}_{counter}{ext}")
                counter += 1
            shutil.copy2(tmp_path, dest_path)

        display_name = f"Custom - {Path(dest_path).stem}"
        return {"status": "ok", "message": f"LUT 已保存: {display_name}", "name": display_name}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"上传失败: {exc}") from exc
    finally:
        os.unlink(tmp_path)


@router.post("/merge")
def merge_luts_endpoint(request: MergeRequest) -> MergeResponse:
    """Execute LUT merge: primary + multiple secondary LUTs.
    执行 LUT 合并：主 LUT + 多个辅助 LUT。

    Replicates the flow of ``ui/callbacks.py::on_merge_execute``:
    resolve paths → detect modes → validate compatibility →
    load data → skip Merged secondaries → merge → save to Custom dir.
    复刻 ``ui/callbacks.py::on_merge_execute`` 的完整流程：
    解析路径 → 检测模式 → 验证兼容性 → 加载数据 → 跳过 Merged Secondary → 合并 → 保存到 Custom 目录。
    """
    # 1. Validate secondary list not empty / 验证 Secondary 列表非空
    if not request.secondary_names:
        raise HTTPException(
            status_code=400,
            detail="At least one secondary LUT is required",
        )

    # 2. Resolve primary path / 解析主 LUT 路径
    primary_path: str | None = LUTManager.get_lut_path(request.primary_name)
    if primary_path is None:
        raise HTTPException(
            status_code=404,
            detail=f"LUT not found: {request.primary_name}",
        )

    try:
        # 3. Detect primary mode / 检测主 LUT 模式
        primary_mode, _ = LUTMerger.detect_color_mode(primary_path)
        if primary_mode not in _VALID_PRIMARY_MODES:
            raise HTTPException(
                status_code=400,
                detail="Primary LUT must be 6-Color or 8-Color",
            )

        # 4. Load primary data / 加载主 LUT 数据
        primary_rgb, primary_stacks = LUTMerger.load_lut_with_stacks(primary_path, primary_mode)
        entries = [(primary_rgb, primary_stacks, primary_mode)]
        all_modes: list[str] = [primary_mode]
        all_paths: list[str] = [primary_path]  # 记录所有输入路径，用于判断输出格式
        all_names: list[str] = [request.primary_name]  # 记录来源 LUT 显示名称

        # 5. Load each secondary, skip Merged / 加载辅助 LUT，跳过 Merged
        for sec_name in request.secondary_names:
            sec_path: str | None = LUTManager.get_lut_path(sec_name)
            if sec_path is None:
                continue
            sec_mode, _ = LUTMerger.detect_color_mode(sec_path)
            if sec_mode == "Merged":
                continue
            sec_rgb, sec_stacks = LUTMerger.load_lut_with_stacks(sec_path, sec_mode)
            entries.append((sec_rgb, sec_stacks, sec_mode))
            all_modes.append(sec_mode)
            all_paths.append(sec_path)
            all_names.append(sec_name)

        # 6. Need at least 2 entries / 至少需要 2 个有效条目
        if len(entries) < 2:
            raise HTTPException(
                status_code=400,
                detail="At least one secondary LUT is required",
            )

        # 7. Validate compatibility / 验证兼容性
        valid, err_msg = LUTMerger.validate_compatibility(all_modes)
        if not valid:
            raise HTTPException(status_code=400, detail=err_msg)

        # 判断输出格式：所有输入都是 .json 时输出 JSON，否则输出 .npz
        all_json = all(p.lower().endswith(".json") for p in all_paths)

        # 8. Merge / 执行合并
        # 如果输出 JSON，加载 metadata 以便保存完整的 Keyed JSON
        metadata_list: list[LUTMetadata] | None = None
        if all_json:
            metadata_list = []
            for p in all_paths:
                _, _, meta = LUTManager.load_lut_with_metadata(p)
                metadata_list.append(meta)

        merged_rgb, merged_stacks, stats = LUTMerger.merge_luts(
            entries,
            dedup_threshold=request.dedup_threshold,
            metadata_list=metadata_list,
            source_names=all_names,
        )

        # 9. Save to Custom dir / 保存到 Custom 目录
        timestamp: str = time.strftime("%Y%m%d_%H%M%S")
        mode_str: str = "+".join(all_modes)
        output_ext: str = ".json" if all_json else ".npz"
        output_name: str = f"Merged_{mode_str}_{timestamp}{output_ext}"
        custom_dir: str = os.path.join(LUTManager.LUT_PRESET_DIR, "Custom")
        os.makedirs(custom_dir, exist_ok=True)
        output_path: str = os.path.join(custom_dir, output_name)

        if all_json:
            # 输出 Keyed JSON 格式，保留 palette 和打印参数
            merged_metadata = stats.get("merged_metadata")
            if merged_metadata is None:
                # 回退：使用主 LUT 的 metadata
                _, _, merged_metadata = LUTManager.load_lut_with_metadata(primary_path)
            entry_sources = stats.get("entry_sources")
            json_stacks = LUTMerger.reindex_canonical_stacks_for_palette(
                merged_stacks,
                merged_metadata.palette,
            )
            LUTManager.save_keyed_json(
                output_path,
                merged_rgb,
                json_stacks,
                merged_metadata,
                sources=entry_sources,
            )
        else:
            LUTMerger.save_merged_lut(merged_rgb, merged_stacks, output_path)

        # 10. Return response / 返回响应
        # 注意：validate_print_params() 和 merge_palettes() 尚未实现（任务 6），暂时使用空列表
        return MergeResponse(
            status="success",
            message=f"Merged {stats['total_before']} colors → {stats['total_after']} colors",
            filename=output_name,
            stats=MergeStats(
                total_before=stats["total_before"],
                total_after=stats["total_after"],
                exact_dupes=stats["exact_dupes"],
                similar_removed=stats["similar_removed"],
            ),
            palette=[],
            warnings=[],
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Merge failed: {exc}",
        ) from exc


@router.post("/compare")
def compare_luts_endpoint(request: CompareRequest) -> CompareResponse:
    """Compare two LUTs by shared recipe keys.
    按共享配方键比较两个 LUT。
    """
    path_a: str | None = LUTManager.get_lut_path(request.lut_a_name)
    if path_a is None:
        raise HTTPException(status_code=404, detail=f"LUT not found: {request.lut_a_name}")

    path_b: str | None = LUTManager.get_lut_path(request.lut_b_name)
    if path_b is None:
        raise HTTPException(status_code=404, detail=f"LUT not found: {request.lut_b_name}")

    try:
        mode_a, _count_a = LUTMerger.detect_color_mode(path_a)
        mode_b, _count_b = LUTMerger.detect_color_mode(path_b)

        rgb_a, stacks_a = LUTMerger.load_lut_with_stacks(path_a, mode_a)
        rgb_b, stacks_b = LUTMerger.load_lut_with_stacks(path_b, mode_b)

        try:
            _, _, metadata_a = LUTManager.load_lut_with_metadata(path_a)
        except Exception:
            metadata_a = LUTMetadata(color_mode=mode_a)

        try:
            _, _, metadata_b = LUTManager.load_lut_with_metadata(path_b)
        except Exception:
            metadata_b = LUTMetadata(color_mode=mode_b)

        normalized_stacks_a = LUTMerger.normalize_stacks_for_compare(
            stacks_a, mode_a, path_a, metadata=metadata_a
        )
        normalized_stacks_b = LUTMerger.normalize_stacks_for_compare(
            stacks_b, mode_b, path_b, metadata=metadata_b
        )

        compare_result = LUTMerger.compare_luts_by_recipe(
            rgb_a,
            normalized_stacks_a,
            rgb_b,
            normalized_stacks_b,
            top_n=request.top_n,
        )

        warnings = list(compare_result.get("warnings", []))

        if mode_a != mode_b:
            warnings.append(f"color_mode 不一致: {mode_a} vs {mode_b}")

        if normalized_stacks_a.ndim == 2 and normalized_stacks_b.ndim == 2:
            if normalized_stacks_a.shape[1] != normalized_stacks_b.shape[1]:
                warnings.append(
                    f"recipe layer count differs: {normalized_stacks_a.shape[1]} vs {normalized_stacks_b.shape[1]}"
                )

        _compatible, param_warnings = LUTMerger.validate_print_params([metadata_a, metadata_b])
        warnings.extend(param_warnings)

        stats_dict = compare_result["stats"]
        if stats_dict["matched_recipe_count"] == 0:
            warnings.append("No shared recipes found; comparison metrics are zeroed.")

        warnings = _dedupe_warnings(warnings)
        message = (
            f"Compared {stats_dict['matched_recipe_count']} shared recipes between "
            f"{request.lut_a_name} and {request.lut_b_name}"
        )

        return CompareResponse(
            status="success",
            message=message,
            lut_a_name=request.lut_a_name,
            lut_b_name=request.lut_b_name,
            lut_a_mode=mode_a,
            lut_b_mode=mode_b,
            stats=CompareStats(**stats_dict),
            warnings=warnings,
            worst_diffs=[CompareDiffItem(**item) for item in compare_result["worst_diffs"]],
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Compare failed: {exc}",
        ) from exc


@router.get("/{lut_name}/colors")
def get_lut_colors(lut_name: str) -> LutColorsResponse:
    """Return all unique colors available in a LUT file.
    返回 LUT 文件中所有可用的唯一颜色。
    """
    path: str | None = LUTManager.get_lut_path(lut_name)
    if path is None:
        raise HTTPException(status_code=404, detail=f"LUT not found: {lut_name}")

    from core.converter import extract_lut_available_colors

    raw_colors: list[dict] = extract_lut_available_colors(path)
    entries: list[LutColorEntry] = [LutColorEntry(hex=c["hex"], rgb=c["color"]) for c in raw_colors]
    return LutColorsResponse(lut_name=lut_name, total=len(entries), colors=entries)


@router.get("/{lut_name}/info")
def get_lut_info(lut_name: str) -> LutInfoResponse:
    """Return color mode and color count for a specific LUT.
    返回指定 LUT 的颜色模式和颜色数量。
    """
    path: str | None = LUTManager.get_lut_path(lut_name)
    if path is None:
        raise HTTPException(status_code=404, detail=f"LUT not found: {lut_name}")

    color_mode, color_count = LUTMerger.detect_color_mode(path)

    # 加载元数据（如果 load_lut_with_metadata 可用）
    metadata = LUTMetadata()
    try:
        _rgb, _stacks, metadata = LUTManager.load_lut_with_metadata(path)
    except (AttributeError, NotImplementedError, Exception):
        # load_lut_with_metadata() 尚未实现（任务 4.2），回退使用默认空元数据
        pass

    palette_schema = [
        PaletteEntrySchema(color=e.color, material=e.material, hex_color=e.hex_color) for e in metadata.palette
    ]

    return LutInfoResponse(
        name=lut_name,
        color_mode=color_mode,
        color_count=color_count,
        palette=palette_schema,
        max_color_layers=metadata.max_color_layers,
        layer_height_mm=metadata.layer_height_mm,
        line_width_mm=metadata.line_width_mm,
        base_layers=metadata.base_layers,
        base_channel_idx=metadata.base_channel_idx,
        layer_order=metadata.layer_order,
    )
