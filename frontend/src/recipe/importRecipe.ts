/**
 * Recipe import adapter: parses recipe files and maps back to converter store state.
 * 配方导入适配器：解析配方文件并映射回 converter store 状态。
 */

import type { LuminaRecipe } from "./types";
import type { ConverterState } from "../stores/converter/store";
import type { ColorReplacementItem, LutInfo } from "../api/types";
import { extractRecipeFromPng } from "./pngMetadata";
import { migrateRecipe } from "./migration";
import { base64ToFile } from "./utils";

// ========== Hex normalization ==========

/** Strip '#' prefix from a hex color string. */
function stripHash(hex: string): string {
  return hex.startsWith("#") ? hex.slice(1) : hex;
}

// ========== Source detection ==========

export type RecipeFileSource = "png" | "json";

/**
 * Detect whether a file is a Lumina share card PNG or a .lumina.json sidecar.
 * 检测文件是 Lumina 分享卡 PNG 还是 .lumina.json sidecar。
 */
export function detectRecipeFileType(file: File): RecipeFileSource | null {
  const name = file.name.toLowerCase();
  if (name.endsWith(".lumina.json")) return "json";
  if (name.endsWith(".png") && file.type === "image/png") return "png";
  // Also accept PNG files without explicit type (some OS don't set MIME)
  if (name.endsWith(".png")) return "png";
  return null;
}

// ========== Parse entry ==========

export interface ParsedRecipe {
  recipe: LuminaRecipe;
  source: RecipeFileSource;
}

/**
 * Parse a recipe from a file (PNG or JSON).
 * 从文件（PNG 或 JSON）中解析配方。
 *
 * @throws Error if the file cannot be parsed or contains invalid recipe data.
 */
export async function parseRecipeFile(file: File): Promise<ParsedRecipe> {
  const fileType = detectRecipeFileType(file);

  if (fileType === "json") {
    const text = await file.text();
    let raw: unknown;
    try {
      raw = JSON.parse(text);
    } catch {
      throw new Error("Invalid .lumina.json: failed to parse JSON");
    }
    const recipe = migrateRecipe(raw);
    return { recipe, source: "json" };
  }

  if (fileType === "png") {
    const recipe = await extractRecipeFromPng(file);
    if (!recipe) {
      throw new Error("PNG file does not contain Lumina recipe metadata");
    }
    const migrated = migrateRecipe(recipe);
    return { recipe: migrated, source: "png" };
  }

  throw new Error(`Unsupported file type: ${file.name}`);
}

// ========== LUT matching ==========

export type LutMatchResult =
  | { matched: true; lutName: string; matchType: "fingerprint" | "name" }
  | { matched: false; originalName: string; originalFingerprint: string };

/**
 * Match a LUT reference against the locally available LUT list.
 * 将 LUT 引用与本地可用的 LUT 列表匹配。
 *
 * Priority: fingerprint → name → not found.
 */
export function matchLut(
  lutRef: { name: string; fingerprint: string },
  localLuts: LutInfo[],
  localFingerprints: Record<string, string>,
): LutMatchResult {
  // 1. Fingerprint match
  for (const lut of localLuts) {
    const fp = localFingerprints[lut.name];
    if (fp && fp === lutRef.fingerprint) {
      return { matched: true, lutName: lut.name, matchType: "fingerprint" };
    }
  }

  // 2. Name match
  const byName = localLuts.find((l) => l.name === lutRef.name);
  if (byName) {
    return { matched: true, lutName: byName.name, matchType: "name" };
  }

  // 3. Not found
  return {
    matched: false,
    originalName: lutRef.name,
    originalFingerprint: lutRef.fingerprint,
  };
}

// ========== Restore result ==========

export interface RestoreResult {
  /** Partial state to merge into converter store. */
  state: Partial<ConverterState>;
  /** Restored primary asset as a File object. */
  assetFile: File;
  /** Restored heightmap as a File object (if present). */
  heightmapFile: File | null;
  /** Warnings to display to the user. */
  warnings: string[];
  /** The full parsed recipe (for display in confirm dialog). */
  recipe: LuminaRecipe;
}

/**
 * Restore converter state from a parsed LuminaRecipe.
 * 从解析的 LuminaRecipe 恢复 converter 状态。
 *
 * @param recipe - The parsed and migrated LuminaRecipe.
 * @param localLuts - Available LUT list from the store.
 * @param localFingerprints - LUT name → fingerprint map.
 * @returns RestoreResult with partial state, files, and warnings.
 */
