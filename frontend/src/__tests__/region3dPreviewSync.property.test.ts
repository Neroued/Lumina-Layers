import { describe, it, expect, vi, beforeEach } from "vitest";
import * as fc from "fast-check";

vi.mock("../api/converter", () => ({
  fetchLutList: vi.fn(),
  convertPreview: vi.fn(),
  convertGenerate: vi.fn(),
  fetchBedSizes: vi.fn(),
  uploadHeightmap: vi.fn(),
  fetchLutColors: vi.fn(),
  cropImage: vi.fn(),
  convertBatch: vi.fn(),
  replaceColor: vi.fn(),
  detectRegion: vi.fn(),
  regionReplace: vi.fn(),
  resetReplacements: vi.fn(),
}));

vi.stubGlobal(
  "URL",
  Object.assign(globalThis.URL ?? {}, {
    createObjectURL: vi.fn(() => "blob:mock-url"),
    revokeObjectURL: vi.fn(),
  }),
);

vi.stubGlobal(
  "Image",
  class {
    onload: (() => void) | null = null;
    set src(_: string) {
      if (this.onload) this.onload();
    }
    naturalWidth = 100;
    naturalHeight = 100;
  },
);

import { useConverterStore } from "../stores/converter";
import type { RegionReplaceResponse } from "../api/types";

const glbUrlPath = fc
  .stringMatching(/^[a-z0-9]{6,12}$/)
  .map((id) => `/api/files/${id}`);

const optionalGlbUrl: fc.Arbitrary<string | null> = fc.oneof(
  fc.constant(null),
  glbUrlPath,
);

const hexColor = fc
  .stringMatching(/^[0-9a-f]{6}$/)
  .filter((s) => s.length === 6);

const contourPolygon = fc.array(
  fc
    .tuple(
      fc.float({ min: 0, max: 100, noNaN: true }),
      fc.float({ min: 0, max: 100, noNaN: true }),
    )
    .map(([x, y]) => [x, y]),
  { minLength: 3, maxLength: 8 },
);

const colorContoursData: fc.Arbitrary<Record<string, number[][][]>> = fc.dictionary(
  hexColor.map((h) => `#${h}`),
  fc.array(contourPolygon, { minLength: 1, maxLength: 3 }),
  { minKeys: 1, maxKeys: 4 },
);

const optionalColorContours: fc.Arbitrary<Record<string, number[][][]> | null> =
  fc.oneof(fc.constant(null), colorContoursData);

const regionReplaceResponse: fc.Arbitrary<RegionReplaceResponse> = fc.record({
  preview_url: fc.constant("/api/files/preview-mock"),
  preview_glb_url: optionalGlbUrl,
  color_contours: optionalColorContours,
  message: fc.constant("Region color replaced successfully"),
});

const existingGlbUrl = glbUrlPath;

const existingContours: fc.Arbitrary<Record<string, number[][][]>> = fc.dictionary(
  hexColor.map((h) => `#${h}`),
  fc.array(contourPolygon, { minLength: 1, maxLength: 2 }),
  { minKeys: 1, maxKeys: 3 },
);

function resetStore(overrides?: Partial<ReturnType<typeof useConverterStore.getState>>) {
  useConverterStore.setState({
    sessionId: "test-session",
    regionData: {
      regionId: "r1",
      colorHex: "#ff0000",
      pixelCount: 100,
      previewUrl: "/mock",
    },
    replacePreviewLoading: false,
    error: null,
    previewImageUrl: null,
    previewGlbUrl: null,
    colorContours: {},
    threemfDiskPath: null,
    downloadUrl: null,
    ...overrides,
  });
}

describe("region 3d preview sync", () => {
  beforeEach(() => {
    resetStore();
    vi.clearAllMocks();
  });

  it("updates previewGlbUrl and colorContours only when response fields are non-null", async () => {
    const { regionReplace } = await import("../api/converter");

    await fc.assert(
      fc.asyncProperty(
        regionReplaceResponse,
        existingGlbUrl,
        existingContours,
        async (response, prevGlbUrl, prevContours) => {
          resetStore({ previewGlbUrl: prevGlbUrl, colorContours: prevContours });
          (regionReplace as ReturnType<typeof vi.fn>).mockResolvedValue(response);

          await useConverterStore.getState().applyRegionReplace("ff0000");
          const state = useConverterStore.getState();

          if (response.preview_glb_url) {
            expect(state.previewGlbUrl).toBe(response.preview_glb_url);
          } else {
            expect(state.previewGlbUrl).toBe(prevGlbUrl);
          }

          if (response.color_contours) {
            expect(state.colorContours).toEqual(response.color_contours);
          } else {
            expect(state.colorContours).toEqual(prevContours);
          }
        },
      ),
      { numRuns: 100 },
    );
  });

  it("sets previewGlbUrl to response.preview_glb_url when present", async () => {
    const { regionReplace } = await import("../api/converter");

    await fc.assert(
      fc.asyncProperty(glbUrlPath, async (glbPath) => {
        resetStore({ previewGlbUrl: null });

        const response: RegionReplaceResponse = {
          preview_url: "/api/files/preview-mock",
          preview_glb_url: glbPath,
          color_contours: null,
          message: "ok",
        };
        (regionReplace as ReturnType<typeof vi.fn>).mockResolvedValue(response);

        await useConverterStore.getState().applyRegionReplace("aabbcc");
        expect(useConverterStore.getState().previewGlbUrl).toBe(glbPath);
      }),
      { numRuns: 100 },
    );
  });

  it("preserves existing previewGlbUrl when response.preview_glb_url is null", async () => {
    const { regionReplace } = await import("../api/converter");
    const existingUrl = "/api/files/existing-glb-123";
    resetStore({ previewGlbUrl: existingUrl });

    const response: RegionReplaceResponse = {
      preview_url: "/api/files/preview-after-replace",
      preview_glb_url: null,
      color_contours: null,
      message: "Region color replaced successfully",
    };
    (regionReplace as ReturnType<typeof vi.fn>).mockResolvedValue(response);

    await useConverterStore.getState().applyRegionReplace("00ff00");

    const state = useConverterStore.getState();
    expect(state.previewGlbUrl).toBe(existingUrl);
    expect(state.previewImageUrl).toBe("/api/files/preview-after-replace");
  });

  it("preserves existing colorContours when response.color_contours is null", async () => {
    const { regionReplace } = await import("../api/converter");

    const existing = {
      "#ff0000": [[[0, 0], [10, 0], [10, 10]]],
      "#00ff00": [[[5, 5], [15, 5], [15, 15]]],
    };
    resetStore({ colorContours: existing });

    const response: RegionReplaceResponse = {
      preview_url: "/api/files/preview-after-replace",
      preview_glb_url: null,
      color_contours: null,
      message: "ok",
    };
    (regionReplace as ReturnType<typeof vi.fn>).mockResolvedValue(response);

    await useConverterStore.getState().applyRegionReplace("0000ff");
    expect(useConverterStore.getState().colorContours).toEqual(existing);
  });
});
