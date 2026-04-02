"""
Lumina Studio - Native Vector Engine (v2 - Chroma-aligned)

SVG to 3D mesh conversion using vector geometry operations.
Aligned with ChromaPrint3D's processing philosophy:

Pipeline:
    SVG → Parse Paths → Occlusion Clip → Match Colors → Run-Length Extrude
        → Silhouette Backing → (optional Double-sided) → Assemble Scene

Key changes from v1:
    - Per-shape reverse-order occlusion clipping (no "small feature" exemptions)
    - Per-unique-color recipe caching via LUT KDTree
    - Run-length layer extrusion (consecutive same-channel layers merged)
    - No micro Z-offset between overlapping colors on the same material
    - Output objects sorted by material ID for stable slicer ordering
"""

import os
import re
import logging
import json
import numpy as np
import time
import xml.etree.ElementTree as ET
import trimesh
import cv2
from dataclasses import dataclass, field
from svgelements import SVG, Path, Shape, Move, Line, Close, CubicBezier, QuadraticBezier, Color
from shapely.geometry import Polygon, MultiPolygon
from shapely import affinity
from shapely.ops import unary_union
from shapely.strtree import STRtree
from shapely.validation import make_valid

from config import PrinterConfig, ColorSystem

_log = logging.getLogger(__name__)

MIN_SHAPE_AREA_MM2 = 0.01
BASE_COLOR_GAP_MM = 0.005
_MAX_BEZIER_DEPTH = 16
_AGENT_DEBUG_LOG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "debug-ab5259.log")
_AGENT_DEBUG_SESSION_ID = "ab5259"
_AGENT_DEBUG_TARGET_RGB = (122, 135, 119)
_AGENT_DEBUG_TARGET_HEX = "#7a8777"
_AGENT_DEBUG_EXTRUDE_FAILURE_LIMIT = 5
_AGENT_DEBUG_EXTRUDE_FAILURES = 0
_AGENT_DEBUG_PARSE_EXAMPLE_LIMIT = 12
_AGENT_DEBUG_OCCLUSION_EXAMPLE_LIMIT = 12


def _agent_debug_rgb_to_hex(rgb):
    """Return a stable lowercase hex string for RGB tuples."""
    try:
        return f"#{int(rgb[0]) & 255:02x}{int(rgb[1]) & 255:02x}{int(rgb[2]) & 255:02x}"
    except Exception:
        return None


def _agent_debug_geom_area(geom):
    """Return geometry area for debug summaries."""
    try:
        return float(getattr(geom, "area", 0.0) or 0.0)
    except Exception:
        return 0.0


def _agent_debug_shape_summary(items, geometry_key, limit=8):
    """Summarise shape counts and areas by source colour."""
    buckets = {}
    for item in items or []:
        hex_color = _agent_debug_rgb_to_hex(item.get("color"))
        if hex_color is None:
            continue
        bucket = buckets.setdefault(hex_color, {"count": 0, "area": 0.0})
        bucket["count"] += 1
        bucket["area"] += _agent_debug_geom_area(item.get(geometry_key))

    target = buckets.get(_AGENT_DEBUG_TARGET_HEX, {"count": 0, "area": 0.0})
    top_colors = []
    for hex_color, bucket in sorted(buckets.items(), key=lambda kv: (-kv[1]["area"], kv[0]))[:limit]:
        top_colors.append(
            {
                "hex": hex_color,
                "count": int(bucket["count"]),
                "area": round(float(bucket["area"]), 4),
            }
        )

    return {
        "shape_count": len(items or []),
        "unique_colors": len(buckets),
        "target_color": {
            "hex": _AGENT_DEBUG_TARGET_HEX,
            "present": _AGENT_DEBUG_TARGET_HEX in buckets,
            "count": int(target["count"]),
            "area": round(float(target["area"]), 4),
        },
        "top_colors_by_area": top_colors,
    }


def _agent_debug_match_summary(items, limit=8):
    """Summarise matched LUT colours, recipes, and source SVG colours."""
    buckets = {}
    for item in items or []:
        matched_hex = _agent_debug_rgb_to_hex(item.get("matched_rgb"))
        source_hex = _agent_debug_rgb_to_hex(item.get("color"))
        if matched_hex is None:
            continue
        bucket = buckets.setdefault(
            matched_hex,
            {"count": 0, "area": 0.0, "recipes": set(), "source_colors": {}},
        )
        geom_area = _agent_debug_geom_area(item.get("geometry"))
        bucket["count"] += 1
        bucket["area"] += geom_area
        recipe = item.get("recipe") or []
        bucket["recipes"].add(tuple(int(v) for v in recipe))
        if source_hex is not None:
            src = bucket["source_colors"].setdefault(source_hex, {"count": 0, "area": 0.0})
            src["count"] += 1
            src["area"] += geom_area

    def _source_colors_payload(source_colors, source_limit=6):
        rows = []
        for source_hex, data in sorted(source_colors.items(), key=lambda kv: (-kv[1]["area"], kv[0]))[:source_limit]:
            rows.append(
                {
                    "hex": source_hex,
                    "count": int(data["count"]),
                    "area": round(float(data["area"]), 4),
                }
            )
        return rows

    target = buckets.get(
        _AGENT_DEBUG_TARGET_HEX,
        {"count": 0, "area": 0.0, "recipes": set(), "source_colors": {}},
    )
    top_colors = []
    for matched_hex, bucket in sorted(buckets.items(), key=lambda kv: (-kv[1]["area"], kv[0]))[:limit]:
        top_colors.append(
            {
                "hex": matched_hex,
                "count": int(bucket["count"]),
                "area": round(float(bucket["area"]), 4),
                "recipes": [list(recipe) for recipe in sorted(bucket["recipes"])[:3]],
                "source_colors": _source_colors_payload(bucket["source_colors"]),
            }
        )

    return {
        "shape_count": len(items or []),
        "unique_colors": len(buckets),
        "target_color": {
            "hex": _AGENT_DEBUG_TARGET_HEX,
            "present": _AGENT_DEBUG_TARGET_HEX in buckets,
            "count": int(target["count"]),
            "area": round(float(target["area"]), 4),
            "recipes": [list(recipe) for recipe in sorted(target["recipes"])[:5]],
            "source_colors": _source_colors_payload(target["source_colors"]),
        },
        "top_colors_by_area": top_colors,
    }


def _agent_debug_scene_summary(scene):
    """Summarise scene geometry before export."""
    geometries = []
    for name in sorted(scene.geometry.keys()):
        geom = scene.geometry[name]
        vertices = getattr(geom, "vertices", None)
        faces = getattr(geom, "faces", None)
        bounds = getattr(geom, "bounds", None)
        bounds_list = None
        try:
            if bounds is not None:
                bounds_arr = np.asarray(bounds, dtype=np.float64)
                if bounds_arr.shape == (2, 3):
                    bounds_list = np.round(bounds_arr, 4).tolist()
        except Exception:
            bounds_list = None
        geometries.append(
            {
                "name": name,
                "vertices": len(vertices) if vertices is not None else 0,
                "faces": len(faces) if faces is not None else 0,
                "bounds": bounds_list,
            }
        )
    return {"object_count": len(scene.geometry), "geometries": geometries}


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


def _flatten_cubic(
    x0, y0, x1, y1, x2, y2, x3, y3, tolerance, out, depth,
):
    """Adaptive de Casteljau subdivision for cubic Bézier curves.

    Appends flattened points to *out*.  Mirrors the algorithm used
    by ``ChromaPrint3D::FlattenCubicBezier``.
    """
    bx = x3 - x0
    by = y3 - y0
    d1 = abs((x1 - x3) * by - (y1 - y3) * bx)
    d2 = abs((x2 - x3) * by - (y2 - y3) * bx)
    len_sq = bx * bx + by * by
    tol_sq = tolerance * tolerance * len_sq
    if (d1 + d2) * (d1 + d2) <= tol_sq or depth >= _MAX_BEZIER_DEPTH:
        out.append((x3, y3))
        return
    m01x = (x0 + x1) * 0.5;  m01y = (y0 + y1) * 0.5
    m12x = (x1 + x2) * 0.5;  m12y = (y1 + y2) * 0.5
    m23x = (x2 + x3) * 0.5;  m23y = (y2 + y3) * 0.5
    m012x = (m01x + m12x) * 0.5;  m012y = (m01y + m12y) * 0.5
    m123x = (m12x + m23x) * 0.5;  m123y = (m12y + m23y) * 0.5
    mx = (m012x + m123x) * 0.5;   my = (m012y + m123y) * 0.5
    _flatten_cubic(x0, y0, m01x, m01y, m012x, m012y, mx, my, tolerance, out, depth + 1)
    _flatten_cubic(mx, my, m123x, m123y, m23x, m23y, x3, y3, tolerance, out, depth + 1)


def _flatten_quadratic(
    x0, y0, x1, y1, x2, y2, tolerance, out, depth,
):
    """Adaptive de Casteljau subdivision for quadratic Bézier curves."""
    bx = x2 - x0
    by = y2 - y0
    d = abs((x1 - x2) * by - (y1 - y2) * bx)
    len_sq = bx * bx + by * by
    if d * d <= tolerance * tolerance * len_sq or depth >= _MAX_BEZIER_DEPTH:
        out.append((x2, y2))
        return
    m01x = (x0 + x1) * 0.5;  m01y = (y0 + y1) * 0.5
    m12x = (x1 + x2) * 0.5;  m12y = (y1 + y2) * 0.5
    mx = (m01x + m12x) * 0.5;  my = (m01y + m12y) * 0.5
    _flatten_quadratic(x0, y0, m01x, m01y, mx, my, tolerance, out, depth + 1)
    _flatten_quadratic(mx, my, m12x, m12y, x2, y2, tolerance, out, depth + 1)


def _sample_gradient_stops(stops, t):
    """Interpolate colour at parameter *t* along a gradient stop list."""
    if not stops:
        return (128, 128, 128)
    if t <= stops[0][0]:
        return stops[0][1]
    if t >= stops[-1][0]:
        return stops[-1][1]
    for i in range(len(stops) - 1):
        t0, c0 = stops[i]
        t1, c1 = stops[i + 1]
        if t0 <= t <= t1:
            if t1 - t0 < 1e-9:
                return c0
            f = (t - t0) / (t1 - t0)
            return (
                int(c0[0] + (c1[0] - c0[0]) * f),
                int(c0[1] + (c1[1] - c0[1]) * f),
                int(c0[2] + (c1[2] - c0[2]) * f),
            )
    return stops[-1][1]


