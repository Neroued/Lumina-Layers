import { describe, it, expect } from "vitest";
import fc from "fast-check";
import { fileToBase64, base64ToFile, sha256Hex, sha256String } from "../recipe/utils";
import { exportConverterRecipe } from "../recipe/exportRecipe";
import { restoreConverterRecipe } from "../recipe/importRecipe";
import { DEFAULT_STATE } from "../stores/converter";
import { DEFAULT_SETTINGS } from "../stores/settingsStore";
import type { ConverterState } from "../stores/converter/store";
import type { LutInfo } from "../api/types";
import { ColorMode } from "../api/types";

// ========== Arbitraries ==========

const arbHexColor = fc
  .array(fc.constantFrom(..."0123456789abcdef".split("")), { minLength: 6, maxLength: 6 })
  .map((chars) => chars.join(""));

const arbBytes = fc.uint8Array({ minLength: 1, maxLength: 128 });

const arbFilename = fc
  .array(fc.constantFrom(..."abcdefghijklmnopqrstuvwxyz0123456789".split("")), {
    minLength: 1,
    maxLength: 20,
  })
  .map((chars) => `${chars.join("")}.png`);

const arbMimeType = fc.constantFrom("image/png", "image/jpeg", "image/webp");

// ========== Property Tests ==========

