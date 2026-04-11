import { describe, it, expect } from "vitest";
import {
  extractHexFromMeshName,
  isClickWithoutDrag,
  toggleColorSelection,
} from "../components/InteractiveModelViewer";

describe("extractHexFromMeshName", () => {
  it('extracts hex from "color_ff0000"', () => {
    expect(extractHexFromMeshName("color_ff0000")).toBe("ff0000");
  });

  it('extracts hex from "color_00ff00"', () => {
    expect(extractHexFromMeshName("color_00ff00")).toBe("00ff00");
  });

  it('extracts hex from "color_AABBCC" preserving case', () => {
    expect(extractHexFromMeshName("color_AABBCC")).toBe("AABBCC");
  });

  it("extracts hex from color_ prefix with 6 chars", () => {
    expect(extractHexFromMeshName("color_000000")).toBe("000000");
    expect(extractHexFromMeshName("color_ffffff")).toBe("ffffff");
  });
});

describe("toggleColorSelection", () => {
  it("returns null when clicking the already selected color (deselect)", () => {
    expect(toggleColorSelection("ff0000", "ff0000")).toBeNull();
  });

  it("returns the clicked hex when no color is selected", () => {
    expect(toggleColorSelection(null, "00ff00")).toBe("00ff00");
  });

  it("returns the clicked hex when a different color is selected", () => {
    expect(toggleColorSelection("ff0000", "00ff00")).toBe("00ff00");
  });

  it("returns null for same color regardless of case match", () => {
    // Both are the same string
    expect(toggleColorSelection("aabbcc", "aabbcc")).toBeNull();
  });

  it("returns clicked hex when selected is different", () => {
    expect(toggleColorSelection("111111", "222222")).toBe("222222");
  });
});

describe("isClickWithoutDrag", () => {
  it("returns true when pointer movement stays within the threshold", () => {
    expect(isClickWithoutDrag(10, 10, 12, 13, 4)).toBe(true);
  });

  it("returns true when pointer movement is exactly on the threshold", () => {
    expect(isClickWithoutDrag(0, 0, 3, 4, 5)).toBe(true);
  });

  it("returns false when pointer movement exceeds the threshold", () => {
    expect(isClickWithoutDrag(0, 0, 4, 4, 5)).toBe(false);
  });
});
