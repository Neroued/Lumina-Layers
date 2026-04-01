import { create } from "zustand";
import type { ExtractorColorMode, ExtractorPage } from "../api/types";
import {
  ExtractorColorMode as ExtractorColorModeEnum,
  ExtractorPage as ExtractorPageEnum,
} from "../api/types";
import {
  confirmPalette,
  extractColors,
  manualFixCell,
  mergeEightColor,
  mergeFiveColorExtended,
  previewAutoWb,
  rotateExtractorImage,
} from "../api/extractor";
import type { ExtractorPaletteEntry } from "../api/types";
import { clampValue } from "./converter";
import { uploadImagePreview } from "../api/system";
import { normalizeResourceUrl } from "../utils/resourceUrl";

export const RAW_EXTENSIONS = new Set([
  ".dng",
  ".cr2",
  ".cr3",
  ".nef",
  ".arw",
  ".orf",
  ".rw2",
  ".raf",
  ".pef",
  ".srw",
  ".raw",
]);

export const ACCEPT_EXTRACTOR_FORMATS =
  "image/*," + Array.from(RAW_EXTENSIONS).join(",");

export function isRawFile(file: File): boolean {
  const ext = file.name.toLowerCase().slice(file.name.lastIndexOf("."));
  return RAW_EXTENSIONS.has(ext);
}

// ========== State Interface ==========

export interface ExtractorState {
  // 鍥剧墖
  imageFile: File | null;
  imagePreviewUrl: string | null;
  imageNaturalWidth: number | null;
  imageNaturalHeight: number | null;

  // 棰滆壊妯″紡涓庨〉鐮?
  color_mode: ExtractorColorMode;
  page: ExtractorPage;

  // 瑙掔偣
  corner_points: Array<[number, number]>;

  // 鎻愬彇鍙傛暟
  offset_x: number;
  offset_y: number;
  zoom: number;
  distortion: number;
  vignette_correction: boolean;
  auto_wb: boolean;
  originalPreviewUrl: string | null;

  // API 鐘舵€?
  isLoading: boolean;
  error: string | null;
  session_id: string | null;

  // 鎻愬彇缁撴灉
  lut_download_url: string | null;
  warp_view_url: string | null;
  lut_preview_url: string | null;

  // 鎵嬪姩淇
  manualFixLoading: boolean;
  manualFixError: string | null;

  // 8鑹插弻椤电姸鎬?
  page1Extracted: boolean;
  page2Extracted: boolean;
  mergeLoading: boolean;
  mergeError: string | null;

  // 5鑹叉墿灞曞弻椤电姸鎬?
  page1Extracted_5c: boolean;
  page2Extracted_5c: boolean;

  // 璋冭壊鏉跨‘璁?
  manufacturer: string;
  type: string;
  defaultPalette: ExtractorPaletteEntry[];
  paletteConfirmed: boolean;
  paletteConfirmLoading: boolean;
  paletteConfirmError: string | null;
}

// ========== Actions Interface ==========

export interface ExtractorActions {
  setImageFile: (file: File | null) => void;
  rotateImage: () => Promise<void>;
  setColorMode: (mode: ExtractorColorMode) => void;
  setPage: (page: ExtractorPage) => void;
  addCornerPoint: (point: [number, number]) => void;
  clearCornerPoints: () => void;
  setOffsetX: (value: number) => void;
  setOffsetY: (value: number) => void;
  setZoom: (value: number) => void;
  setDistortion: (value: number) => void;
  setVignetteCorrection: (value: boolean) => void;
  setAutoWb: (value: boolean) => Promise<void>;
  setManufacturer: (value: string) => void;
  setType: (value: string) => void;
  submitExtract: () => Promise<void>;
  submitManualFix: (row: number, col: number, color: string) => Promise<void>;
  submitMerge: () => Promise<void>;
  setError: (error: string | null) => void;
  clearError: () => void;
  updatePaletteEntry: (
    index: number,
    entry: Partial<ExtractorPaletteEntry>,
  ) => void;
  submitConfirmPalette: () => Promise<void>;
}

// ========== Default State ==========