describe("recipe round-trip properties", () => {
  it("base64 round-trip preserves file name, type, and content", async () => {
    await fc.assert(
      fc.asyncProperty(arbBytes, arbFilename, arbMimeType, async (bytes, name, mime) => {
        const original = new File([bytes], name, { type: mime });
        const b64 = await fileToBase64(original);
        const restored = base64ToFile(b64, name, mime);

        expect(restored.name).toBe(name);
        expect(restored.type).toBe(mime);
        expect(restored.size).toBe(original.size);

        const origBuf = new Uint8Array(await original.arrayBuffer());
        const restBuf = new Uint8Array(await restored.arrayBuffer());
        expect(restBuf).toEqual(origBuf);
      }),
      { numRuns: 30 },
    );
  });

  it("sha256Hex is deterministic for the same input", async () => {
    await fc.assert(
      fc.asyncProperty(arbBytes, async (bytes) => {
        const buf = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
        const h1 = await sha256Hex(buf);
        const h2 = await sha256Hex(buf);
        expect(h1).toBe(h2);
        expect(h1).toHaveLength(64);
      }),
      { numRuns: 20 },
    );
  });

  it("sha256String is deterministic for the same string", async () => {
    await fc.assert(
      fc.asyncProperty(fc.string({ minLength: 0, maxLength: 200 }), async (s) => {
        const h1 = await sha256String(s);
        const h2 = await sha256String(s);
        expect(h1).toBe(h2);
        expect(h1).toHaveLength(64);
      }),
      { numRuns: 20 },
    );
  });

  it("export → import round-trip preserves key converter parameters", () => {
    const arbState = fc.record({
      lut_name: fc.constantFrom("LUT-A", "LUT-B"),
      target_width_mm: fc.integer({ min: 10, max: 400 }),
      target_height_mm: fc.integer({ min: 10, max: 400 }),
      spacer_thick: fc.double({ min: 0.2, max: 3.5, noNaN: true }),
      auto_bg: fc.boolean(),
      bg_tol: fc.integer({ min: 0, max: 100 }),
      quantize_colors: fc.integer({ min: 2, max: 128 }),
      enable_cleanup: fc.boolean(),
      hue_enable: fc.boolean(),
      chroma_gate: fc.integer({ min: 0, max: 100 }),
      add_loop: fc.boolean(),
      loop_angle: fc.integer({ min: -180, max: 180 }),
      enable_relief: fc.boolean(),
      enable_outline: fc.boolean(),
      outline_width: fc.double({ min: 0.1, max: 2.0, noNaN: true }),
      enable_cloisonne: fc.boolean(),
      enable_coating: fc.boolean(),
      largeFormatEnabled: fc.boolean(),
      tileWidthMm: fc.integer({ min: 50, max: 500 }),
      tileHeightMm: fc.integer({ min: 50, max: 500 }),
    });

    const localLuts: LutInfo[] = [
      { name: "LUT-A", color_mode: ColorMode.FOUR_COLOR_RYBW, path: "/a", fingerprint: "fpA" },
      { name: "LUT-B", color_mode: ColorMode.SIX_COLOR, path: "/b", fingerprint: "fpB" },
    ];
    const localFP: Record<string, string> = { "LUT-A": "fpA", "LUT-B": "fpB" };
    const fpForLut: Record<string, string> = { "LUT-A": "fpA", "LUT-B": "fpB" };

    fc.assert(
      fc.property(arbState, (overrides) => {
        const state = { ...DEFAULT_STATE, ...overrides } as ConverterState;
        const recipe = exportConverterRecipe(state, DEFAULT_SETTINGS, fpForLut[overrides.lut_name]);

        // Build a minimal LuminaRecipe wrapper for restoreConverterRecipe
        const fullRecipe = {
          format: "lumina-recipe" as const,
          schema_version: 1,
          app_version: "0.0.0",
          created_at: new Date().toISOString(),
          source: "converter" as const,
          cover: { width: 1, height: 1, mime_type: "image/png" as const },
          asset: {
            primary: {
              filename: "test.png",
              mime_type: "image/png",
              byte_size: 4,
              sha256: "abcd",
              encoding: "base64" as const,
              payload_b64: "dGVzdA==",
            },
          },
          recipe: { converter: recipe },
          integrity: {
            recipe_sha256: "0".repeat(64),
            asset_checksums: { primary: "abcd" },
          },
          compat: { min_schema_version: 1 },
          warnings: [] as string[],
        };

        const { state: restored } = restoreConverterRecipe(fullRecipe, localLuts, localFP);

        // Key parameters must survive round-trip
        expect(restored.lut_name).toBe(overrides.lut_name);
        expect(restored.target_width_mm).toBe(overrides.target_width_mm);
        expect(restored.target_height_mm).toBe(overrides.target_height_mm);
        expect(restored.auto_bg).toBe(overrides.auto_bg);
        expect(restored.bg_tol).toBe(overrides.bg_tol);
        expect(restored.quantize_colors).toBe(overrides.quantize_colors);
        expect(restored.enable_cleanup).toBe(overrides.enable_cleanup);
        expect(restored.hue_enable).toBe(overrides.hue_enable);
        expect(restored.chroma_gate).toBe(overrides.chroma_gate);
        expect(restored.add_loop).toBe(overrides.add_loop);
        expect(restored.loop_angle).toBe(overrides.loop_angle);
        expect(restored.enable_relief).toBe(overrides.enable_relief);
        expect(restored.enable_outline).toBe(overrides.enable_outline);
        expect(restored.enable_cloisonne).toBe(overrides.enable_cloisonne);
        expect(restored.enable_coating).toBe(overrides.enable_coating);
        expect(restored.largeFormatEnabled).toBe(overrides.largeFormatEnabled);
        expect(restored.tileWidthMm).toBe(overrides.tileWidthMm);
        expect(restored.tileHeightMm).toBe(overrides.tileHeightMm);
      }),
      { numRuns: 50 },
    );
  });

  it("free_color_set survives Set→Array→Set round-trip", () => {
    fc.assert(
      fc.property(fc.uniqueArray(arbHexColor, { minLength: 0, maxLength: 8 }), (hexes) => {
        const state = {
          ...DEFAULT_STATE,
          free_color_set: new Set(hexes),
        } as ConverterState;

        const recipe = exportConverterRecipe(state, DEFAULT_SETTINGS, "fp");
        // Exported as array with '#' prefix
        expect(recipe.color_ops.free_color_set).toHaveLength(hexes.length);

        // Build full recipe wrapper to test import
        const fullRecipe = {
          format: "lumina-recipe" as const,
          schema_version: 1,
          app_version: "0.0.0",
          created_at: new Date().toISOString(),
          source: "converter" as const,
          cover: { width: 1, height: 1, mime_type: "image/png" as const },
          asset: {
            primary: {
              filename: "t.png",
              mime_type: "image/png",
              byte_size: 4,
              sha256: "a",
              encoding: "base64" as const,
              payload_b64: "dGVzdA==",
            },
          },
          recipe: { converter: recipe },
          integrity: { recipe_sha256: "0".repeat(64), asset_checksums: { primary: "a" } },
          compat: { min_schema_version: 1 },
          warnings: [] as string[],
        };

        const { state: restored } = restoreConverterRecipe(fullRecipe, [], {});
        // Restored Set should match original (both without '#')
        expect(restored.free_color_set).toEqual(new Set(hexes));
      }),
      { numRuns: 30 },
    );
  });
});