def _parse_svg_transform(transform_str):
    """Parse an SVG ``transform`` attribute into a 3x3 affine matrix.

    Supports ``translate``, ``scale``, ``rotate``, ``matrix``,
    ``skewX`` and ``skewY``, including concatenated transforms.

    解析 SVG transform 属性字符串为 3×3 仿射矩阵，
    支持 translate/scale/rotate/matrix/skewX/skewY 及其组合。
    """
    if not transform_str:
        return np.eye(3, dtype=np.float64)

    result = np.eye(3, dtype=np.float64)
    _tf_re = re.compile(
        r"(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)"
    )

    for match in _tf_re.finditer(transform_str):
        func = match.group(1)
        args = [float(v) for v in re.split(r"[\s,]+", match.group(2).strip()) if v]
        m = np.eye(3, dtype=np.float64)

        if func == "translate":
            m[0, 2] = args[0] if len(args) >= 1 else 0.0
            m[1, 2] = args[1] if len(args) >= 2 else 0.0
        elif func == "scale":
            sx = args[0] if len(args) >= 1 else 1.0
            m[0, 0] = sx
            m[1, 1] = args[1] if len(args) >= 2 else sx
        elif func == "rotate":
            angle = np.radians(args[0]) if args else 0.0
            cos_a, sin_a = np.cos(angle), np.sin(angle)
            if len(args) >= 3:
                cx, cy = args[1], args[2]
                m[0, 0] = cos_a;  m[0, 1] = -sin_a
                m[0, 2] = cx - cos_a * cx + sin_a * cy
                m[1, 0] = sin_a;  m[1, 1] = cos_a
                m[1, 2] = cy - sin_a * cx - cos_a * cy
            else:
                m[0, 0] = cos_a;  m[0, 1] = -sin_a
                m[1, 0] = sin_a;  m[1, 1] = cos_a
        elif func == "matrix" and len(args) >= 6:
            m[0, 0] = args[0];  m[1, 0] = args[1]
            m[0, 1] = args[2];  m[1, 1] = args[3]
            m[0, 2] = args[4];  m[1, 2] = args[5]
        elif func == "skewX" and args:
            m[0, 1] = np.tan(np.radians(args[0]))
        elif func == "skewY" and args:
            m[1, 0] = np.tan(np.radians(args[0]))

        result = result @ m

    return result


def _parse_gradient_length(val, default=0.0):
    """Parse an SVG gradient coordinate value, handling ``%`` suffix.

    解析 SVG 渐变坐标值，支持百分比后缀。
    """
    if val is None:
        return default
    s = str(val).strip()
    if not s:
        return default
    try:
        if s.endswith("%"):
            return float(s[:-1]) / 100.0
        return float(s)
    except (ValueError, TypeError):
        return default


# Lazy import to avoid circular dependency at module load time
_LuminaImageProcessor = None
_VECTOR_PARSE_CLIP_CACHE = {}
_VECTOR_PARSE_CLIP_CACHE_MAX = 3


def _get_image_processor_class():
    global _LuminaImageProcessor
    if _LuminaImageProcessor is None:
        from core.image_processing import LuminaImageProcessor

        _LuminaImageProcessor = LuminaImageProcessor
    return _LuminaImageProcessor


@dataclass
class VectorAnalysis:
    """Intermediate result of SVG parsing, clipping, and color matching.
    SVG 解析、裁剪、配色的中间结果 — 预览与 3D 构建共享。

    Produced by ``VectorProcessor.analyze_svg`` and consumed by both
    ``build_mesh`` (3D extrusion) and ``render_preview`` (2D raster).
    """

    shape_data: list
    clipped_shapes: list
    matched_shapes: list
    silhouette: object  # Polygon | MultiPolygon | None
    scale_factor: float
    bbox: tuple  # (gx0, gy0, real_w, real_h) in SVG user units
    color_conf: dict
    slot_names: list
    num_channels: int
    num_layers: int
    preview_colors: dict
    stage_timings: dict = field(default_factory=dict)