const DEFAULT_STATE: ExtractorState = {
  imageFile: null,
  imagePreviewUrl: null,
  imageNaturalWidth: null,
  imageNaturalHeight: null,
  color_mode: ExtractorColorModeEnum.FOUR_COLOR_RYBW,
  page: ExtractorPageEnum.PAGE_1,
  corner_points: [],
  offset_x: 0,
  offset_y: 0,
  zoom: 1.0,
  distortion: 0.0,
  vignette_correction: false,
  auto_wb: false,
  originalPreviewUrl: null,
  isLoading: false,
  error: null,
  session_id: null,
  lut_download_url: null,
  warp_view_url: null,
  lut_preview_url: null,
  manualFixLoading: false,
  manualFixError: null,
  page1Extracted: false,
  page2Extracted: false,
  mergeLoading: false,
  mergeError: null,
  page1Extracted_5c: false,
  page2Extracted_5c: false,
  manufacturer: "",
  type: "",
  defaultPalette: [],
  paletteConfirmed: false,
  paletteConfirmLoading: false,
  paletteConfirmError: null,
};

// ========== Store ==========

export const useExtractorStore = create<ExtractorState & ExtractorActions>(
  (set, get) => ({
    ...DEFAULT_STATE,

    setImageFile: (file: File | null) => {
      // Revoke previous blob URL to avoid memory leaks
      const prev = get().imagePreviewUrl;
      if (prev && prev.startsWith("blob:")) {
        URL.revokeObjectURL(prev);
      }

      if (!file) {
        set({
          imageFile: null,
          imagePreviewUrl: null,
          imageNaturalWidth: null,
          imageNaturalHeight: null,
          corner_points: [],
          session_id: null,
          lut_download_url: null,
          warp_view_url: null,
          lut_preview_url: null,
          defaultPalette: [],
          paletteConfirmed: false,
          paletteConfirmError: null,
          auto_wb: false,
          originalPreviewUrl: null,
        });
        return;
      }

      if (isRawFile(file)) {
        set({
          imageFile: file,
          imagePreviewUrl: null,
          imageNaturalWidth: null,
          imageNaturalHeight: null,
          corner_points: [],
          session_id: null,
          lut_download_url: null,
          warp_view_url: null,
          lut_preview_url: null,
          defaultPalette: [],
          paletteConfirmed: false,
          paletteConfirmError: null,
          auto_wb: false,
          originalPreviewUrl: null,
        });
        uploadImagePreview(file)
          .then(({ preview_url, width, height }) => {
            set({
              imagePreviewUrl: preview_url,
              imageNaturalWidth: width,
              imageNaturalHeight: height,
            });
          })
          .catch(() => {
            set({ error: "RAW 鍥剧墖棰勮澶辫触锛岃妫€鏌ュ悗绔槸鍚﹀畨瑁?rawpy" });
          });
        return;
      }

      const previewUrl = URL.createObjectURL(file);

      // Load image to get natural dimensions
      const img = new Image();
      img.onload = () => {
        set({
          imageNaturalWidth: img.naturalWidth,
          imageNaturalHeight: img.naturalHeight,
        });
      };
      img.src = previewUrl;

      set({
        imageFile: file,
        imagePreviewUrl: previewUrl,
        imageNaturalWidth: null,
        imageNaturalHeight: null,
        // Clear previous corner points and extraction results
        corner_points: [],
        session_id: null,
        lut_download_url: null,
        warp_view_url: null,
        lut_preview_url: null,
        defaultPalette: [],
        paletteConfirmed: false,
        paletteConfirmError: null,
        auto_wb: false,
        originalPreviewUrl: null,
      });
    },

    rotateImage: async () => {
      const { imageFile, imagePreviewUrl } = get();
      if (!imageFile) return;

      set({ isLoading: true, error: null });
      try {
        const { preview_url, width, height } = await rotateExtractorImage(
          imageFile,
          imageFile.name,
        );

        // Fetch rotated image as blob to create a new File for subsequent extract calls
        const res = await fetch(preview_url);
        const blob = await res.blob();
        const baseName = imageFile.name.replace(/\.[^.]+$/, "");
        const rotatedFile = new File([blob], `${baseName}.png`, {
          type: "image/png",
        });

        // Revoke previous blob URL
        if (imagePreviewUrl && imagePreviewUrl.startsWith("blob:")) {
          URL.revokeObjectURL(imagePreviewUrl);
        }

        set({
          imageFile: rotatedFile,
          imagePreviewUrl: preview_url,
          imageNaturalWidth: width,
          imageNaturalHeight: height,
          corner_points: [],
          isLoading: false,
          auto_wb: false,
          originalPreviewUrl: null,
        });
      } catch (err) {
        set({
          error: err instanceof Error ? err.message : "鍥剧墖鏃嬭浆澶辫触",
          isLoading: false,
        });
      }
    },

    setColorMode: (mode: ExtractorColorMode) =>
      set({
        color_mode: mode,
        // Reset 8-color and 5-color page tracking when switching modes
        page1Extracted: false,
        page2Extracted: false,
        page1Extracted_5c: false,
        page2Extracted_5c: false,
        mergeError: null,
        defaultPalette: [],
        paletteConfirmed: false,
        paletteConfirmError: null,
      }),

    setPage: (page: ExtractorPage) => set({ page }),

    addCornerPoint: (point: [number, number]) => {
      const { corner_points } = get();
      if (corner_points.length >= 4) return;
      set({ corner_points: [...corner_points, point] });
    },

    clearCornerPoints: () => set({ corner_points: [] }),

    setOffsetX: (value: number) =>
      set({ offset_x: clampValue(value, -30, 30) }),

    setOffsetY: (value: number) =>
      set({ offset_y: clampValue(value, -30, 30) }),

    setZoom: (value: number) => set({ zoom: clampValue(value, 0.8, 1.2) }),

    setDistortion: (value: number) =>
      set({ distortion: clampValue(value, -0.2, 0.2) }),

    setVignetteCorrection: (value: boolean) =>
      set({ vignette_correction: value }),

    setAutoWb: async (value: boolean) => {
      const { imageFile, imagePreviewUrl, originalPreviewUrl } = get();
      if (!imageFile) {
        set({ auto_wb: value });
        return;
      }

      if (value) {
        // Enable auto white-balance: save original preview and fetch adjusted preview
        set({ isLoading: true, error: null, auto_wb: true });
        try {
          const saved = originalPreviewUrl ?? imagePreviewUrl;
          const { preview_url, width, height } = await previewAutoWb(
            imageFile,
            imageFile.name,
          );
          set({
            originalPreviewUrl: saved,
            imagePreviewUrl: preview_url,
            imageNaturalWidth: width,
            imageNaturalHeight: height,
            isLoading: false,
          });
        } catch (err) {
          set({
            auto_wb: false,
            error: err instanceof Error ? err.message : "White balance preview failed",
            isLoading: false,
          });
        }
      } else {
        // 鍏抽棴鐧藉钩琛★細鎭㈠鍘熷棰勮
        if (originalPreviewUrl) {
          set({
            auto_wb: false,
            imagePreviewUrl: originalPreviewUrl,
            originalPreviewUrl: null,
          });
        } else {
          set({ auto_wb: false });
        }
      }
    },

    setManufacturer: (value: string) => set({ manufacturer: value }),

    setType: (value: string) => set({ type: value }),

    submitExtract: async () => {
      const state = get();
      if (!state.imageFile || state.corner_points.length < 4) return;

      set({ isLoading: true, error: null });
      try {
        const response = await extractColors(state.imageFile, {
          corner_points: state.corner_points,
          color_mode: state.color_mode,
          page: state.page,
          offset_x: state.offset_x,
          offset_y: state.offset_y,
          zoom: state.zoom,
          distortion: state.distortion,
          vignette_correction: state.vignette_correction,
          auto_wb: state.auto_wb,
        });
        
        // Track 8-color page extraction status
        const pageUpdate: Partial<ExtractorState> = {};
        if (state.color_mode === ExtractorColorModeEnum.EIGHT_COLOR) {
          if (state.page === ExtractorPageEnum.PAGE_1) {
            pageUpdate.page1Extracted = true;
          } else {
            pageUpdate.page2Extracted = true;
          }
        }
        // Track 5-Color Extended page extraction status
        if (state.color_mode === ExtractorColorModeEnum.FIVE_COLOR_EXT) {
          if (state.page === ExtractorPageEnum.PAGE_1) {
            pageUpdate.page1Extracted_5c = true;
          } else {
            pageUpdate.page2Extracted_5c = true;
          }
        }

        set({
          session_id: response.session_id,
          lut_download_url: response.lut_download_url
            ? normalizeResourceUrl(response.lut_download_url)
            : null,
          warp_view_url: response.warp_view_url
            ? normalizeResourceUrl(response.warp_view_url)
            : null,
          lut_preview_url: response.lut_preview_url
            ? normalizeResourceUrl(response.lut_preview_url)
            : null,
          isLoading: false,
          defaultPalette: response.default_palette ?? [],
          paletteConfirmed: false,
          paletteConfirmError: null,
          ...pageUpdate,
        });
      } catch (err) {
        set({
          error: err instanceof Error ? err.message : "棰滆壊鎻愬彇澶辫触锛岃閲嶈瘯",
          isLoading: false,
        });
      }
    },

    submitManualFix: async (row: number, col: number, color: string) => {
      const state = get();
      if (!state.session_id) return;

      set({ manualFixLoading: true, manualFixError: null });
      try {
        const response = await manualFixCell(
          state.session_id,
          [row, col],
          color,
        );
        set({
          lut_preview_url: response.lut_preview_url
            ? normalizeResourceUrl(response.lut_preview_url)
            : null,
          manualFixLoading: false,
        });
      } catch (err) {
        set({
          manualFixError:
            err instanceof Error ? err.message : "鎵嬪姩淇澶辫触锛岃閲嶈瘯",
          manualFixLoading: false,
        });
      }
    },

    submitMerge: async () => {
      const state = get();
      // Determine which page states to check based on color_mode
      const is5c = state.color_mode === ExtractorColorModeEnum.FIVE_COLOR_EXT;
      const bothExtracted = is5c
        ? state.page1Extracted_5c && state.page2Extracted_5c
        : state.page1Extracted && state.page2Extracted;

      if (!bothExtracted) return;

      set({ mergeLoading: true, mergeError: null });
      try {
        const response = is5c
          ? await mergeFiveColorExtended()
          : await mergeEightColor();
                set({
          session_id: response.session_id,
          lut_download_url: response.lut_download_url
            ? normalizeResourceUrl(response.lut_download_url)
            : null,
          warp_view_url: response.warp_view_url
            ? normalizeResourceUrl(response.warp_view_url)
            : null,
          lut_preview_url: response.lut_preview_url
            ? normalizeResourceUrl(response.lut_preview_url)
            : null,
          defaultPalette: response.default_palette ?? [],
          paletteConfirmed: false,
          paletteConfirmError: null,
          mergeLoading: false,
        });
      } catch (err) {
        set({
          mergeError: err instanceof Error ? err.message : "鍚堝苟澶辫触锛岃閲嶈瘯",
          mergeLoading: false,
        });
      }
    },

    setError: (error: string | null) => set({ error }),
    clearError: () => set({ error: null }),

    updatePaletteEntry: (
      index: number,
      entry: Partial<ExtractorPaletteEntry>,
    ) => {
      const palette = [...get().defaultPalette];
      if (index >= 0 && index < palette.length) {
        palette[index] = { ...palette[index], ...entry };
        set({ defaultPalette: palette });
      }
    },

    submitConfirmPalette: async () => {
      const state = get();
      if (!state.session_id || state.defaultPalette.length === 0) return;

      set({ paletteConfirmLoading: true, paletteConfirmError: null });
      try {
        await confirmPalette({
          session_id: state.session_id,
          manufacturer: state.manufacturer.trim(),
          type: state.type.trim(),
          palette: state.defaultPalette.map((entry) => ({
            ...entry,
            color_name: entry.color_name?.trim() || null,
          })),
        });
        set({ paletteConfirmed: true, paletteConfirmLoading: false });
      } catch (err) {
        set({
          paletteConfirmError:
            err instanceof Error ? err.message : "Palette confirmation failed",
          paletteConfirmLoading: false,
        });
      }
    },
  }),
);


