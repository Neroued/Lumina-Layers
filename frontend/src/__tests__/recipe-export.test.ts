import { describe, it, expect } from "vitest";
import { exportConverterRecipe } from "../recipe/exportRecipe";
import type { ConverterState } from "../stores/converter/store";
import { DEFAULT_STATE } from "../stores/converter";
import type { SettingsState } from "../stores/settingsStore";
import { DEFAULT_SETTINGS } from "../stores/settingsStore";

function makeState(overrides?: Partial<ConverterState>): ConverterState {
  return { ...DEFAULT_STATE, ...overrides } as ConverterState;
}

function makeSettings(overrides?: Partial<SettingsState>): SettingsState {
  return { ...DEFAULT_SETTINGS, ...overrides };
}

describe("recipe/exportRecipe", () => {
  describe("exportConverterRecipe", () => {
    it("exports base parameters correctly", () => {
      const state = makeState({
        lut_name: "TestLUT",
        color_mode: "4-Color (RYBW)" as ConverterState["color_mode"],
        modeling_mode: "high-fidelity" as ConverterState["modeling_mode"],
        target_width_mm: 100,
        target_height_mm: 75,
        auto_bg: true,
        bg_tol: 25,
        quantize_colors: 64,
        enable_cleanup: true,
        hue_enable: true,
        chroma_gate: 20,
      });

      const recipe = exportConverterRecipe(state, makeSettings(), "fp123");

      expect(recipe.base.lut.name).toBe("TestLUT");
      expect(recipe.base.lut.fingerprint).toBe("fp123");
      expect(recipe.base.color_mode).toBe("4-Color (RYBW)");
      expect(recipe.base.target_width_mm).toBe(100);
      expect(recipe.base.target_height_mm).toBe(75);
      expect(recipe.base.hue_enable).toBe(true);
      expect(recipe.base.chroma_gate).toBe(20);
    });

    it("exports geometry parameters including loop", () => {
      const state = makeState({
        add_loop: true,
        loop_width: 6,
        loop_length: 10,
        loop_hole: 4,
        loop_angle: 90,
        loop_offset_x: 2,
        loop_offset_y: -1,
        loop_position_preset: "bottom-center",
      });

      const recipe = exportConverterRecipe(state, makeSettings(), "fp");
      expect(recipe.geometry.add_loop).toBe(true);
      expect(recipe.geometry.loop_angle).toBe(90);
      expect(recipe.geometry.loop_position_preset).toBe("bottom-center");
    });

    it("merges colorRemapMap into replacement_regions", () => {
      const state = makeState({
        replacement_regions: [
          { quantized_hex: "aa0000", matched_hex: "bb0000", replacement_hex: "cc0000" },
        ],
        colorRemapMap: { dd0000: "ee0000" },
        palette: [
          { quantized_hex: "dd0000", matched_hex: "dd0000", pixel_count: 10, percentage: 0.5 },
        ],
      });

      const recipe = exportConverterRecipe(state, makeSettings(), "fp");

      // Should have 2 entries: original + remapped
      expect(recipe.color_ops.replacement_regions).toHaveLength(2);
      // All hex values should have '#' prefix
      expect(recipe.color_ops.replacement_regions[0].quantized_hex).toBe("#aa0000");
      expect(recipe.color_ops.replacement_regions[1].matched_hex).toBe("#dd0000");
    });

    it("serializes free_color_set with '#' prefix", () => {
      const state = makeState({
        free_color_set: new Set(["ff0000", "00ff00"]),
      });

      const recipe = exportConverterRecipe(state, makeSettings(), "fp");
      expect(recipe.color_ops.free_color_set).toEqual(["#ff0000", "#00ff00"]);
    });

    it("normalizes color_height_map keys with '#' prefix", () => {
      const state = makeState({
        enable_relief: true,
        color_height_map: { ff0000: 0.3, "00ff00": 0.5 },
      });

      const recipe = exportConverterRecipe(state, makeSettings(), "fp");
      expect(recipe.relief.color_height_map).toEqual({ "#ff0000": 0.3, "#00ff00": 0.5 });
    });

    it("exports device info from settings", () => {
      const settings = makeSettings({
        printerModel: "custom-printer",
        slicerSoftware: "OrcaSlicer",
      });

      const recipe = exportConverterRecipe(makeState(), settings, "fp");
      expect(recipe.device.printer_id).toBe("custom-printer");
      expect(recipe.device.slicer).toBe("OrcaSlicer");
    });

    it("exports large format parameters", () => {
      const state = makeState({
        largeFormatEnabled: true,
        tileWidthMm: 180,
        tileHeightMm: 140,
      });

      const recipe = exportConverterRecipe(state, makeSettings(), "fp");
      expect(recipe.large_format.large_format_enabled).toBe(true);
      expect(recipe.large_format.tile_width_mm).toBe(180);
      expect(recipe.large_format.tile_height_mm).toBe(140);
    });

    it("does NOT include UI-only state fields", () => {
      const state = makeState();
      const recipe = exportConverterRecipe(state, makeSettings(), "fp");
      const json = JSON.stringify(recipe);

      // These UI-only fields should NOT appear in the recipe
      expect(json).not.toContain("sessionId");
      expect(json).not.toContain("isLoading");
      expect(json).not.toContain("isGenerating");
      expect(json).not.toContain("previewGlbUrl");
      expect(json).not.toContain("batchMode");
      expect(json).not.toContain("cropModalOpen");
    });
  });
});