export function restoreConverterRecipe(
  recipe: LuminaRecipe,
  localLuts: LutInfo[],
  localFingerprints: Record<string, string>,
): RestoreResult {
  if (!recipe.recipe.converter) {
    throw new Error("Recipe does not contain converter data");
  }

  const conv = recipe.recipe.converter;
  const warnings: string[] = [...recipe.warnings];

  // --- Restore primary asset ---
  const primaryAsset = recipe.asset.primary;
  const assetFile = base64ToFile(
    primaryAsset.payload_b64,
    primaryAsset.filename,
    primaryAsset.mime_type,
  );

  // --- Restore heightmap asset ---
  let heightmapFile: File | null = null;
  if (recipe.asset.heightmap) {
    const hm = recipe.asset.heightmap;
    heightmapFile = base64ToFile(hm.payload_b64, hm.filename, hm.mime_type);
  }

  // --- LUT matching ---
  const lutMatch = matchLut(conv.base.lut, localLuts, localFingerprints);
  let lutName = "";
  if (lutMatch.matched) {
    lutName = lutMatch.lutName;
    if (lutMatch.matchType === "name") {
      warnings.push(
        `LUT matched by name ("${lutName}") but fingerprint differs. Colors may not be identical.`,
      );
    }
  } else {
    warnings.push(
      `LUT "${lutMatch.originalName}" not found locally. Please select a compatible LUT manually.`,
    );
  }

  // --- Normalize hex values (strip '#' for store) ---
  const replacementRegions: ColorReplacementItem[] =
    conv.color_ops.replacement_regions.map((r) => ({
      quantized_hex: stripHash(r.quantized_hex),
      matched_hex: stripHash(r.matched_hex),
      replacement_hex: stripHash(r.replacement_hex),
    }));

  const freeColorSet = new Set(
    conv.color_ops.free_color_set.map(stripHash),
  );

  const colorHeightMap: Record<string, number> = {};
  for (const [hex, height] of Object.entries(conv.relief.color_height_map)) {
    colorHeightMap[stripHash(hex)] = height;
  }

  // --- Build partial state ---
  const state: Partial<ConverterState> = {
    // Base
    lut_name: lutName,
    color_mode: conv.base.color_mode as ConverterState["color_mode"],
    modeling_mode: conv.base.modeling_mode as ConverterState["modeling_mode"],
    target_width_mm: conv.base.target_width_mm,
    target_height_mm: conv.base.target_height_mm,
    auto_bg: conv.base.auto_bg,
    bg_tol: conv.base.bg_tol,
    quantize_colors: conv.base.quantize_colors,
    enable_cleanup: conv.base.enable_cleanup,
    hue_enable: conv.base.hue_enable,
    chroma_gate: conv.base.chroma_gate,

    // Geometry
    spacer_thick: conv.geometry.spacer_thick,
    structure_mode: conv.geometry.structure_mode as ConverterState["structure_mode"],
    separate_backing: conv.geometry.separate_backing,
    add_loop: conv.geometry.add_loop,
    loop_width: conv.geometry.loop_width,
    loop_length: conv.geometry.loop_length,
    loop_hole: conv.geometry.loop_hole,
    loop_angle: conv.geometry.loop_angle,
    loop_offset_x: conv.geometry.loop_offset_x,
    loop_offset_y: conv.geometry.loop_offset_y,
    loop_position_preset: conv.geometry.loop_position_preset,

    // Relief
    enable_relief: conv.relief.enable_relief,
    autoHeightMode: conv.relief.auto_height_mode as ConverterState["autoHeightMode"],
    color_height_map: colorHeightMap,
    heightmap_max_height: conv.relief.heightmap_max_height,

    // Outline
    enable_outline: conv.outline.enable_outline,
    outline_width: conv.outline.outline_width,

    // Cloisonne
    enable_cloisonne: conv.cloisonne.enable_cloisonne,
    wire_width_mm: conv.cloisonne.wire_width_mm,
    wire_height_mm: conv.cloisonne.wire_height_mm,

    // Coating
    enable_coating: conv.coating.enable_coating,
    coating_height_mm: conv.coating.coating_height_mm,

    // Color ops
    replacement_regions: replacementRegions,
    free_color_set: freeColorSet,
    // Clear remap state — replacement_regions already contains merged data
    colorRemapMap: {},
    remapHistory: [],

    // Large format
    largeFormatEnabled: conv.large_format.large_format_enabled,
    tileWidthMm: conv.large_format.tile_width_mm,
    tileHeightMm: conv.large_format.tile_height_mm,

    // Clear session/preview state (will be rebuilt on next preview)
    sessionId: null,
    previewImageUrl: null,
    previewGlbUrl: null,
    modelUrl: null,
    threemfDiskPath: null,
    downloadUrl: null,
    hasManualPreview: false,
    layerImages: [],
    layerImagesOpen: false,
    regionData: null,
    selectedRegions: [],
    pendingReplacement: null,
    regionReplacementCount: 0,
    error: null,
  };

  return {
    state,
    assetFile,
    heightmapFile,
    warnings,
    recipe,
  };
}
