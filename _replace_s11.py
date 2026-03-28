with open('core/pipeline/s11_glb_preview.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace the numpy voxel section with the old findContours + Shapely approach
# but with corrected lateral face winding order (LEFT/RIGHT/FRONT reversed)
start_marker = '        # 4. Build per-color meshes: pure numpy voxel approach'
end_marker = '        _t_mesh_loop = time.perf_counter() - _t\n'

si = content.find(start_marker)
ei = content.find(end_marker, si)
if si == -1 or ei == -1:
    print(f"ERROR: start={si}, end={ei}")
    import sys; sys.exit(1)

old_block = content[si:ei + len('        _t_mesh_loop = time.perf_counter() - _t\n')]

new_block = '''        # 4. Build per-color meshes: findContours + Shapely polygon extrusion
        _t = time.perf_counter()
        total_layers = 25
        scene = _get_trimesh().Scene()
        contours_data: dict[str, list[list[list[float]]]] = {}

        pixel_scale = target_width_mm / width if width > 0 else 0.42
        scale_transform = np.eye(4)
        scale_transform[0, 0] = pixel_scale
        scale_transform[1, 1] = pixel_scale
        scale_transform[2, 2] = PrinterConfig.LAYER_HEIGHT

        from shapely.geometry import Polygon, MultiPolygon
        # 不用 dilate，直接用 findContours（无间隙有1px间隙，视觉可接受）
        for idx, color_rgb in enumerate(unique_colors):
            r, g, b = int(color_rgb[0]), int(color_rgb[1]), int(color_rgb[2])
            hex_name = f"{r:02x}{g:02x}{b:02x}"
            rgba = np.array([r, g, b, 255], dtype=np.uint8)

            color_mask = np.all(matched_rgb == color_rgb, axis=2) & mask_solid
            mask_u8 = color_mask.astype(np.uint8) * 255

            contours, hierarchy = cv2.findContours(
                mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            if not contours:
                continue

            meshes = []
            color_contour_list: list[list[list[float]]] = []

            for cnt in contours:
                if len(cnt) < 3:
                    continue

                pts = cnt.squeeze(1).astype(np.float64)

                # Convert to world coords (flip Y)
                world_pts = np.column_stack([pts[:, 0], height - pts[:, 1]])

                try:
                    poly = Polygon(world_pts)
                    if not poly.is_valid:
                        poly = poly.buffer(0)
                    if poly.is_empty or poly.area < 1e-4:
                        continue

                    polys_list = list(poly.geoms) if isinstance(poly, MultiPolygon) else [poly]
                    for p in polys_list:
                        if p.is_empty or p.area < 1e-4:
                            continue
                        m = _get_trimesh().creation.extrude_polygon(p, height=float(total_layers))
                        meshes.append(m)
                except Exception:
                    continue

                # Store contour data for cache
                cache_pts = [
                    [float(px * pixel_scale), float((height - py) * pixel_scale)]
                    for px, py in pts
                ]
                color_contour_list.append(cache_pts)

            if meshes:
                result = _get_trimesh().util.concatenate(meshes) if len(meshes) > 1 else meshes[0]
                result.visual.face_colors = np.tile(rgba, (len(result.faces), 1))
                result.apply_transform(scale_transform)
                scene.add_geometry(result, node_name=f"color_{hex_name}")

            if color_contour_list:
                contours_data[hex_name] = color_contour_list

        _t_mesh_loop = time.perf_counter() - _t
'''

new_content = content[:si] + new_block + content[ei + len('        _t_mesh_loop = time.perf_counter() - _t\n'):]
new_content = new_content.replace(
    'mesh_loop(numpy_voxel)=',
    'mesh_loop(contour_extrude)='
)

with open('core/pipeline/s11_glb_preview.py', 'w', encoding='utf-8') as f:
    f.write(new_content)
print("Done")