class VectorProcessor:
    """
    Native vector processing engine for SVG files.

    Converts SVG directly to 3D meshes without rasterization,
    preserving vector precision.  Uses ChromaPrint3D-style
    occlusion clipping and run-length layer extrusion.

    Attributes:
        color_mode: Color system mode string forwarded to ColorSystem.
        img_processor: LuminaImageProcessor instance for LUT / KDTree access.
        sampling_precision: Curve approximation precision in mm.
    """

    def __init__(self, lut_path: str, color_mode: str):
        self.color_mode = color_mode
        print(f"[VECTOR] Initializing Native Vector Engine ({color_mode})...")

        ImageProcessor = _get_image_processor_class()
        self.img_processor = ImageProcessor(lut_path, color_mode)
        self.sampling_precision = 0.02  # mm
        self.last_stage_timings = {}
        self.parse_warnings: list[str] = []

        print(f"[VECTOR] Initialized with {len(self.img_processor.ref_stacks)} LUT colors")

    # ── Geometry pre-processing helpers ─────────────────────────────────

    @staticmethod
    def _normalize_contours(geom, close_delta_mm=0.03):
        """Morphological close: inflate -> deflate to fill micro-gaps.

        Mirrors ``ChromaPrint3D::NormalizeContours`` (Clipper2 inflate/deflate).
        Uses Shapely ``buffer`` as an equivalent operation.
        """
        if geom is None or geom.is_empty:
            return geom
        try:
            inflated = geom.buffer(close_delta_mm, join_style="mitre", mitre_limit=2.0)
            if inflated.is_empty:
                return geom
            deflated = inflated.buffer(-close_delta_mm, join_style="mitre", mitre_limit=2.0)
            if deflated.is_empty:
                return geom
            return make_valid(deflated)
        except Exception:
            return geom

    @staticmethod
    def _filter_backing_holes(geom, min_hole_area_mm2=1.0):
        """Remove small holes from the backing plate polygon.

        Mirrors ``ChromaPrint3D``'s ``base_min_hole_area_mm2`` filtering.
        """
        if geom is None or geom.is_empty:
            return geom
        if geom.geom_type == "Polygon":
            kept = [h for h in geom.interiors if Polygon(h).area >= min_hole_area_mm2]
            return Polygon(geom.exterior, kept)
        if geom.geom_type == "MultiPolygon":
            polys = []
            for p in geom.geoms:
                kept = [h for h in p.interiors if Polygon(h).area >= min_hole_area_mm2]
                polys.append(Polygon(p.exterior, kept))
            return MultiPolygon(polys)
        return geom

    @staticmethod
    def _split_disconnected_shapes(shape_data):
        """Split MultiPolygon / GeometryCollection shapes into individual Polygons.

        Mirrors ``ChromaPrint3D::SplitDisconnectedShapes``.  Shapely already
        distinguishes exterior rings from holes inside ``Polygon`` objects, so
        no explicit containment-depth analysis is needed.
        """
        result = []
        for item in shape_data:
            geom = item["poly"]
            if geom is None or geom.is_empty:
                continue
            if geom.geom_type == "Polygon":
                if geom.area >= MIN_SHAPE_AREA_MM2:
                    result.append(item)
            elif geom.geom_type == "MultiPolygon":
                for poly in geom.geoms:
                    if not poly.is_empty and poly.area >= MIN_SHAPE_AREA_MM2:
                        result.append({**item, "poly": poly})
            elif geom.geom_type == "GeometryCollection":
                for g in geom.geoms:
                    if g.is_empty or not hasattr(g, "area") or g.area < MIN_SHAPE_AREA_MM2:
                        continue
                    if g.geom_type == "Polygon":
                        result.append({**item, "poly": g})
                    elif g.geom_type == "MultiPolygon":
                        for poly in g.geoms:
                            if not poly.is_empty and poly.area >= MIN_SHAPE_AREA_MM2:
                                result.append({**item, "poly": poly})
        return result

    @staticmethod
    def _extract_polygonal_geometry(geom):
        """Return only polygonal parts from arbitrary Shapely geometry.

        ``make_valid()`` can turn self-intersecting filled SVG paths into a
        ``GeometryCollection`` containing a ``MultiPolygon`` plus stray line
        segments.  The vector parser must preserve those polygonal parts
        instead of dropping the whole element.
        """
        if geom is None or geom.is_empty:
            return None
        if geom.geom_type in ("Polygon", "MultiPolygon"):
            return geom
        if geom.geom_type != "GeometryCollection":
            return None

        polygon_parts = []
        for child in geom.geoms:
            extracted = VectorProcessor._extract_polygonal_geometry(child)
            if extracted is None or extracted.is_empty:
                continue
            if extracted.geom_type == "Polygon":
                polygon_parts.append(extracted)
            elif extracted.geom_type == "MultiPolygon":
                polygon_parts.extend([poly for poly in extracted.geoms if not poly.is_empty])

        if not polygon_parts:
            return None
        if len(polygon_parts) == 1:
            return polygon_parts[0]

        try:
            merged = unary_union(polygon_parts)
            return merged if merged is not None and not merged.is_empty else MultiPolygon(polygon_parts)
        except Exception:
            return MultiPolygon(polygon_parts)

    @staticmethod
    def _parse_gradient_defs(svg_path):
        """Pre-parse SVG XML to extract gradient definitions.

        Returns ``{gradient_id: {type, stops, units, transform, ...}}``
        for linear and radial gradients.

        Handles ``gradientUnits``, ``gradientTransform``,
        ``xlink:href`` / ``href`` inheritance, percentage coordinate
        values, and ``stop-color`` defined via the ``style`` attribute.

        解析 SVG XML 提取渐变定义，支持坐标变换、单位、继承、
        百分比值和 style 属性中的 stop-color。
        """
        _SVG_NS = {"svg": "http://www.w3.org/2000/svg"}
        _XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
        gradients = {}
        try:
            tree = ET.parse(svg_path)
            root = tree.getroot()
        except Exception:
            return gradients

        def _parse_stops(parent):
            stops = []
            for s in parent.findall("svg:stop", _SVG_NS):
                raw_off = s.get("offset", "0")
                offset = float(raw_off.rstrip("%")) / (
                    100.0 if "%" in raw_off else 1.0
                )
                raw_c = s.get("stop-color")
                if not raw_c:
                    style = s.get("style", "")
                    m = re.search(r"stop-color\s*:\s*([^;]+)", style)
                    if m:
                        raw_c = m.group(1).strip()
                if not raw_c:
                    raw_c = "black"
                try:
                    c = Color(raw_c)
                    rgb = (int(c.red), int(c.green), int(c.blue))
                except Exception:
                    rgb = (0, 0, 0)
                stops.append((offset, rgb))
            return stops

        elem_map = {}
        for tag in ("linearGradient", "radialGradient"):
            for elem in root.iter(f"{{http://www.w3.org/2000/svg}}{tag}"):
                gid = elem.get("id")
                if gid:
                    elem_map[gid] = elem

        def _resolve(gid, visited=None):
            if visited is None:
                visited = set()
            if gid in gradients:
                return gradients[gid]
            if gid not in elem_map or gid in visited:
                return None
            visited.add(gid)

            elem = elem_map[gid]
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

            href = elem.get(_XLINK_HREF) or elem.get("href")
            href_id = href.lstrip("#") if href else None
            parent = _resolve(href_id, visited) if href_id else None

            stops = _parse_stops(elem)
            if not stops and parent:
                stops = parent.get("stops", [])

            raw_units = elem.get("gradientUnits")
            if raw_units is None and parent:
                raw_units = parent.get("units")
            units = raw_units if raw_units in ("userSpaceOnUse", "objectBoundingBox") else "objectBoundingBox"

            raw_tf = elem.get("gradientTransform")
            if raw_tf is not None:
                transform = _parse_svg_transform(raw_tf)
            elif parent is not None:
                transform = parent.get("transform", np.eye(3, dtype=np.float64))
            else:
                transform = np.eye(3, dtype=np.float64)

            def _coord(attr, default):
                val = elem.get(attr)
                if val is not None:
                    return _parse_gradient_length(val, default)
                if parent is not None:
                    return parent.get(attr, default)
                return default

            if tag == "linearGradient":
                info = {
                    "type": "linear",
                    "x1": _coord("x1", 0.0), "y1": _coord("y1", 0.0),
                    "x2": _coord("x2", 1.0), "y2": _coord("y2", 0.0),
                    "stops": stops, "units": units, "transform": transform,
                }
            elif tag == "radialGradient":
                info = {
                    "type": "radial",
                    "cx": _coord("cx", 0.5), "cy": _coord("cy", 0.5),
                    "r": _coord("r", 0.5),
                    "stops": stops, "units": units, "transform": transform,
                }
            else:
                return None

            gradients[gid] = info
            return info

        for gid in elem_map:
            _resolve(gid)

        return gradients

    @staticmethod
    def _flatten_gradient_shape(grad_info, subpath_polys):
        """Convert a gradient-filled SVG element into multiple solid-color shapes.

        Algorithm (mirrors ``ChromaPrint3D::FlattenGradientShape``):
        1. Rasterise the gradient inside the element's bounding box
        2. Quantise each pixel to the nearest gradient stop colour
        3. Extract contours per stop colour via OpenCV ``findContours``
        4. Convert pixel contours back to SVG coordinate polygons

        Correctly handles ``gradientUnits`` (``objectBoundingBox`` vs
        ``userSpaceOnUse``) and ``gradientTransform``.

        Args:
            grad_info: Gradient definition dict from ``_parse_gradient_defs``.
            subpath_polys: List of Shapely Polygon objects for the element.

        Returns list of ``{poly: Polygon, color: (r,g,b)}`` dicts.
        Falls back to sampling the gradient centre colour if extraction fails.
        """
        stops = grad_info.get("stops", [])
        if not stops:
            return []

        union_poly = unary_union(subpath_polys) if subpath_polys else None
        if union_poly is None or union_poly.is_empty:
            return []

        bx0, by0, bx1, by1 = union_poly.bounds
        bw = bx1 - bx0
        bh = by1 - by0
        if bw <= 0 or bh <= 0:
            return []

        units = grad_info.get("units", "objectBoundingBox")
        transform = grad_info.get("transform", np.eye(3, dtype=np.float64))

        def _map_point(x, y):
            """Map gradient-space coords to SVG user-space coords."""
            if units == "objectBoundingBox":
                x = bx0 + x * bw
                y = by0 + y * bh
            pt = transform @ np.array([x, y, 1.0], dtype=np.float64)
            return float(pt[0]), float(pt[1])

        def _map_radius(r):
            if units == "objectBoundingBox":
                r = r * (bw + bh) * 0.5
            sx = np.sqrt(transform[0, 0] ** 2 + transform[1, 0] ** 2)
            sy = np.sqrt(transform[0, 1] ** 2 + transform[1, 1] ** 2)
            return r * (sx + sy) * 0.5

        _MAX_GRAD_PX = 2048
        px_per_unit = min(10.0, _MAX_GRAD_PX / max(bw, bh))
        img_w = max(4, int(bw * px_per_unit))
        img_h = max(4, int(bh * px_per_unit))

        ys = np.arange(img_h)[:, None]
        xs = np.arange(img_w)[None, :]
        wx = bx0 + (xs + 0.5) / px_per_unit
        wy = by0 + (ys + 0.5) / px_per_unit

        grad_type = grad_info["type"]
        if grad_type == "linear":
            gx1, gy1 = _map_point(grad_info["x1"], grad_info["y1"])
            gx2, gy2 = _map_point(grad_info["x2"], grad_info["y2"])
            dx = gx2 - gx1
            dy = gy2 - gy1
            length_sq = dx * dx + dy * dy
            if length_sq < 1e-12:
                t_map = np.zeros((img_h, img_w), dtype=np.float32)
            else:
                t_map = ((wx - gx1) * dx + (wy - gy1) * dy) / length_sq
        elif grad_type == "radial":
            cx, cy = _map_point(grad_info["cx"], grad_info["cy"])
            r_grad = _map_radius(grad_info["r"])
            if r_grad < 1e-12:
                r_grad = max(bw, bh) / 2
            t_map = np.sqrt((wx - cx) ** 2 + (wy - cy) ** 2) / r_grad
        else:
            mid_color = _sample_gradient_stops(stops, 0.5)
            return [{"poly": union_poly, "color": mid_color}]

        t_map = np.clip(t_map, 0.0, 1.0).astype(np.float32)

        canvas = np.zeros((img_h, img_w, 3), dtype=np.uint8)
        for i in range(len(stops) - 1):
            t0, c0 = stops[i]
            t1, c1 = stops[i + 1]
            mask = (t_map >= t0) & (t_map <= t1)
            if not np.any(mask):
                continue
            if t1 - t0 < 1e-9:
                f = np.zeros_like(t_map)
            else:
                f = (t_map - t0) / (t1 - t0)
            for ch in range(3):
                canvas[:, :, ch] = np.where(
                    mask,
                    (c0[ch] + (c1[ch] - c0[ch]) * f).astype(np.uint8),
                    canvas[:, :, ch],
                )
        below = t_map < stops[0][0]
        above = t_map > stops[-1][0]
        for ch in range(3):
            canvas[:, :, ch] = np.where(below, stops[0][1][ch], canvas[:, :, ch])
            canvas[:, :, ch] = np.where(above, stops[-1][1][ch], canvas[:, :, ch])

        stop_colors = np.array([s[1] for s in stops], dtype=np.int16)
        flat = canvas.reshape(-1, 3).astype(np.int16)
        diffs = np.linalg.norm(
            flat[:, None, :] - stop_colors[None, :, :],
            axis=2,
        )
        quantized_idx = diffs.argmin(axis=1).reshape(img_h, img_w)

        result_shapes = []
        for si, (_, scolor) in enumerate(stops):
            mask = (quantized_idx == si).astype(np.uint8) * 255
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for cnt in contours:
                if cv2.contourArea(cnt) < 4:
                    continue
                approx = cv2.approxPolyDP(cnt, 1.0, True)
                if len(approx) < 3:
                    continue
                svg_coords = [
                    (bx0 + pt[0] / px_per_unit, by0 + pt[1] / px_per_unit)
                    for pt in approx[:, 0, :]
                ]
                poly = Polygon(svg_coords)
                if poly.is_valid and not poly.is_empty and poly.area > 0:
                    try:
                        clipped = poly.intersection(union_poly)
                    except Exception:
                        clipped = poly
                    if not clipped.is_empty:
                        result_shapes.append({"poly": clipped, "color": scolor})

        if not result_shapes:
            mid_color = _sample_gradient_stops(stops, 0.5)
            return [{"poly": union_poly, "color": mid_color}]

        return result_shapes

    # ── Public entry points ─────────────────────────────────────────────

    def analyze_svg(
        self,
        svg_path: str,
        target_width_mm: float,
        color_replacements: dict = None,
        progress_fn=None,
    ) -> VectorAnalysis:
        """Parse, clip, and color-match an SVG — shared by preview and mesh.
        解析、裁剪、配色 SVG — 预览与 3D 构建共享此结果。

        Args:
            svg_path:         Path to SVG file.
            target_width_mm:  Physical width in mm for the output model.
            color_replacements: Optional ``{hex: hex}`` replacement map.
            progress_fn:      Optional progress callback.

        Returns:
            A ``VectorAnalysis`` containing all intermediate data needed
            by ``build_mesh`` and ``render_preview``.
        """
        print(f"[VECTOR] Analyzing: {svg_path}")
        stage_timings = {}

        # === Stage 1+2: Parse & Occlusion clip (with cache) ===
        cache_key = None
        cached_entry = None
        try:
            svg_abs = os.path.abspath(svg_path)
            svg_mtime = os.path.getmtime(svg_abs)
            cache_key = (
                svg_abs,
                round(float(target_width_mm), 4),
                round(float(self.sampling_precision), 4),
                svg_mtime,
            )
            cached_entry = _VECTOR_PARSE_CLIP_CACHE.get(cache_key)
        except Exception:
            cache_key = None

        if cached_entry is not None:
            shape_data = cached_entry["shape_data"]
            clipped_shapes = cached_entry["clipped_shapes"]
            silhouette = cached_entry["silhouette"]
            scale_factor = cached_entry["scale_factor"]
            bbox = cached_entry["bbox"]
            stage_timings["parse_s"] = 0.0
            stage_timings["occlusion_s"] = 0.0
            print(f"[VECTOR] Parse/clip cache hit: {os.path.basename(svg_path)}")
            print(f"[VECTOR] Parsed {len(shape_data)} shapes. Scale: {scale_factor:.4f}")
            print(f"[VECTOR] After occlusion clip: {len(clipped_shapes)} non-overlapping shapes")
        else:
            t0 = time.perf_counter()
            shape_data, scale_factor, bbox = self._parse_svg(svg_path, target_width_mm)
            if not shape_data:
                raise ValueError("No valid filled shapes found in SVG.")
            stage_timings["parse_s"] = time.perf_counter() - t0
            print(f"[VECTOR] Parsed {len(shape_data)} shapes. Scale: {scale_factor:.4f}")

            t0 = time.perf_counter()
            _pre_area = sum(it["poly"].area for it in shape_data if it["poly"] is not None)
            clipped_shapes, silhouette = self._clip_occlusion(shape_data, return_silhouette=True)
            _clip_area = sum(it["geometry"].area for it in clipped_shapes if it["geometry"] is not None)
            print(f"[VECTOR] _clip_occlusion: {len(shape_data)} -> {len(clipped_shapes)} shapes, area {_pre_area:.1f} -> {_clip_area:.1f} ({_clip_area/_pre_area*100:.1f}%)")

            post_clip = []
            for item in clipped_shapes:
                g = item["geometry"]
                g = VectorProcessor._normalize_contours(g)
                if g is not None and not g.is_empty:
                    item["geometry"] = g
                    post_clip.append(item)
            _norm_area = sum(it["geometry"].area for it in post_clip if it["geometry"] is not None)
            print(f"[VECTOR] post-clip normalize: {len(clipped_shapes)} -> {len(post_clip)} shapes, area {_clip_area:.1f} -> {_norm_area:.1f}")
            clipped_shapes = post_clip

            split_input = [{"poly": it["geometry"], "color": it["color"]} for it in clipped_shapes]
            split_output = VectorProcessor._split_disconnected_shapes(split_input)
            clipped_shapes = [
                {"geometry": it["poly"], "color": it["color"], "draw_order": idx}
                for idx, it in enumerate(split_output)
            ]
            _split_area = sum(it["geometry"].area for it in clipped_shapes if it["geometry"] is not None)
            print(f"[VECTOR] split disconnected: {len(post_clip)} -> {len(clipped_shapes)} shapes, area {_norm_area:.1f} -> {_split_area:.1f}")

            clipped_area_by_order = {
                int(item["draw_order"]): _agent_debug_geom_area(item["geometry"])
                for item in post_clip
            }
            occlusion_examples = []
            for draw_order, item in enumerate(shape_data):
                orig_area = _agent_debug_geom_area(item["poly"])
                if orig_area <= 0.0:
                    continue
                kept_area = float(clipped_area_by_order.get(draw_order, 0.0))
                lost_area = max(0.0, orig_area - kept_area)
                if lost_area <= 0.0:
                    continue
                occlusion_examples.append(
                    {
                        "draw_order": int(draw_order),
                        "color": _agent_debug_rgb_to_hex(item.get("color")),
                        "orig_area": round(orig_area, 4),
                        "kept_area": round(kept_area, 4),
                        "lost_area": round(lost_area, 4),
                        "loss_ratio": round(lost_area / orig_area, 4),
                        "fully_occluded": kept_area <= 1e-9,
                    }
                )
            occlusion_examples.sort(key=lambda row: (-row["lost_area"], row["draw_order"]))

            # region agent log
            _agent_debug_write(
                hypothesis_id="G",
                location="core/vector_engine.py:analyze_svg.occlusion_diagnostics",
                message="Occlusion and normalization diagnostics",
                data={
                    "svg_path": os.path.basename(svg_path),
                    "pre_clip_shape_count": len(shape_data),
                    "post_clip_shape_count": len(clipped_shapes),
                    "pre_clip_area": round(float(_pre_area), 4),
                    "post_clip_area": round(float(_clip_area), 4),
                    "post_normalize_area": round(float(_norm_area), 4),
                    "post_split_area": round(float(_split_area), 4),
                    "fully_occluded_count": sum(1 for row in occlusion_examples if row["fully_occluded"]),
                    "partial_loss_count": sum(1 for row in occlusion_examples if not row["fully_occluded"]),
                    "top_area_losses": occlusion_examples[:_AGENT_DEBUG_OCCLUSION_EXAMPLE_LIMIT],
                },
            )
            # endregion

            stage_timings["occlusion_s"] = time.perf_counter() - t0
            print(f"[VECTOR] After occlusion clip: {len(clipped_shapes)} non-overlapping shapes")

            if cache_key is not None:
                _VECTOR_PARSE_CLIP_CACHE[cache_key] = {
                    "shape_data": shape_data,
                    "clipped_shapes": clipped_shapes,
                    "silhouette": silhouette,
                    "scale_factor": scale_factor,
                    "bbox": bbox,
                }
                while len(_VECTOR_PARSE_CLIP_CACHE) > _VECTOR_PARSE_CLIP_CACHE_MAX:
                    _VECTOR_PARSE_CLIP_CACHE.pop(next(iter(_VECTOR_PARSE_CLIP_CACHE)))

        # === Stage 3: Resolve color system config ===
        is_six_color = len(self.img_processor.lut_rgb) == 1296
        if is_six_color:
            print("[VECTOR] Auto-detected 6-Color LUT. Forcing 6-Color mode.")
            color_conf = ColorSystem.SIX_COLOR
            self.color_mode = "6-Color"
        else:
            color_conf = ColorSystem.get(self.color_mode)

        slot_names = color_conf["slots"]
        preview_colors = dict(color_conf["preview"])
        num_channels = len(slot_names)
        num_layers = color_conf.get("layer_count", PrinterConfig.COLOR_LAYERS)

        # === Stage 4: Match fill colors to LUT recipes ===
        replacement_manager = None
        if color_replacements:
            try:
                from core.color_replacement import ColorReplacementManager

                replacement_manager = ColorReplacementManager.from_dict(color_replacements)
            except Exception as e:
                print(f"[VECTOR] Warning: Failed to load color replacements: {e}")

        t0 = time.perf_counter()
        matched_shapes = self._match_colors(clipped_shapes, replacement_manager, num_channels, num_layers=num_layers)
        stage_timings["color_match_s"] = time.perf_counter() - t0
        print(f"[VECTOR] Matched {len(matched_shapes)} shapes to LUT recipes")

        # region agent log
        _agent_debug_write(
            hypothesis_id="C",
            location="core/vector_engine.py:analyze_svg.match_summary",
            message="Matched LUT color and recipe summary",
            data={
                "svg_path": os.path.basename(svg_path),
                "num_channels": int(num_channels),
                "num_layers": int(num_layers),
                "summary": _agent_debug_match_summary(matched_shapes),
            },
        )
        # endregion

        return VectorAnalysis(
            shape_data=shape_data,
            clipped_shapes=clipped_shapes,
            matched_shapes=matched_shapes,
            silhouette=silhouette,
            scale_factor=scale_factor,
            bbox=bbox,
            color_conf=color_conf,
            slot_names=slot_names,
            num_channels=num_channels,
            num_layers=num_layers,
            preview_colors=preview_colors,
            stage_timings=stage_timings,
        )

    def build_mesh(
        self,
        analysis: VectorAnalysis,
        thickness_mm: float,
        structure_mode: str = "Single-sided",
        progress_fn=None,
    ) -> trimesh.Scene:
        """Extrude analyzed vector shapes into a trimesh Scene.
        将分析后的矢量形状挤出为 trimesh Scene。

        Args:
            analysis:       Result from ``analyze_svg``.
            thickness_mm:   Backing (spacer) thickness in mm.
            structure_mode: "Single-sided" or "Double-sided".
            progress_fn:    Optional progress callback.

        Returns:
            A ``trimesh.Scene`` with one geometry per material slot.
        """
        print(f"[VECTOR] Building mesh: structure_mode={structure_mode}")
        stage_timings = dict(analysis.stage_timings)
        t_total_start = time.perf_counter()

        matched_shapes = analysis.matched_shapes
        clipped_shapes = analysis.clipped_shapes
        silhouette = analysis.silhouette
        scale_factor = analysis.scale_factor
        bbox = analysis.bbox
        slot_names = analysis.slot_names
        num_channels = analysis.num_channels
        num_layers = analysis.num_layers
        preview_colors = analysis.preview_colors

        # === Stage 5: Run-length extrude per channel ===
        layer_h = PrinterConfig.LAYER_HEIGHT
        extrude_cache = {}
        is_5color = "5-Color Extended" in self.color_mode
        backing_layer_count = max(1, int(round(thickness_mm / layer_h)))
        backing_height = backing_layer_count * layer_h

        t0 = time.perf_counter()
        if is_5color:
            meshes_by_slot = self._run_length_extrude(
                matched_shapes,
                num_layers,
                layer_h,
                num_channels,
                slot_names,
                scale_factor,
                extrude_cache=extrude_cache,
                face_up=True,
                optical_z_base=backing_height,
            )
            print(f"[VECTOR] 5-Color face-up: {num_layers} optical layers above {backing_height:.2f}mm backing")
        else:
            meshes_by_slot = self._run_length_extrude(
                matched_shapes,
                num_layers,
                layer_h,
                num_channels,
                slot_names,
                scale_factor,
                extrude_cache=extrude_cache,
            )
        stage_timings["extrude_bottom_s"] = time.perf_counter() - t0

        # === Stage 6: Backing layer from silhouette ===
        t0 = time.perf_counter()
        if silhouette is None and clipped_shapes:
            all_geoms = [
                s["geometry"] for s in clipped_shapes if s["geometry"] is not None and not s["geometry"].is_empty
            ]
            silhouette = unary_union(all_geoms) if all_geoms else None

        if is_5color:
            backing_z_start = 0
        else:
            backing_z_start = num_layers * layer_h

        if thickness_mm > 0 and silhouette is not None and not silhouette.is_empty:
            print(f"[VECTOR] Generating backing: {backing_layer_count} layers ({thickness_mm}mm)")
            backing_sil = self._normalize_contours(silhouette, close_delta_mm=0.4)
            if backing_sil is None or backing_sil.is_empty:
                backing_sil = silhouette
            backing_sil = self._filter_backing_holes(backing_sil, min_hole_area_mm2=0.3)
            try:
                backing_sil = backing_sil.buffer(0.15, join_style="mitre", mitre_limit=2.0)
            except Exception:
                pass
            backing_meshes = []
            backing_height = backing_layer_count * layer_h
            gap_offset = BASE_COLOR_GAP_MM if not is_5color else 0.0
            backing_meshes.extend(
                self._extrude_geometry(
                    backing_sil,
                    height=backing_height,
                    z_offset=backing_z_start + gap_offset,
                    scale=scale_factor,
                    extrude_cache=extrude_cache,
                )
            )
            if backing_meshes:
                backing_name = "Board"
                if backing_name not in meshes_by_slot:
                    meshes_by_slot[backing_name] = {"meshes": [], "mat_id": 0}
                meshes_by_slot[backing_name]["meshes"].extend(backing_meshes)
        stage_timings["backing_s"] = time.perf_counter() - t0

        # === Stage 7: Double-sided structure ===
        t0 = time.perf_counter()
        is_double_sided = "双面" in structure_mode or "Double" in structure_mode
        if is_double_sided:
            print("[VECTOR] Adding mirrored color layers (double-sided mode)...")
            top_z_start = backing_z_start + backing_layer_count * layer_h
            self._add_double_sided_layers(
                matched_shapes,
                num_layers,
                layer_h,
                num_channels,
                slot_names,
                scale_factor,
                top_z_start,
                meshes_by_slot,
                extrude_cache=extrude_cache,
            )
        stage_timings["extrude_top_s"] = time.perf_counter() - t0

        # === Stage 8: Assemble scene (sorted by material ID) ===
        t0 = time.perf_counter()
        scene = trimesh.Scene()
        svg_height_mm = bbox[3] * scale_factor

        sorted_items = sorted(meshes_by_slot.items(), key=lambda x: x[1]["mat_id"])

        for name, data in sorted_items:
            mesh_list = data["meshes"]
            mat_id = data["mat_id"]
            if not mesh_list:
                continue

            print(f"[VECTOR] Merging {len(mesh_list)} parts for {name}...")
            combined = trimesh.util.concatenate(mesh_list) if len(mesh_list) > 1 else mesh_list[0]
            self._fix_coordinates(combined, svg_height_mm)

            color_val = preview_colors.get(mat_id, [255, 255, 255, 255])
            combined.visual.face_colors = color_val
            combined.metadata["name"] = name
            scene.add_geometry(combined, geom_name=name)

        stage_timings["assemble_s"] = time.perf_counter() - t0
        stage_timings["total_s"] = time.perf_counter() - t_total_start
        stage_timings["extrude_cache_entries"] = len(extrude_cache)
        self.last_stage_timings = stage_timings

        # region agent log
        _agent_debug_write(
            hypothesis_id="D",
            location="core/vector_engine.py:build_mesh.scene_summary",
            message="Scene summary before 3MF export",
            data={
                "structure_mode": structure_mode,
                "stage_timings": {
                    key: round(float(value), 4)
                    for key, value in stage_timings.items()
                    if isinstance(value, (int, float))
                },
                "scene": _agent_debug_scene_summary(scene),
            },
        )
        # endregion

        print(
            "[VECTOR] Stage timings (s): "
            f"parse={stage_timings.get('parse_s', 0):.3f}, "
            f"clip={stage_timings.get('occlusion_s', 0):.3f}, "
            f"match={stage_timings.get('color_match_s', 0):.3f}, "
            f"extrude_bottom={stage_timings['extrude_bottom_s']:.3f}, "
            f"backing={stage_timings['backing_s']:.3f}, "
            f"extrude_top={stage_timings['extrude_top_s']:.3f}, "
            f"assemble={stage_timings['assemble_s']:.3f}, "
            f"total={stage_timings['total_s']:.3f}"
        )
        print(f"[VECTOR] Extrude cache entries: {stage_timings['extrude_cache_entries']}")
        print(f"[VECTOR] Scene complete: {len(scene.geometry)} objects")
        return scene

    def svg_to_mesh(
        self,
        svg_path: str,
        target_width_mm: float,
        thickness_mm: float,
        structure_mode: str = "Single-sided",
        color_replacements: dict = None,
        progress_fn=None,
    ) -> trimesh.Scene:
        """Convert an SVG file to a trimesh Scene ready for 3MF export.
        将 SVG 文件转换为可用于 3MF 导出的 trimesh Scene。

        Convenience wrapper combining ``analyze_svg`` and ``build_mesh``.

        Args:
            svg_path:         Path to SVG file.
            target_width_mm:  Physical width in mm for the output model.
            thickness_mm:     Backing (spacer) thickness in mm.
            structure_mode:   "Single-sided" or "Double-sided".
            color_replacements: Optional ``{hex: hex}`` replacement map.
            progress_fn:      Optional progress callback.

        Returns:
            A ``trimesh.Scene`` with one geometry per material slot, sorted
            by material ID.  Geometry names match slot names from the active
            ``ColorSystem`` configuration.
        """
        analysis = self.analyze_svg(svg_path, target_width_mm, color_replacements, progress_fn)
        return self.build_mesh(analysis, thickness_mm, structure_mode, progress_fn)

    # ── 2D preview from analyzed geometry ─────────────────────────────────

    @staticmethod
    def render_preview(
        analysis: "VectorAnalysis",
        pixels_per_mm: float = 10.0,
        max_width_px: int = 1600,
    ) -> np.ndarray:
        """Render a 2D RGBA preview from analyzed vector geometry.
        从已分析的矢量几何渲染 2D RGBA 预览，与 3MF 使用同一组几何数据。

        Args:
            analysis:      Result from ``analyze_svg``.
            pixels_per_mm: Rasterization density (pixels per mm).
            max_width_px:  Maximum output width in pixels.

        Returns:
            (H, W, 4) uint8 RGBA numpy array with white background.
        """
        real_w = analysis.bbox[2]
        real_h = analysis.bbox[3]
        sf = analysis.scale_factor

        w_mm = real_w * sf
        h_mm = real_h * sf
        ppm = pixels_per_mm

        w_px = max(1, int(round(w_mm * ppm)))
        h_px = max(1, int(round(h_mm * ppm)))

        if w_px > max_width_px:
            ratio = max_width_px / w_px
            w_px = max_width_px
            h_px = max(1, int(round(h_px * ratio)))
            ppm = w_px / w_mm

        canvas = np.full((h_px, w_px, 4), 255, dtype=np.uint8)

        coord_scale = sf * ppm

        slot_names = analysis.slot_names
        preview_colors = analysis.preview_colors

        for shape in analysis.matched_shapes:
            geom = shape["geometry"]
            recipe = shape["recipe"]
            if geom is None or geom.is_empty:
                continue

            slot_idx = recipe[0] if recipe else 0
            rgba = preview_colors.get(slot_idx, preview_colors.get(slot_names[slot_idx] if slot_idx < len(slot_names) else 0, [128, 128, 128, 255]))
            bgr_color = (int(rgba[2]), int(rgba[1]), int(rgba[0]))

            polys = []
            if geom.geom_type == "Polygon":
                polys = [geom]
            elif geom.geom_type == "MultiPolygon":
                polys = list(geom.geoms)
            else:
                continue

            for poly in polys:
                if poly.is_empty:
                    continue
                ext_coords = np.array(poly.exterior.coords)
                pts = np.column_stack([
                    ext_coords[:, 0] * coord_scale,
                    h_px - ext_coords[:, 1] * coord_scale,
                ]).astype(np.int32)
                cv2.fillPoly(canvas, [pts], (*bgr_color, int(rgba[3])))

                for interior in poly.interiors:
                    hole_coords = np.array(interior.coords)
                    hole_pts = np.column_stack([
                        hole_coords[:, 0] * coord_scale,
                        h_px - hole_coords[:, 1] * coord_scale,
                    ]).astype(np.int32)
                    cv2.fillPoly(canvas, [hole_pts], (255, 255, 255, 255))

        return canvas

    @staticmethod
    def build_preview_cache(
        analysis: "VectorAnalysis",
        pixels_per_mm: float = 10.0,
        max_width_px: int = 1600,
    ) -> dict:
        """Rasterise vector analysis into preview-cache arrays.
        将矢量分析结果光栅化为预览缓存数组，供预览/调色板/GLB 复用。

        Unlike ``render_preview()``, this method preserves separate
        ``matched_rgb`` / ``quantized_image`` / ``mask_solid`` data so the
        frontend preview cache stays aligned with the native vector pipeline.
        """
        real_w = analysis.bbox[2]
        real_h = analysis.bbox[3]
        sf = analysis.scale_factor

        w_mm = real_w * sf
        h_mm = real_h * sf
        ppm = pixels_per_mm

        w_px = max(1, int(round(w_mm * ppm)))
        h_px = max(1, int(round(h_mm * ppm)))

        if w_px > max_width_px:
            ratio = max_width_px / w_px
            w_px = max_width_px
            h_px = max(1, int(round(h_px * ratio)))
            ppm = w_px / w_mm

        coord_scale = sf * ppm
        matched_rgb = np.zeros((h_px, w_px, 3), dtype=np.uint8)
        quantized_image = np.zeros((h_px, w_px, 3), dtype=np.uint8)
        mask_solid = np.zeros((h_px, w_px), dtype=bool)
        material_matrix = np.full((h_px, w_px, analysis.num_layers), -1, dtype=np.int16)

        def _iter_polygons(geom):
            if geom is None or geom.is_empty:
                return []
            if geom.geom_type == "Polygon":
                return [geom]
            if geom.geom_type == "MultiPolygon":
                return list(geom.geoms)
            return []

        def _coords_to_pts(coords):
            pts = np.column_stack([
                coords[:, 0] * coord_scale,
                h_px - coords[:, 1] * coord_scale,
            ]).astype(np.int32)
            if len(pts) < 3:
                return None
            return pts

        def _polygon_mask(poly):
            region = np.zeros((h_px, w_px), dtype=np.uint8)
            ext_coords = np.array(poly.exterior.coords)
            ext_pts = _coords_to_pts(ext_coords)
            if ext_pts is None:
                return None
            cv2.fillPoly(region, [ext_pts], 255)

            for interior in poly.interiors:
                hole_coords = np.array(interior.coords)
                hole_pts = _coords_to_pts(hole_coords)
                if hole_pts is not None:
                    cv2.fillPoly(region, [hole_pts], 0)

            return region.astype(bool)

        for shape in analysis.matched_shapes:
            geom = shape.get("geometry")
            if geom is None or geom.is_empty:
                continue

            matched_color = np.array(
                shape.get("matched_rgb") or shape.get("color") or (0, 0, 0),
                dtype=np.uint8,
            )
            source_color = np.array(
                shape.get("color") or shape.get("matched_rgb") or (0, 0, 0),
                dtype=np.uint8,
            )

            recipe = shape.get("recipe") or []
            recipe_full = np.full((analysis.num_layers,), -1, dtype=np.int16)
            for idx, value in enumerate(recipe[:analysis.num_layers]):
                recipe_full[idx] = int(value)

            for poly in _iter_polygons(geom):
                if poly.is_empty:
                    continue
                region_mask = _polygon_mask(poly)
                if region_mask is None or not np.any(region_mask):
                    continue

                matched_rgb[region_mask] = matched_color
                quantized_image[region_mask] = source_color
                mask_solid[region_mask] = True
                material_matrix[region_mask] = recipe_full

        preview_rgba = np.zeros((h_px, w_px, 4), dtype=np.uint8)
        preview_rgba[mask_solid, :3] = matched_rgb[mask_solid]
        preview_rgba[mask_solid, 3] = 255

        return {
            "target_w": w_px,
            "target_h": h_px,
            "target_width_mm": w_mm,
            "pixel_scale": (w_mm / w_px) if w_px > 0 else 0.0,
            "matched_rgb": matched_rgb,
            "quantized_image": quantized_image,
            "mask_solid": mask_solid,
            "material_matrix": material_matrix,
            "preview_rgba": preview_rgba,
        }

    # ── Stage 2: Occlusion clipping (Chroma-style) ───────────────────────

    @staticmethod
    def _clip_occlusion(shape_data, return_silhouette=False):
        """Clip shapes so no two overlap in XY.

        Iterates in reverse draw order (topmost first).  Each shape is
        subtracted from the accumulated union so that lower shapes only
        retain geometry not already covered by higher shapes.

        This mirrors ``ChromaPrint3D::detail::ClipOcclusion``.
        """
        n = len(shape_data)
        if n == 0:
            return ([], None) if return_silhouette else []

        valid = []
        for i, item in enumerate(shape_data):
            geom = item["poly"]
            if geom is None or geom.is_empty:
                continue
            valid.append((i, geom))

        if not valid:
            return ([], None) if return_silhouette else []

        orders = [v[0] for v in valid]
        geoms = [v[1] for v in valid]
        tree = STRtree(geoms)
        geom_id_to_idx = {id(g): idx for idx, g in enumerate(geoms)}
        result = []

        for i in range(n - 1, -1, -1):
            item = shape_data[i]
            geom = item["poly"]
            if geom is None or geom.is_empty:
                continue

            occluders = []
            try:
                candidate_refs = tree.query(geom)
            except Exception:
                candidate_refs = []

            for ref in candidate_refs:
                if isinstance(ref, (int, np.integer)):
                    idx = int(ref)
                else:
                    idx = geom_id_to_idx.get(id(ref), -1)
                if idx < 0:
                    continue
                if orders[idx] <= i:
                    continue
                cand = geoms[idx]
                try:
                    if cand.intersects(geom):
                        occluders.append(cand)
                except Exception:
                    continue

            if not occluders:
                clipped = geom
            else:
                occ = occluders[0] if len(occluders) == 1 else unary_union(occluders)
                try:
                    clipped = geom.difference(occ)
                except Exception:
                    # First attempt failed — repair both geometries and retry.
                    try:
                        fixed_geom = geom if geom.is_valid else geom.buffer(0)
                        fixed_occ = occ if occ.is_valid else occ.buffer(0)
                        clipped = fixed_geom.difference(fixed_occ)
                    except Exception:
                        # Cannot compute difference — drop shape to avoid
                        # overlapping geometry that breaks the mesh.
                        clipped = None

            if clipped is not None and not clipped.is_empty:
                if not clipped.is_valid:
                    clipped = make_valid(clipped)
                if not clipped.is_empty:
                    result.append(
                        {
                            "geometry": clipped,
                            "color": item["color"],
                            "draw_order": i,
                        }
                    )

        result.reverse()
        if return_silhouette:
            try:
                silhouette = unary_union(geoms)
            except Exception:
                silhouette = None
            return result, silhouette
        return result

    # ── Stage 4: Color matching with per-color cache ─────────────────────

    def _match_colors(self, clipped_shapes, replacement_manager, num_channels, num_layers=None):
        """Match each shape's fill colour to a LUT recipe.

        Identical fill colours share a single KDTree lookup via a cache,
        mirroring ``ChromaPrint3D::VectorRecipeMap::Match`` behaviour.

        Returns a list of dicts: ``{geometry, recipe, color}``.
        """
        if num_layers is None:
            num_layers = PrinterConfig.COLOR_LAYERS
        recipe_log_mode = os.getenv("LUMINA_VECTOR_RECIPE_LOG", "summary").strip().lower()
        color_cache = {}
        matched = []
        sample_logs = []

        for item in clipped_shapes:
            rgb = item["color"]

            if rgb in color_cache:
                cached = color_cache[rgb]
                recipe = cached["recipe"]
                matched_rgb = cached["matched_rgb"]
                lut_idx = cached["lut_idx"]
            else:
                query_lab = self.img_processor._rgb_to_lab(np.array([rgb], dtype=np.uint8))
                _, index = self.img_processor.kdtree.query(query_lab)
                lut_idx = int(index[0])
                matched_rgb = tuple(int(c) for c in self.img_processor.lut_rgb[lut_idx])

                if replacement_manager is not None:
                    replacement = replacement_manager.get_replacement(matched_rgb)
                    if replacement is not None:
                        rep_lab = self.img_processor._rgb_to_lab(np.array([replacement], dtype=np.uint8))
                        _, rep_index = self.img_processor.kdtree.query(rep_lab)
                        lut_idx = int(rep_index[0])
                        matched_rgb = tuple(int(c) for c in self.img_processor.lut_rgb[lut_idx])

                stack = self.img_processor.ref_stacks[lut_idx]
                recipe = [min(int(stack[z]), num_channels - 1) for z in range(min(num_layers, len(stack)))]
                color_cache[rgb] = {
                    "recipe": recipe,
                    "matched_rgb": matched_rgb,
                    "lut_idx": lut_idx,
                }

                hex_c = f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
                matched_hex = f"#{matched_rgb[0]:02x}{matched_rgb[1]:02x}{matched_rgb[2]:02x}"
                if recipe_log_mode == "full":
                    print(f"  {hex_c} -> {matched_hex} -> recipe {recipe}")
                elif recipe_log_mode == "summary" and len(sample_logs) < 8:
                    sample_logs.append(f"{hex_c} -> {matched_hex} -> {recipe}")

            matched.append(
                {
                    "geometry": item["geometry"],
                    "recipe": recipe,
                    "color": rgb,
                    "matched_rgb": matched_rgb,
                    "lut_idx": int(lut_idx),
                }
            )

        if recipe_log_mode == "summary":
            print(f"[VECTOR] Recipe cache summary: unique_colors={len(color_cache)}, shapes={len(clipped_shapes)}")
            if sample_logs:
                print(f"[VECTOR] Recipe samples: {'; '.join(sample_logs)}")

        return matched

    # ── Stage 5: Run-length extrusion ────────────────────────────────────

    @staticmethod
    def _build_channel_runs(recipe, layers_to_use, num_channels):
        """Build contiguous layer runs grouped by channel.

        Returns:
            dict[channel_id] -> list of (start_layer, end_layer)
        """
        runs_by_channel = {}
        if layers_to_use <= 0:
            return runs_by_channel

        run_start = 0
        run_channel = int(recipe[0])
        for z in range(1, layers_to_use + 1):
            current_channel = int(recipe[z]) if z < layers_to_use else None
            if current_channel != run_channel:
                if 0 <= run_channel < num_channels:
                    runs_by_channel.setdefault(run_channel, []).append((run_start, z - 1))
                run_start = z
                run_channel = current_channel

        return runs_by_channel

    @staticmethod
    def _run_length_extrude(
        matched_shapes,
        num_layers,
        layer_h,
        num_channels,
        slot_names,
        scale_factor,
        extrude_cache=None,
        face_up=False,
        optical_z_base=0.0,
    ):
        """Extrude each shape per channel, merging consecutive same-channel
        layers into single volumes (run-length encoding).

        Before extrusion, shapes sharing the same (channel, layer-run) are
        merged via ``unary_union`` + morphological closing to eliminate gaps
        between adjacent same-colour regions (Fix 7).

        When *face_up* is True the layer order is reversed so that
        recipe[N-1] sits at the lowest Z (just above *optical_z_base*)
        and recipe[0] at the highest Z — matching ``_build_voxel_matrix_faceup``
        semantics used by the raster path for 5-Color Extended.
        """
        # --- Fix 7: group shapes by (channel, run) and merge ---
        # Key: (channel_id, run_start, run_end)  Value: list of geometries
        run_groups: dict[tuple, list] = {}
        target_run_groups = {}

        for item in matched_shapes:
            geom = item["geometry"]
            recipe = item["recipe"]
            if geom is None or geom.is_empty:
                continue

            layers_to_use = min(num_layers, len(recipe))
            runs_by_channel = VectorProcessor._build_channel_runs(recipe, layers_to_use, num_channels)
            source_hex = _agent_debug_rgb_to_hex(item.get("matched_rgb"))
            source_area = _agent_debug_geom_area(geom)

            for ch, runs in runs_by_channel.items():
                if ch >= len(slot_names):
                    continue
                for run_start, run_end in runs:
                    key = (ch, run_start, run_end)
                    run_groups.setdefault(key, []).append(geom)
                    if source_hex == _AGENT_DEBUG_TARGET_HEX:
                        debug_key = f"{slot_names[ch]}:{run_start}-{run_end}"
                        info = target_run_groups.setdefault(
                            debug_key,
                            {
                                "slot_name": slot_names[ch],
                                "run_start": int(run_start),
                                "run_end": int(run_end),
                                "source_shape_count": 0,
                                "source_area": 0.0,
                                "group_geom_count": 0,
                                "merged_geom_type": None,
                                "merged_area": 0.0,
                                "meshes_created": 0,
                                "height": 0.0,
                                "z_bot": 0.0,
                            },
                        )
                        info["source_shape_count"] += 1
                        info["source_area"] += source_area

        meshes_by_slot = {}
        for (ch, run_start, run_end), geoms in run_groups.items():
            slot_name = slot_names[ch]
            if slot_name not in meshes_by_slot:
                meshes_by_slot[slot_name] = {"meshes": [], "mat_id": ch}

            if len(geoms) > 1:
                try:
                    merged = unary_union(geoms)
                    merged = VectorProcessor._normalize_contours(merged, close_delta_mm=0.03)
                    if merged is None or merged.is_empty:
                        merged = unary_union(geoms)
                except Exception:
                    merged = unary_union(geoms)
            else:
                merged = geoms[0]

            if face_up:
                inv_start = (num_layers - 1) - run_end
                inv_end = (num_layers - 1) - run_start
                z_bot = optical_z_base + inv_start * layer_h
                height = (inv_end - inv_start + 1) * layer_h
            else:
                z_bot = run_start * layer_h
                height = (run_end - run_start + 1) * layer_h

            new_meshes = VectorProcessor._extrude_geometry(
                merged,
                height=height,
                z_offset=z_bot,
                scale=scale_factor,
                extrude_cache=extrude_cache,
            )
            meshes_by_slot[slot_name]["meshes"].extend(new_meshes)
            debug_key = f"{slot_name}:{run_start}-{run_end}"
            if debug_key in target_run_groups:
                target_run_groups[debug_key]["group_geom_count"] = len(geoms)
                target_run_groups[debug_key]["merged_geom_type"] = getattr(merged, "geom_type", type(merged).__name__)
                target_run_groups[debug_key]["merged_area"] = round(_agent_debug_geom_area(merged), 4)
                target_run_groups[debug_key]["meshes_created"] = len(new_meshes)
                target_run_groups[debug_key]["height"] = round(float(height), 4)
                target_run_groups[debug_key]["z_bot"] = round(float(z_bot), 4)

        # region agent log
        _agent_debug_write(
            hypothesis_id="C",
            location="core/vector_engine.py:_run_length_extrude",
            message="Run-length extrusion summary for target matched LUT color",
            data={
                "face_up": bool(face_up),
                "optical_z_base": round(float(optical_z_base), 4),
                "slot_mesh_counts": {
                    name: len(data["meshes"]) for name, data in sorted(meshes_by_slot.items())
                },
                "target_color": _AGENT_DEBUG_TARGET_HEX,
                "target_run_groups": [
                    {
                        **info,
                        "source_area": round(float(info["source_area"]), 4),
                    }
                    for _, info in sorted(target_run_groups.items())
                ],
            },
        )
        # endregion

        return meshes_by_slot

    # ── Stage 7: Double-sided helper ─────────────────────────────────────

    @staticmethod
    def _add_double_sided_layers(
        matched_shapes,
        num_layers,
        layer_h,
        num_channels,
        slot_names,
        scale_factor,
        top_z_start,
        meshes_by_slot,
        extrude_cache=None,
    ):
        """Mirror colour layers above the backing for double-sided mode.

        Layer Z order is inverted so the viewing surface faces upward on
        the top side.
        """
        for item in matched_shapes:
            geom = item["geometry"]
            recipe = item["recipe"]
            if geom is None or geom.is_empty:
                continue

            layers_to_use = min(num_layers, len(recipe))

            runs_by_channel = VectorProcessor._build_channel_runs(recipe, layers_to_use, num_channels)
            for ch, runs in runs_by_channel.items():
                if ch >= len(slot_names):
                    continue

                slot_name = slot_names[ch]
                if slot_name not in meshes_by_slot:
                    meshes_by_slot[slot_name] = {"meshes": [], "mat_id": ch}

                for run_start, run_end in runs:
                    inv_start = (num_layers - 1) - run_end
                    inv_end = (num_layers - 1) - run_start

                    z_bot = top_z_start + inv_start * layer_h
                    height = (inv_end - inv_start + 1) * layer_h
                    new_meshes = VectorProcessor._extrude_geometry(
                        geom,
                        height=height,
                        z_offset=z_bot,
                        scale=scale_factor,
                        extrude_cache=extrude_cache,
                    )
                    meshes_by_slot[slot_name]["meshes"].extend(new_meshes)

    # ── SVG parsing ──────────────────────────────────────────────────────

    def _parse_svg(self, svg_path: str, target_width_mm: float):
        """Parse SVG and return shapes in draw order with normalised coords.

        Returns:
            ``(shape_list, scale_factor, bbox_tuple)``
            where each shape item is ``{'poly': Polygon, 'color': (r,g,b)}``.
        """
        try:
            svg = SVG.parse(svg_path)
        except Exception as e:
            raise ValueError(f"Failed to parse SVG: {e}")

        gradient_defs = VectorProcessor._parse_gradient_defs(svg_path)
        _url_re = re.compile(r"url\(#([^)]+)\)")

        tol_svg = self.sampling_precision / max(target_width_mm / 100.0, 0.01)

        def _sample_path_to_polygon(path_obj):
            try:
                segments = list(path_obj.segments())
            except Exception:
                segments = None

            if segments and len(segments) > 1:
                coords = _flatten_segments(segments, tol_svg)
            else:
                coords = _flatten_segments_fallback(path_obj, tol_svg)

            if len(coords) < 3:
                return None

            poly = Polygon(coords)
            if not poly.is_valid:
                poly = make_valid(poly)
            poly = VectorProcessor._extract_polygonal_geometry(poly)

            if poly is not None and not poly.is_empty:
                return poly
            return None

        def _flatten_segments(segments, tolerance):
            """Adaptive de Casteljau flattening for each segment."""
            coords = []
            for seg in segments:
                if isinstance(seg, Move):
                    continue
                if isinstance(seg, (Line, Close)):
                    coords.append((seg.start.x, seg.start.y))
                elif isinstance(seg, CubicBezier):
                    if not coords:
                        coords.append((seg.start.x, seg.start.y))
                    _flatten_cubic(
                        seg.start.x, seg.start.y,
                        seg.control1.x, seg.control1.y,
                        seg.control2.x, seg.control2.y,
                        seg.end.x, seg.end.y,
                        tolerance, coords, 0,
                    )
                elif isinstance(seg, QuadraticBezier):
                    if not coords:
                        coords.append((seg.start.x, seg.start.y))
                    _flatten_quadratic(
                        seg.start.x, seg.start.y,
                        seg.control.x, seg.control.y,
                        seg.end.x, seg.end.y,
                        tolerance, coords, 0,
                    )
                else:
                    coords.append((seg.start.x, seg.start.y))
                    try:
                        for tv in np.linspace(0.1, 1.0, 10):
                            pt = seg.point(tv)
                            coords.append((pt.x, pt.y))
                    except Exception:
                        coords.append((seg.end.x, seg.end.y))
            return coords

        def _flatten_segments_fallback(path_obj, tolerance):
            """Fallback for paths that can't be decomposed into segments."""
            try:
                path_len = path_obj.length()
            except Exception:
                return []
            if path_len == 0:
                return []
            n = max(10, min(int(path_len / max(tolerance, 0.01)), 8000))
            t_vals = np.linspace(0, 1, n)
            pts = [path_obj.point(t) for t in t_vals]
            return [(p.x, p.y) for p in pts]

        raw_shapes = []
        skipped_types = {}
        skipped_gradient_count = 0
        skipped_polygon_count = 0
        path_like_count = 0
        fill_shape_count = 0
        stroke_only_count = 0
        filled_with_stroke_count = 0
        parse_skip_examples = []
        print("[VECTOR] Parsing SVG geometry...")

        def _record_parse_skip(reason, element_obj, **extra):
            if len(parse_skip_examples) >= _AGENT_DEBUG_PARSE_EXAMPLE_LIMIT:
                return
            fill_val = getattr(getattr(element_obj, "fill", None), "value", None)
            stroke_val = getattr(getattr(element_obj, "stroke", None), "value", None)
            parse_skip_examples.append(
                {
                    "reason": reason,
                    "element_type": type(element_obj).__name__,
                    "fill": None if fill_val is None else str(fill_val),
                    "stroke": None if stroke_val is None else str(stroke_val),
                    **extra,
                }
            )

        for element in svg.elements():
            if not isinstance(element, (Path, Shape)):
                type_name = type(element).__name__
                skipped_types[type_name] = skipped_types.get(type_name, 0) + 1
                continue

            path_like_count += 1

            has_fill = (
                element.fill is not None
                and element.fill.value is not None
                and str(element.fill.value).lower() != "none"
            )
            has_stroke = (
                getattr(element, "stroke", None) is not None
                and getattr(element.stroke, "value", None) is not None
                and str(element.stroke.value).lower() != "none"
            )
            if not has_fill:
                if has_stroke:
                    stroke_only_count += 1
                    _record_parse_skip("stroke_only_ignored", element)
                continue

            fill_shape_count += 1
            if has_stroke:
                filled_with_stroke_count += 1

            if isinstance(element, Shape) and not isinstance(element, Path):
                try:
                    element = Path(element)
                except Exception:
                    _record_parse_skip("shape_to_path_failed", element)
                    continue

            grad_info = None
            raw_fill = None
            vals = getattr(element, "values", None)
            if isinstance(vals, dict):
                raw_fill = vals.get("fill", "")
            if raw_fill and gradient_defs:
                m = _url_re.match(str(raw_fill))
                if m:
                    grad_info = gradient_defs.get(m.group(1))
            is_gradient = grad_info is not None

            rgb = None
            if has_fill and not is_gradient:
                try:
                    rgb = (element.fill.red, element.fill.green, element.fill.blue)
                except (AttributeError, TypeError, ValueError):
                    rgb = None
            if rgb is None and not is_gradient:
                fill_val = getattr(element.fill, 'value', None) if element.fill else None
                eid = getattr(element, 'id', None) or f"element#{skipped_gradient_count}"
                _log.debug(f"Skipping '{eid}' — unresolvable fill: {fill_val}")
                skipped_gradient_count += 1
                _record_parse_skip("unresolvable_fill", element)
                continue

            try:
                subpaths = list(element.as_subpaths())
            except Exception:
                subpaths = []

            subpath_polys = []
            for subpath in subpaths:
                try:
                    sub_path = subpath if isinstance(subpath, Path) else Path(subpath)
                    poly = _sample_path_to_polygon(sub_path)
                except Exception:
                    continue
                if poly is None:
                    continue
                subpath_polys.append(poly)

            # --- Fix 4: gradient flattening ---
            if is_gradient:
                grad_shapes = VectorProcessor._flatten_gradient_shape(grad_info, subpath_polys)
                for gs in grad_shapes:
                    p = gs["poly"]
                    if p is not None and not p.is_empty:
                        p = VectorProcessor._normalize_contours(p)
                        if p is not None and not p.is_empty:
                            raw_shapes.append({"poly": p, "color": gs["color"]})
                if not grad_shapes:
                    skipped_gradient_count += 1
                    _record_parse_skip("gradient_flatten_empty", element, subpath_count=len(subpath_polys))
                continue

            # --- Fix 2: fill-rule aware subpath merging ---
            fill_rule = "nonzero"
            try:
                fr = getattr(element, "fill_rule", None)
                if fr is not None:
                    fill_rule = str(fr).strip().lower()
                if fill_rule not in ("nonzero", "evenodd") or fr is None:
                    vals = getattr(element, "values", None)
                    if isinstance(vals, dict):
                        vfr = vals.get("fill-rule", "").strip().lower()
                        if vfr in ("nonzero", "evenodd"):
                            fill_rule = vfr
                    elif hasattr(vals, '__getitem__'):
                        try:
                            vfr = str(vals["fill-rule"]).strip().lower()
                            if vfr in ("nonzero", "evenodd"):
                                fill_rule = vfr
                        except (KeyError, TypeError):
                            pass
            except Exception:
                fill_rule = "nonzero"
            if fill_rule not in ("nonzero", "evenodd"):
                fill_rule = "nonzero"

            if len(subpath_polys) == 1:
                result_poly = subpath_polys[0]
            elif len(subpath_polys) > 1:
                if fill_rule == "evenodd":
                    combined = subpath_polys[0]
                    for sp in subpath_polys[1:]:
                        try:
                            combined = combined.symmetric_difference(sp)
                        except Exception:
                            pass
                else:
                    try:
                        combined = unary_union(subpath_polys)
                    except Exception:
                        combined = subpath_polys[0]

                if combined is not None and not combined.is_empty:
                    if not combined.is_valid:
                        combined = make_valid(combined)
                    result_poly = combined if not combined.is_empty else None
                else:
                    result_poly = None
            else:
                result_poly = None

            if result_poly is None:
                try:
                    result_poly = _sample_path_to_polygon(element)
                except Exception:
                    pass

            if result_poly is None:
                skipped_polygon_count += 1
                _record_parse_skip("polygon_sampling_failed", element, subpath_count=len(subpath_polys))
                continue

            # --- Fix 3: morphological closing ---
            result_poly = VectorProcessor._normalize_contours(result_poly)
            if result_poly is None or result_poly.is_empty:
                skipped_polygon_count += 1
                _record_parse_skip("normalize_empty", element, subpath_count=len(subpath_polys))
                continue

            raw_shapes.append({"poly": result_poly, "color": rgb})

        if skipped_types:
            _log.info(f"[VECTOR] Skipped non-path elements: {skipped_types}")
        if skipped_gradient_count > 0:
            _log.info(f"[VECTOR] {skipped_gradient_count} gradient fills could not be fully resolved")
        if skipped_polygon_count > 0:
            _log.info(f"[VECTOR] Skipped {skipped_polygon_count} elements (invalid polygon after sampling)")
        _log.info(f"[VECTOR] Successfully parsed {len(raw_shapes)} shapes from SVG")

        parse_warnings = []
        if skipped_gradient_count > 0:
            parse_warnings.append(
                f"{skipped_gradient_count} gradient/pattern fills could not be fully resolved"
            )
        if skipped_polygon_count > 0:
            parse_warnings.append(
                f"{skipped_polygon_count} elements produced invalid geometry and were skipped"
            )
        self.parse_warnings = parse_warnings

        # region agent log
        _agent_debug_write(
            hypothesis_id="F",
            location="core/vector_engine.py:_parse_svg",
            message="SVG parse diagnostics",
            data={
                "svg_path": os.path.basename(svg_path),
                "path_like_count": int(path_like_count),
                "fill_shape_count": int(fill_shape_count),
                "stroke_only_count": int(stroke_only_count),
                "filled_with_stroke_count": int(filled_with_stroke_count),
                "parsed_shape_count": int(len(raw_shapes)),
                "skipped_gradient_count": int(skipped_gradient_count),
                "skipped_polygon_count": int(skipped_polygon_count),
                "skipped_non_path_types": skipped_types,
                "parse_skip_examples": parse_skip_examples,
            },
        )
        # endregion

        if not raw_shapes:
            raise ValueError("No valid shapes found in SVG")

        # Global bounding box — union of parsed shapes and SVG viewport
        min_xs, min_ys, max_xs, max_ys = [], [], [], []
        for item in raw_shapes:
            bx0, by0, bx1, by1 = item["poly"].bounds
            min_xs.append(bx0)
            min_ys.append(by0)
            max_xs.append(bx1)
            max_ys.append(by1)

        gx0, gy0 = min(min_xs), min(min_ys)
        gx1, gy1 = max(max_xs), max(max_ys)

        try:
            vb = getattr(svg, "viewbox", None)
            if vb is not None:
                vb_x = float(getattr(vb, "x", 0) or 0)
                vb_y = float(getattr(vb, "y", 0) or 0)
                vb_w = float(getattr(vb, "width", 0) or 0)
                vb_h = float(getattr(vb, "height", 0) or 0)
                if vb_w > 0 and vb_h > 0:
                    gx0 = min(gx0, vb_x)
                    gy0 = min(gy0, vb_y)
                    gx1 = max(gx1, vb_x + vb_w)
                    gy1 = max(gy1, vb_y + vb_h)
                    print(f"[VECTOR] SVG viewBox: ({vb_x}, {vb_y}, {vb_w}, {vb_h})")
        except Exception:
            pass

        real_w = gx1 - gx0
        real_h = gy1 - gy0

        print(f"[VECTOR] Global bounds: x={gx0:.1f}, y={gy0:.1f}, w={real_w:.1f}, h={real_h:.1f}")
        if real_w == 0:
            raise ValueError("Invalid geometry width (0)")

        scale_factor = target_width_mm / real_w
        min_area_svg = max(0.0, (self.sampling_precision**2) / max(scale_factor**2, 1e-12) * 0.25)

        final_shapes = []
        for item in raw_shapes:
            shifted = affinity.translate(item["poly"], xoff=-gx0, yoff=-gy0)

            if not shifted.is_valid:
                shifted = make_valid(shifted)

            if shifted.is_empty or shifted.area <= min_area_svg:
                continue
            final_shapes.append({"poly": shifted, "color": item["color"]})

        return final_shapes, scale_factor, (gx0, gy0, real_w, real_h)

    # ── Geometry helpers ─────────────────────────────────────────────────

    @staticmethod
    def _extrude_geometry(geometry, height, z_offset, scale, extrude_cache=None):
        """Extrude 2D Shapely geometry to 3D trimesh objects."""
        meshes = []
        if geometry is None or geometry.is_empty:
            return meshes

        polys = geometry.geoms if hasattr(geometry, "geoms") else [geometry]

        for poly in polys:
            if poly.is_empty:
                continue
            if not hasattr(poly, "exterior"):
                continue
            try:
                cache_key = None
                cached_base = None
                if extrude_cache is not None:
                    # Key excludes height: cache unit-height (h=1) base mesh,
                    # then scale Z per call. Avoids re-triangulating the same
                    # polygon when it appears in multiple layers at different heights.
                    cache_key = (poly.wkb, round(float(scale), 8))
                    cached_base = extrude_cache.get(cache_key)

                if cached_base is None:
                    m_base = trimesh.creation.extrude_polygon(poly, height=1.0)
                    m_base.apply_scale([scale, scale, 1.0])
                    if extrude_cache is not None and cache_key is not None:
                        extrude_cache[cache_key] = m_base.copy()
                else:
                    m_base = cached_base

                m = m_base.copy()
                m.apply_scale([1.0, 1.0, float(height)])
                m.apply_translation([0, 0, z_offset])
                meshes.append(m)
            except Exception as e:
                global _AGENT_DEBUG_EXTRUDE_FAILURES
                if _AGENT_DEBUG_EXTRUDE_FAILURES < _AGENT_DEBUG_EXTRUDE_FAILURE_LIMIT:
                    _AGENT_DEBUG_EXTRUDE_FAILURES += 1
                    # region agent log
                    _agent_debug_write(
                        hypothesis_id="C",
                        location="core/vector_engine.py:_extrude_geometry",
                        message="Polygon extrusion failed",
                        data={
                            "geom_type": getattr(poly, "geom_type", type(poly).__name__),
                            "area": round(_agent_debug_geom_area(poly), 4),
                            "height": round(float(height), 4),
                            "z_offset": round(float(z_offset), 4),
                            "scale": round(float(scale), 6),
                            "error": str(e),
                        },
                    )
                    # endregion
                print(f"[VECTOR] Warning: Failed to extrude polygon: {e}")
                continue

        return meshes

    @staticmethod
    def _fix_coordinates(mesh, svg_height_mm):
        """Flip Y-axis from SVG (Y-down) to printer (Y-up) coordinate system."""
        transform = np.eye(4)
        transform[1, 1] = -1
        mesh.apply_transform(transform)
        mesh.apply_translation([0, svg_height_mm, 0])
