"""
Lumina Studio - BambuStudio 3MF Writer
Enhanced 3MF export with BambuStudio-compatible metadata and configurations.

Uses neroued-3mf (C++ streaming writer with Production Extension) for 3MF
packaging, and injects Bambu/Orca vendor metadata via CustomPart.
"""

from __future__ import annotations

import io
import os
import sys
import time
import xml.etree.ElementTree as ET
import json
import copy
from typing import List, Dict, Optional
import numpy as np

# Lazy imports: avoid >60s startup cost when imported via API.
# Only loaded when export functions are actually called.
_trimesh = None
_n3mf = None


def _get_trimesh():
    global _trimesh
    if _trimesh is None:
        import trimesh as _tm

        _trimesh = _tm
    return _trimesh


def _get_n3mf():
    global _n3mf
    if _n3mf is None:
        import neroued_3mf as _n

        _n3mf = _n
    return _n3mf


_CONFIG_TEMPLATE_CACHE = None
_PRINTER_TEMPLATE_CACHE: dict[str, dict] = {}
_AGENT_DEBUG_LOG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "debug-ab5259.log")
_AGENT_DEBUG_SESSION_ID = "ab5259"


def _agent_debug_write(hypothesis_id, location, message, data, run_id="initial"):
    """Append one NDJSON debug entry for the current session."""
    payload = {
        "sessionId": _AGENT_DEBUG_SESSION_ID,
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
    try:
        with open(_AGENT_DEBUG_LOG_PATH, "a", encoding="utf-8") as debug_fp:
            debug_fp.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass


def load_printer_template(printer_id: str, slicer: str = "BambuStudio") -> dict:
    """Load printer config template JSON for the given printer ID and slicer.
    加载指定机型和切片器的配置模板 JSON。

    Priority: printer_profiles/ directory first (matched via PrinterProfile.get_template_file),
    falls back to bambu_config_template.json for backward compatibility.
    优先从 printer_profiles/ 目录加载，找不到时回退到 bambu_config_template.json。

    Args:
        printer_id (str): Printer identifier, e.g. "bambu-h2d". (打印机标识)
        slicer (str): Slicer software identifier, e.g. "BambuStudio" or "OrcaSlicer". (切片器标识)

    Returns:
        dict: Parsed JSON configuration template. (解析后的 JSON 配置模板)
    """
    global _PRINTER_TEMPLATE_CACHE

    cache_key = f"{printer_id}:{slicer}"
    if cache_key in _PRINTER_TEMPLATE_CACHE:
        return copy.deepcopy(_PRINTER_TEMPLATE_CACHE[cache_key])

    from config import get_printer_profile

    profile = get_printer_profile(printer_id)
    template_file = profile.get_template_file(slicer)

    # Resolve printer_profiles/ directory
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base_dir = sys._MEIPASS
    else:
        base_dir = os.path.join(os.path.dirname(__file__), "..")

    profile_path = os.path.join(base_dir, "printer_profiles", template_file)

    if os.path.exists(profile_path):
        with open(profile_path, "r", encoding="utf-8") as f:
            template = json.load(f)
        _PRINTER_TEMPLATE_CACHE[cache_key] = template
        print(f"[BAMBU_3MF] Loaded printer template: {profile_path} (slicer={slicer})")
        return copy.deepcopy(template)

    # Fallback to legacy bambu_config_template.json
    fallback_path = os.path.join(base_dir, "bambu_config_template.json")
    if os.path.exists(fallback_path):
        with open(fallback_path, "r", encoding="utf-8") as f:
            template = json.load(f)
        _PRINTER_TEMPLATE_CACHE[cache_key] = template
        print(
            f"[BAMBU_3MF] Printer template not found for '{printer_id}' (slicer={slicer}), using fallback: {fallback_path}"
        )
        return copy.deepcopy(template)

    print(f"[WARNING] No printer template found for '{printer_id}', returning empty dict")
    return {}


class BambuStudio3MFWriter:
    """Enhanced 3MF writer with BambuStudio-compatible metadata.
    使用 neroued-3mf Production Extension 生成 Bambu 兼容 3MF。

    Features:
    - Embeds print settings (layer height, temperatures, speeds)
    - Adds color information to objects via BaseMaterial
    - Compatible with BambuStudio/OrcaSlicer/ElegooSlicer/SnapmakerOrca
    - C++ streaming XML serialisation with native ZIP64 support
    """

    DEFAULT_SETTINGS = {
        "layer_height": "0.08",
        "initial_layer_height": "0.08",
        "wall_loops": "1",
        "top_shell_layers": "0",
        "bottom_shell_layers": "0",
        "sparse_infill_density": "100%",
        "sparse_infill_pattern": "zig-zag",
        "nozzle_temperature": ["220", "220", "220", "220"],
        "bed_temperature": ["60", "60", "60", "60"],
        "filament_type": ["PLA", "PLA", "PLA", "PLA"],
        "print_speed": "100",
        "travel_speed": "150",
        "enable_support": "0",
        "brim_width": "5",
        "brim_type": "auto_brim",
    }

    def __init__(
        self,
        output_path: str,
        settings: Optional[Dict] = None,
        color_mode: str = "4-Color",
        printer_id: str = "bambu-h2d",
        slicer: str = "BambuStudio",
        watermark: str = "LuminaStudio",
    ):
        """Initialize 3MF writer with printer-specific template support.
        初始化 3MF 写入器，支持机型和切片器专属配置模板。

        Args:
            output_path (str): Output .3mf file path. (输出 .3mf 文件路径)
            settings (Optional[Dict]): Custom print settings overrides. (自定义打印设置覆盖)
            color_mode (str): Color mode ('4-Color', '6-Color', '8-Color', 'BW'). (颜色模式)
            printer_id (str): Printer identifier for template selection, default 'bambu-h2d'. (打印机标识)
            slicer (str): Slicer software identifier, default 'BambuStudio'. (切片器标识)
            watermark (str): Watermark text embedded in the 3MF ZIP structure. (嵌入 3MF ZIP 结构的水印文本)
        """
        from config import normalize_slicer_software_id

        self.output_path = output_path
        self.settings = {**self.DEFAULT_SETTINGS, **(settings or {})}
        self.objects: list[tuple[_get_trimesh().Trimesh, str, tuple]] = []
        self.color_mode = color_mode
        self.printer_id = printer_id
        self.slicer = normalize_slicer_software_id(slicer)
        self.watermark = watermark

    def add_mesh(self, mesh: _get_trimesh().Trimesh, name: str, color_rgb: tuple):
        """Add a mesh object to the scene.
        将网格对象添加到场景中。

        Args:
            mesh: Trimesh object
            name: Object name (e.g., "White", "Cyan", "Magenta")
            color_rgb: RGB color tuple (0-255)
        """
        if mesh is None:
            raise ValueError(f"[BAMBU_3MF] Cannot add mesh '{name}': mesh is None")

        vertices = getattr(mesh, "vertices", None)
        faces = getattr(mesh, "faces", None)
        v_count = len(vertices) if vertices is not None else 0
        f_count = len(faces) if faces is not None else 0
        if v_count == 0 or f_count == 0:
            raise ValueError(f"[BAMBU_3MF] Cannot add mesh '{name}': empty geometry (v={v_count}, f={f_count})")

        self.objects.append((mesh, name, color_rgb))

    def export(self) -> str:
        """Export all meshes to a BambuStudio-compatible 3MF file.
        将所有网格导出为 BambuStudio 兼容的 3MF 文件。

        Returns:
            str: Path to the exported 3MF file
        """
        if len(self.objects) == 0:
            raise ValueError("[BAMBU_3MF] Refusing to export 3MF: no mesh objects were added")

        print(f"[BAMBU_3MF] Exporting {len(self.objects)} objects to {self.output_path}")
        _exp_t0 = time.perf_counter()

        n3mf = _get_n3mf()

        builder = n3mf.DocumentBuilder()
        builder.set_unit(n3mf.Unit.Millimeter)
        builder.set_language("en-US")

        builder.enable_production()
        builder.set_production_merge_objects(True)

        builder.add_namespace("BambuStudio", "http://schemas.bambulab.com/package/2021")
        builder.add_metadata("Application", self._get_app_version_str())
        builder.add_metadata("BambuStudio:3mfVersion", "1")
        builder.add_external_model_metadata("BambuStudio:3mfVersion", "1")

        materials = [
            n3mf.BaseMaterial(name, n3mf.Color(rgb[0], rgb[1], rgb[2])) for _, name, rgb in self.objects
        ]
        mat_group_id = builder.add_base_material_group(materials)

        object_ids: list[int] = []
        for idx, (mesh, name, _) in enumerate(self.objects):
            n3mf_mesh = n3mf.Mesh.from_arrays(
                np.ascontiguousarray(mesh.vertices, dtype=np.float64),
                np.ascontiguousarray(mesh.faces, dtype=np.int64),
            )
            obj_id = builder.add_mesh_object(name, n3mf_mesh, mat_group_id, idx)
            builder.add_build_item(obj_id)
            object_ids.append(obj_id)

        assembly_id = object_ids[-1] + 1 if object_ids else mat_group_id + 1
        self._inject_metadata_parts(builder, object_ids, assembly_id)

        doc = builder.build()

        opts = n3mf.WriteOptions()
        opts.vertex_precision = 6
        opts.compact_xml = True
        if self.watermark and hasattr(n3mf, "WatermarkConfig"):
            opts.watermark = n3mf.WatermarkConfig(payload=self.watermark.encode("utf-8"))
        elif self.watermark:
            n3mf_version = getattr(n3mf, "__version__", "unknown")
            print(
                "[BAMBU_3MF] Watermark disabled: "
                f"neroued_3mf {n3mf_version} does not provide WatermarkConfig"
            )

        n3mf.write_to_file(self.output_path, doc, opts)

        print(f"[BAMBU_3MF] [OK] Export complete: {self.output_path} ({time.perf_counter() - _exp_t0:.3f}s total)")
        return self.output_path

    # ------------------------------------------------------------------
    # Slicer version string
    # ------------------------------------------------------------------

    def _get_app_version_str(self) -> str:
        """Return slicer-appropriate Application version string.
        返回适配不同切片器的 Application 版本字符串。
        """
        _VERSION_MAP = {
            "SnapmakerOrca": "BambuStudio-2.2.4",
            "ElegooSlicer": "ElegooSlicer-1.3.2.9",
            "OrcaSlicer": "BambuStudio-2.3.2-rc2",
            "AnycubicSlicerNext": "BambuStudio-1.3.9.4",
        }
        return _VERSION_MAP.get(self.slicer, "BambuStudio-02.02.01.04")

    def _is_anycubic_slicer(self) -> bool:
        """Return whether the current export targets Anycubic Slicer Next.
        返回当前导出是否面向 Anycubic Slicer Next。
        """
        return self.slicer == "AnycubicSlicerNext"

    @staticmethod
    def _format_number(value: float) -> str:
        """Format a float for stable metadata output.
        将浮点数格式化为稳定的元数据输出字符串。
        """
        return format(float(value), ".15g")

    def _get_identify_id(self) -> str:
        """Return a slicer-specific plate identify_id value.
        返回切片器专属的 plate identify_id 值。
        """
        if self._is_anycubic_slicer():
            return "160"
        return "1"

    # ------------------------------------------------------------------
    # Bambu vendor metadata injection (CustomPart)
    # ------------------------------------------------------------------

    def _inject_metadata_parts(
        self,
        builder: _get_n3mf().DocumentBuilder,
        object_ids: list[int],
        assembly_id: int,
    ) -> None:
        """Inject all Bambu vendor metadata files into the 3MF via CustomPart.
        通过 CustomPart 向 3MF 中注入所有 Bambu 厂商元数据。
        """
        parts = [
            ("Metadata/model_settings.config", "text/xml", self._build_model_settings_bytes(object_ids, assembly_id)),
            ("Metadata/project_settings.config", "text/xml", self._build_project_settings_bytes()),
            ("Metadata/slice_info.config", "text/xml", self._build_slice_info_bytes()),
        ]
        if self._is_anycubic_slicer():
            parts.append(
                ("Metadata/custom_gcode_per_layer.xml", "text/xml", self._build_custom_gcode_per_layer_bytes())
            )
        else:
            parts.extend(
                [
                    ("Metadata/filament_sequence.json", "application/json", self._build_filament_sequence_bytes()),
                    ("Metadata/cut_information.xml", "text/xml", self._build_cut_information_bytes()),
                ]
            )
        for path, content_type, data in parts:
            builder.add_custom_part(_get_n3mf().CustomPart(path, content_type, data))

        builder.add_custom_content_type(_get_n3mf().CustomContentType("config", "text/xml"))
        builder.add_custom_content_type(_get_n3mf().CustomContentType("json", "application/json"))
        builder.add_custom_content_type(_get_n3mf().CustomContentType("xml", "text/xml"))

    # ------------------------------------------------------------------
    # Individual metadata builders (return bytes, no filesystem I/O)
    # ------------------------------------------------------------------

    def _build_model_settings_bytes(self, object_ids: list[int], assembly_id: int) -> bytes:
        """Build model_settings.config XML as bytes.
        构建 model_settings.config XML（字节形式）。
        """
        config = ET.Element("config")

        obj_elem = ET.SubElement(config, "object", attrib={"id": str(assembly_id)})
        ET.SubElement(obj_elem, "metadata", attrib={"key": "extruder", "value": "1"})

        source_file = os.path.basename(self.output_path)

        for idx, ((mesh, name, _), obj_id) in enumerate(zip(self.objects, object_ids)):
            bounds = np.asarray(getattr(mesh, "bounds", np.zeros((2, 3))), dtype=np.float64)
            if bounds.shape != (2, 3):
                bounds = np.zeros((2, 3), dtype=np.float64)
            center_x, center_y, center_z = bounds.mean(axis=0)
            max_x, max_y, max_z = bounds[1]
            matrix_value = (
                "1 0 0 "
                f"{self._format_number(max_x)} "
                "0 1 0 "
                f"{self._format_number(max_y)} "
                "0 0 1 "
                f"{self._format_number(max_z)} "
                "0 0 0 1"
            )
            part = ET.SubElement(obj_elem, "part", attrib={"id": str(obj_id), "subtype": "normal_part"})
            ET.SubElement(part, "metadata", attrib={"key": "name", "value": name})
            ET.SubElement(part, "metadata", attrib={"key": "matrix", "value": matrix_value})
            ET.SubElement(part, "metadata", attrib={"key": "source_file", "value": source_file})
            ET.SubElement(part, "metadata", attrib={"key": "source_object_id", "value": "0"})
            ET.SubElement(part, "metadata", attrib={"key": "source_volume_id", "value": str(idx)})
            ET.SubElement(part, "metadata", attrib={"key": "source_offset_x", "value": self._format_number(center_x)})
            ET.SubElement(part, "metadata", attrib={"key": "source_offset_y", "value": self._format_number(center_y)})
            ET.SubElement(part, "metadata", attrib={"key": "source_offset_z", "value": self._format_number(center_z)})
            ET.SubElement(part, "metadata", attrib={"key": "extruder", "value": str(idx + 1)})
            ET.SubElement(
                part,
                "mesh_stat",
                attrib={
                    "edges_fixed": "0",
                    "degenerate_facets": "0",
                    "facets_removed": "0",
                    "facets_reversed": "0",
                    "backwards_edges": "0",
                },
            )

        plate = ET.SubElement(config, "plate")
        ET.SubElement(plate, "metadata", attrib={"key": "plater_id", "value": "1"})
        ET.SubElement(plate, "metadata", attrib={"key": "plater_name", "value": ""})
        ET.SubElement(plate, "metadata", attrib={"key": "locked", "value": "false"})
        if not self._is_anycubic_slicer():
            ET.SubElement(plate, "metadata", attrib={"key": "filament_map_mode", "value": "Auto For Flush"})
        ET.SubElement(plate, "metadata", attrib={"key": "thumbnail_file", "value": "Metadata/plate_1.png"})
        ET.SubElement(
            plate, "metadata", attrib={"key": "thumbnail_no_light_file", "value": "Metadata/plate_no_light_1.png"}
        )
        ET.SubElement(plate, "metadata", attrib={"key": "top_file", "value": "Metadata/top_1.png"})
        ET.SubElement(plate, "metadata", attrib={"key": "pick_file", "value": "Metadata/pick_1.png"})

        model_instance = ET.SubElement(plate, "model_instance")
        ET.SubElement(model_instance, "metadata", attrib={"key": "object_id", "value": str(assembly_id)})
        ET.SubElement(model_instance, "metadata", attrib={"key": "instance_id", "value": "0"})
        ET.SubElement(model_instance, "metadata", attrib={"key": "identify_id", "value": self._get_identify_id()})

        tree = ET.ElementTree(config)
        ET.indent(tree, space="  ")

        buf = io.BytesIO()
        buf.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
        tree.write(buf, encoding="utf-8", xml_declaration=False)
        return buf.getvalue()

    def _build_project_settings_bytes(self) -> bytes:
        """Build project_settings.config JSON as bytes.
        构建 project_settings.config JSON（字节形式）。
        """
        num_colors = len(self.objects)

        settings = self._get_base_config_template()

        _RESIZABLE_ARRAY_KEYS = frozenset(
            [
                "nozzle_temperature",
                "nozzle_temperature_initial_layer",
                "nozzle_temperature_range_low",
                "nozzle_temperature_range_high",
                "bed_temperature",
                "bed_temperature_initial_layer",
                "activate_air_filtration",
                "additional_cooling_fan_speed",
                "chamber_temperatures",
                "close_fan_the_first_x_layers",
                "complete_print_exhaust_fan_speed",
                "cool_plate_temp",
                "cool_plate_temp_initial_layer",
                "during_print_exhaust_fan_speed",
                "eng_plate_temp",
                "eng_plate_temp_initial_layer",
                "fan_cooling_layer_time",
                "fan_max_speed",
                "fan_min_speed",
                "hot_plate_temp",
                "hot_plate_temp_initial_layer",
                "textured_plate_temp",
                "textured_plate_temp_initial_layer",
            ]
        )

        for key, value in settings.items():
            if isinstance(value, list) and len(value) > 0:
                if key.startswith("filament_") or key in _RESIZABLE_ARRAY_KEYS:
                    if len(value) != num_colors:
                        template_value = value[0] if value else "0"
                        settings[key] = [template_value] * num_colors

        settings.update(self._build_filament_arrays(num_colors))

        settings.setdefault("single_extruder_multi_material", "1")
        settings.setdefault("enable_prime_tower", "1")

        if self.settings:
            for key in [
                "layer_height",
                "initial_layer_height",
                "wall_loops",
                "top_shell_layers",
                "bottom_shell_layers",
                "sparse_infill_density",
                "sparse_infill_pattern",
                "print_speed",
                "travel_speed",
                "enable_support",
                "brim_width",
                "brim_type",
            ]:
                if key in self.settings:
                    settings[key] = self.settings[key]

        return json.dumps(settings, indent=4, ensure_ascii=False).encode("utf-8")

    def _build_slice_info_bytes(self) -> bytes:
        """Build slice_info.config XML as bytes.
        构建 slice_info.config XML（字节形式）。
        """
        config = ET.Element("config")
        header = ET.SubElement(config, "header")
        if self._is_anycubic_slicer():
            ET.SubElement(header, "header_item", attrib={"key": "X-ACNext-Client-Type", "value": "slicer"})
            ET.SubElement(
                header, "header_item", attrib={"key": "X-ACNext-Client-Version", "value": "1.3.9.4 20260319225535"}
            )
        else:
            ET.SubElement(header, "header_item", attrib={"key": "X-BBL-Client-Type", "value": "slicer"})
            ET.SubElement(header, "header_item", attrib={"key": "X-BBL-Client-Version", "value": "Lumina-1.6.3"})

        tree = ET.ElementTree(config)
        ET.indent(tree, space="  ")

        buf = io.BytesIO()
        buf.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
        tree.write(buf, encoding="utf-8", xml_declaration=False)
        return buf.getvalue()

    @staticmethod
    def _build_filament_sequence_bytes() -> bytes:
        """Build filament_sequence.json as bytes.
        构建 filament_sequence.json（字节形式）。
        """
        data = {"plate_1": {"sequence": []}}
        return json.dumps(data, ensure_ascii=False).encode("utf-8")

    @staticmethod
    def _build_cut_information_bytes() -> bytes:
        """Build cut_information.xml as bytes.
        构建 cut_information.xml（字节形式）。
        """
        config = ET.Element("objects")
        obj = ET.SubElement(config, "object", attrib={"id": "1"})
        ET.SubElement(obj, "cut_id", attrib={"id": "0", "check_sum": "1", "connectors_cnt": "0"})

        tree = ET.ElementTree(config)
        ET.indent(tree, space=" ")

        buf = io.BytesIO()
        buf.write(b'<?xml version="1.0" encoding="utf-8"?>\n')
        tree.write(buf, encoding="utf-8", xml_declaration=False)
        return buf.getvalue()

    @staticmethod
    def _build_custom_gcode_per_layer_bytes() -> bytes:
        """Build Anycubic custom_gcode_per_layer.xml as bytes.
        构建 Anycubic 的 custom_gcode_per_layer.xml（字节形式）。
        """
        config = ET.Element("custom_gcodes_per_layer")
        plate = ET.SubElement(config, "plate")
        ET.SubElement(plate, "plate_info", attrib={"id": "1"})
        ET.SubElement(plate, "mode", attrib={"value": "MultiExtruder"})

        tree = ET.ElementTree(config)
        ET.indent(tree, space="  ")

        buf = io.BytesIO()
        buf.write(b'<?xml version="1.0" encoding="utf-8"?>\n')
        tree.write(buf, encoding="utf-8", xml_declaration=False)
        return buf.getvalue()

    # ------------------------------------------------------------------
    # Config template & filament arrays (unchanged logic)
    # ------------------------------------------------------------------

    def _get_base_config_template(self) -> dict:
        """Get complete BambuStudio configuration template for the selected printer.
        获取所选机型的完整 BambuStudio 配置模板。

        Uses load_printer_template() to load printer-specific templates from
        printer_profiles/ directory, falling back to bambu_config_template.json.

        Returns:
            dict: Complete configuration template. (完整配置模板)
        """
        template = load_printer_template(self.printer_id, slicer=self.slicer)
        if template:
            return template

        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            template_path = os.path.join(sys._MEIPASS, "bambu_config_template.json")
        else:
            template_path = os.path.join(os.path.dirname(__file__), "..", "bambu_config_template.json")

        global _CONFIG_TEMPLATE_CACHE
        if os.path.exists(template_path):
            if _CONFIG_TEMPLATE_CACHE is None:
                with open(template_path, "r", encoding="utf-8") as f:
                    _CONFIG_TEMPLATE_CACHE = json.load(f)
            return copy.deepcopy(_CONFIG_TEMPLATE_CACHE)
        else:
            print("[WARNING] bambu_config_template.json not found, using minimal config")
            return self._get_minimal_config_template()

    @staticmethod
    def _get_minimal_config_template() -> dict:
        """Fallback minimal configuration template."""
        return {
            "layer_height": "0.08",
            "initial_layer_height": "0.08",
            "wall_loops": "1",
            "top_shell_layers": "0",
            "bottom_shell_layers": "0",
            "sparse_infill_density": "100%",
            "sparse_infill_pattern": "zig-zag",
            "nozzle_temperature": ["220"] * 8,
            "nozzle_temperature_initial_layer": ["220"] * 8,
        }

    def _build_filament_arrays(self, num_colors: int) -> dict:
        """Build filament-related arrays with length matching num_colors.
        构建长度匹配 num_colors 的耗材相关数组。

        Args:
            num_colors: Number of colors in the mode (2, 4, 6, or 8)

        Returns:
            dict: Filament arrays with correct lengths
        """
        arrays: dict[str, list] = {}

        arrays["filament_colour"] = []
        for _, _, color_rgb in self.objects:
            hex_color = f"#{color_rgb[0]:02X}{color_rgb[1]:02X}{color_rgb[2]:02X}"
            arrays["filament_colour"].append(hex_color)

        return arrays


# ======================================================================
# Public convenience function (signature unchanged from original)
# ======================================================================


def export_scene_with_bambu_metadata(
    scene: _get_trimesh().Scene,
    output_path: str,
    slot_names: List[str],
    preview_colors: Dict,
    settings: Optional[Dict] = None,
    color_mode: str = "4-Color",
    printer_id: str = "bambu-h2d",
    slicer: str = "BambuStudio",
    watermark: str = "LuminaStudio",
):
    """Export a Trimesh scene to BambuStudio/OrcaSlicer-compatible 3MF with metadata.
    将 Trimesh 场景导出为 BambuStudio/OrcaSlicer 兼容的 3MF 文件（含元数据）。

    Args:
        scene (_get_trimesh().Scene): Trimesh Scene containing all meshes. (包含所有网格的场景)
        output_path (str): Output .3mf file path. (输出 .3mf 文件路径)
        slot_names (List[str]): Actually used material names. (实际使用的材料名称列表)
        preview_colors (Dict): Material ID to RGBA color mapping. (材料 ID 到 RGBA 颜色映射)
        settings (Optional[Dict]): Custom print settings. (自定义打印设置)
        color_mode (str): Color mode ('4-Color', '6-Color', '8-Color', 'BW'). (颜色模式)
        printer_id (str): Printer identifier for template selection, default 'bambu-h2d'. (打印机标识)
        slicer (str): Slicer software identifier, default 'BambuStudio'. (切片器标识)
        watermark (str): Watermark text embedded in the 3MF ZIP structure. (嵌入 3MF ZIP 结构的水印文本)

    Returns:
        str: Path to the exported 3MF file. (导出的 3MF 文件路径)
    """
    if scene is None:
        raise ValueError("[BAMBU_3MF] Scene is None")
    if not slot_names:
        raise ValueError("[BAMBU_3MF] slot_names is empty - no exportable objects")

    num_used_colors = len(slot_names)

    if num_used_colors <= 2:
        actual_color_mode = "BW"
    elif num_used_colors <= 4:
        actual_color_mode = "4-Color"
    elif num_used_colors <= 6:
        actual_color_mode = "6-Color"
    else:
        actual_color_mode = "8-Color"

    print(
        f"[BAMBU_3MF] LUT color_mode: {color_mode}, Actual colors used: {num_used_colors} → 3MF mode: {actual_color_mode}"
    )

    writer = BambuStudio3MFWriter(
        output_path, settings, actual_color_mode,
        printer_id=printer_id, slicer=slicer, watermark=watermark,
    )

    name_to_color: dict[str, tuple] = {}
    print("[BAMBU_3MF] Building color mapping:")
    for idx, slot_name in enumerate(slot_names):
        if slot_name in preview_colors:
            name_to_color[slot_name] = tuple(preview_colors[slot_name][:3])
            print(f"[BAMBU_3MF]   {idx}: '{slot_name}' -> RGB{name_to_color[slot_name]} (by name)")
        elif idx in preview_colors:
            name_to_color[slot_name] = tuple(preview_colors[idx][:3])
            print(f"[BAMBU_3MF]   {idx}: '{slot_name}' -> RGB{name_to_color[slot_name]} (by ID)")
        else:
            name_to_color[slot_name] = (200, 200, 200)
            print(f"[BAMBU_3MF]   {idx}: '{slot_name}' -> RGB(200,200,200) (fallback)")

    print(f"[BAMBU_3MF] Color mapping complete: {list(name_to_color.keys())}")

    print("[BAMBU_3MF] Adding meshes to 3MF:")
    unmatched = []
    slot_debug = []
    for idx, slot_name in enumerate(slot_names):
        mesh = scene.geometry.get(slot_name)
        if mesh is None:
            unmatched.append(slot_name)
            slot_debug.append(
                {
                    "slot_name": slot_name,
                    "found": False,
                    "vertices": 0,
                    "faces": 0,
                    "color_rgb": list(name_to_color.get(slot_name, (200, 200, 200))),
                }
            )
            print(f"[BAMBU_3MF]   {idx}: '{slot_name}' - NOT FOUND in scene")
            continue

        color_rgb = name_to_color.get(slot_name, (200, 200, 200))
        vertices = getattr(mesh, "vertices", None)
        faces = getattr(mesh, "faces", None)
        slot_debug.append(
            {
                "slot_name": slot_name,
                "found": True,
                "vertices": len(vertices) if vertices is not None else 0,
                "faces": len(faces) if faces is not None else 0,
                "color_rgb": list(color_rgb),
            }
        )
        writer.add_mesh(mesh, slot_name, color_rgb)
        print(f"[BAMBU_3MF]   {idx}: '{slot_name}' -> RGB{color_rgb} (added to 3MF)")

    # region agent log
    _agent_debug_write(
        hypothesis_id="D",
        location="utils/bambu_3mf_writer.py:export_scene_with_bambu_metadata",
        message="3MF slot-to-scene mapping summary",
        data={
            "output_path": output_path,
            "slot_names": slot_names,
            "actual_color_mode": actual_color_mode,
            "writer_object_count": len(writer.objects),
            "unmatched": unmatched,
            "slot_debug": slot_debug,
        },
    )
    # endregion

    if unmatched:
        raise ValueError("[BAMBU_3MF] Missing geometries for slot names: " + ", ".join(unmatched))

    return writer.export()
