"""Unit tests for slicer-specific 3MF metadata generation."""

import json
import zipfile
import xml.etree.ElementTree as ET
from types import SimpleNamespace

import trimesh

from utils import bambu_3mf_writer as writer_module
from utils.bambu_3mf_writer import BambuStudio3MFWriter, load_printer_template


class _FakeCustomPart:
    def __init__(self, path: str, content_type: str, data: bytes):
        self.path = path
        self.content_type = content_type
        self.data = data


class _FakeContentType:
    def __init__(self, extension: str, content_type: str):
        self.extension = extension
        self.content_type = content_type


class _FakeBuilder:
    def __init__(self) -> None:
        self.parts: list[_FakeCustomPart] = []
        self.content_types: list[_FakeContentType] = []

    def add_custom_part(self, part: _FakeCustomPart) -> None:
        self.parts.append(part)

    def add_custom_content_type(self, content_type: _FakeContentType) -> None:
        self.content_types.append(content_type)


def _metadata_values(parent: ET.Element) -> dict[str, str]:
    return {child.attrib["key"]: child.attrib["value"] for child in parent.findall("metadata")}


def _make_anycubic_writer(tmp_path) -> BambuStudio3MFWriter:
    writer = BambuStudio3MFWriter(
        str(tmp_path / "anycubic-test.3mf"),
        settings={},
        color_mode="4-Color",
        printer_id="anycubic-kobra-s1",
        slicer="AnycubicSlicerNext",
    )

    white = trimesh.creation.box(extents=[2, 4, 6])
    white.apply_translation([1, 2, 3])
    writer.add_mesh(white, "White", (255, 0, 0))

    green = trimesh.creation.box(extents=[1, 1, 1])
    green.apply_translation([2, 2, 0.5])
    writer.add_mesh(green, "Green", (0, 255, 0))
    return writer


class TestAnycubicWriterMetadata:
    def test_anycubic_model_settings_match_sample_shape(self, tmp_path) -> None:
        writer = _make_anycubic_writer(tmp_path)

        root = ET.fromstring(writer._build_model_settings_bytes([1, 2], 3))
        first_part = root.find("./object/part")
        assert first_part is not None

        part_meta = _metadata_values(first_part)
        assert part_meta["source_file"] == "anycubic-test.3mf"
        assert part_meta["source_object_id"] == "0"
        assert part_meta["source_volume_id"] == "0"
        assert part_meta["source_offset_x"] == "1"
        assert part_meta["source_offset_y"] == "2"
        assert part_meta["source_offset_z"] == "3"
        assert part_meta["extruder"] == "1"
        assert part_meta["matrix"] == "1 0 0 2 0 1 0 4 0 0 1 6 0 0 0 1"

        plate = root.find("./plate")
        assert plate is not None
        plate_meta = _metadata_values(plate)
        assert "filament_map_mode" not in plate_meta
        assert plate_meta["thumbnail_file"] == "Metadata/plate_1.png"
        assert plate_meta["thumbnail_no_light_file"] == "Metadata/plate_no_light_1.png"
        assert plate_meta["top_file"] == "Metadata/top_1.png"
        assert plate_meta["pick_file"] == "Metadata/pick_1.png"

        model_instance = plate.find("./model_instance")
        assert model_instance is not None
        instance_meta = _metadata_values(model_instance)
        assert instance_meta["identify_id"] == "160"

    def test_anycubic_project_settings_preserve_template_filament_metadata(self, tmp_path) -> None:
        writer = _make_anycubic_writer(tmp_path)
        settings = json.loads(writer._build_project_settings_bytes().decode("utf-8"))
        template = load_printer_template("anycubic-kobra-s1", slicer="AnycubicSlicerNext")

        expected_vendor = template["filament_vendor"][0]
        expected_filament_id = template["filament_ids"][0]
        expected_settings_id = template["filament_settings_id"][0]

        assert settings["filament_vendor"] == [expected_vendor, expected_vendor]
        assert settings["filament_ids"] == [expected_filament_id, expected_filament_id]
        assert settings["filament_settings_id"] == [expected_settings_id, expected_settings_id]
        assert settings["filament_colour"] == ["#FF0000", "#00FF00"]
        assert all(value != "Bambu Lab" for value in settings["filament_vendor"])
        assert all(value != "GFA00" for value in settings["filament_ids"])

    def test_anycubic_slice_info_and_custom_parts_use_acnext_layout(
        self,
        tmp_path,
        monkeypatch,
    ) -> None:
        writer = _make_anycubic_writer(tmp_path)
        slice_info = ET.fromstring(writer._build_slice_info_bytes())
        header = slice_info.find("./header")
        assert header is not None
        header_items = {item.attrib["key"]: item.attrib["value"] for item in header.findall("header_item")}

        assert header_items == {
            "X-ACNext-Client-Type": "slicer",
            "X-ACNext-Client-Version": "1.3.9.4 20260319225535",
        }

        fake_n3mf = SimpleNamespace(
            CustomPart=_FakeCustomPart,
            CustomContentType=_FakeContentType,
        )
        monkeypatch.setattr(writer_module, "_n3mf", fake_n3mf)

        builder = _FakeBuilder()
        writer._inject_metadata_parts(builder, [1, 2], 3)

        part_paths = [part.path for part in builder.parts]
        assert "Metadata/custom_gcode_per_layer.xml" in part_paths
        assert "Metadata/filament_sequence.json" not in part_paths
        assert "Metadata/cut_information.xml" not in part_paths

        custom_part = next(part for part in builder.parts if part.path == "Metadata/custom_gcode_per_layer.xml")
        custom_xml = ET.fromstring(custom_part.data)
        plate = custom_xml.find("./plate")
        assert plate is not None
        plate_info = plate.find("./plate_info")
        mode = plate.find("./mode")
        assert plate_info is not None and plate_info.attrib["id"] == "1"
        assert mode is not None and mode.attrib["value"] == "MultiExtruder"

    def test_anycubic_export_package_contains_expected_files(self, tmp_path) -> None:
        writer = _make_anycubic_writer(tmp_path)
        out_path = writer.export()

        with zipfile.ZipFile(out_path) as package:
            names = set(package.namelist())
            assert "Metadata/custom_gcode_per_layer.xml" in names
            assert "Metadata/filament_sequence.json" not in names
            assert "Metadata/cut_information.xml" not in names

            model_root = ET.fromstring(package.read("3D/3dmodel.model"))
            core_ns = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
            model_metadata = {
                node.attrib["name"]: (node.text or "") for node in model_root.findall("m:metadata", core_ns)
            }
            assert model_metadata["Application"] == "BambuStudio-1.3.9.4"
            assert model_metadata["BambuStudio:3mfVersion"] == "1"

            slice_root = ET.fromstring(package.read("Metadata/slice_info.config"))
            header = slice_root.find("./header")
            assert header is not None
            header_items = {item.attrib["key"]: item.attrib["value"] for item in header.findall("header_item")}
            assert header_items["X-ACNext-Client-Type"] == "slicer"
            assert header_items["X-ACNext-Client-Version"] == "1.3.9.4 20260319225535"
