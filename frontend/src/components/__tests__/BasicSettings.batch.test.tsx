import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { useConverterStore } from "../../stores/converter";
import BasicSettings from "../sections/BasicSettings";

// Mock heavy child components to isolate conditional rendering logic
vi.mock("../ui/CropModal", () => ({
  CropModal: () => null,
}));

vi.mock("../ui/Dropdown", () => ({
  default: ({ label }: { label: string }) => (
    <div data-testid={`dropdown-${label}`}>{label}</div>
  ),
}));

vi.mock("../ui/Slider", () => ({
  default: ({ label }: { label: string }) => (
    <div data-testid={`slider-${label}`}>{label}</div>
  ),
}));

vi.mock("../ui/RadioGroup", () => ({
  default: ({ label }: { label: string }) => (
    <div data-testid={`radio-${label}`}>{label}</div>
  ),
}));

function makeFile(name: string, type = "image/png"): File {
  return new File(["dummy"], name, { type });
}

describe("BasicSettings — auto batch mode (unified uploader)", () => {
  beforeEach(() => {
    useConverterStore.setState({
      batchMode: false,
      batchFiles: [],
      imageFile: null,
      imagePreviewUrl: null,
      lut_name: "",
      lutList: [],
      target_width_mm: 60,
      target_height_mm: 60,
      spacer_thick: 1.2,
      enableCrop: false,
      cropModalOpen: false,
      isCropping: false,
    });
  });

  it("does NOT render a batch mode checkbox (removed)", () => {
    render(<BasicSettings />);
    expect(
      screen.queryByRole("checkbox", { name: "批量模式" }),
    ).not.toBeInTheDocument();
  });

  it("shows UnifiedUploader upload hint when no image is selected", () => {
    render(<BasicSettings />);
    expect(
      screen.getByText("拖拽图片或点击上传（支持多选）"),
    ).toBeInTheDocument();
  });

  it("shows crop checkbox in SingleMode (imageFile set, no batchFiles)", () => {
    useConverterStore.setState({
      batchMode: false,
      batchFiles: [],
      imageFile: makeFile("photo.png"),
    });
    render(<BasicSettings />);
    expect(
      screen.getByRole("checkbox", { name: "上传后裁剪" }),
    ).toBeInTheDocument();
  });

  it("hides crop checkbox in BatchMode", () => {
    useConverterStore.setState({
      batchMode: true,
      batchFiles: [makeFile("a.png"), makeFile("b.png")],
    });
    render(<BasicSettings />);
    expect(
      screen.queryByRole("checkbox", { name: "上传后裁剪" }),
    ).not.toBeInTheDocument();
  });

  it("shows batch file list when batchFiles exist", () => {
    useConverterStore.setState({
      batchMode: true,
      batchFiles: [makeFile("a.png"), makeFile("b.jpg")],
    });
    render(<BasicSettings />);
    expect(screen.getByText("a.png")).toBeInTheDocument();
    expect(screen.getByText("b.jpg")).toBeInTheDocument();
    expect(screen.getByText("已选 2 个文件")).toBeInTheDocument();
  });
});
