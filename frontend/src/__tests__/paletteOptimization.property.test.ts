import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest';
import * as fc from 'fast-check';
import {
  rgbEuclideanDistance,
  sortByColorDistance,
} from '../utils/colorUtils';
import type { LutColorEntry } from '../api/types';
const { mockApiFetchLutColors } = vi.hoisted(() => ({
  mockApiFetchLutColors: vi.fn(),
}));

vi.mock('../api/converter', async () => {
  const original = await vi.importActual<typeof import('../api/converter')>('../api/converter');
  return {
    ...original,
    fetchLutColors: (...args: unknown[]) => mockApiFetchLutColors(...args),
    replaceColor: vi.fn().mockResolvedValue({ preview_url: '/api/files/mock-preview' }),
  };
});

// ========== Generators ==========

/** Arbitrary RGB tuple with integer values 0-255. (0-255 鏁存暟鐨?RGB 鍏冪粍鐢熸垚鍣? */
const arbRgb = fc.tuple(
  fc.integer({ min: 0, max: 255 }),
  fc.integer({ min: 0, max: 255 }),
  fc.integer({ min: 0, max: 255 }),
) as fc.Arbitrary<[number, number, number]>;

/** Arbitrary LutColorEntry from a random RGB. (浠庨殢鏈?RGB 鐢熸垚 LutColorEntry) */
const arbLutColorEntry: fc.Arbitrary<LutColorEntry> = arbRgb.map((rgb) => {
  const hex =
    '#' +
    rgb
      .map((c) => c.toString(16).padStart(2, '0'))
      .join('');
  return { hex, rgb };
});

/** Non-empty array of LutColorEntry. (闈炵┖ LutColorEntry 鏁扮粍) */
const arbLutColorEntries = fc.array(arbLutColorEntry, { minLength: 1, maxLength: 50 });

// ========== Property 5: 棰滆壊璺濈鎺掑簭鍗曡皟鎬?==========

// **Validates: Requirements 3.1**
describe('Feature: palette-optimization, Property 5: distance sort monotonicity', () => {
  it('sortByColorDistance returns results with monotonically non-decreasing distances', () => {
    fc.assert(
      fc.property(arbRgb, arbLutColorEntries, (baseRgb, colors) => {
        const topK = colors.length; // use full list to verify complete ordering
        const sorted = sortByColorDistance(baseRgb, colors, topK);

        for (let i = 0; i < sorted.length - 1; i++) {
          const distCurrent = rgbEuclideanDistance(baseRgb, sorted[i].rgb);
          const distNext = rgbEuclideanDistance(baseRgb, sorted[i + 1].rgb);
          expect(distCurrent).toBeLessThanOrEqual(distNext);
        }
      }),
      { numRuns: 100 },
    );
  });

  it('sortByColorDistance with topK < colors.length still maintains monotonicity', () => {
    fc.assert(
      fc.property(
        arbRgb,
        arbLutColorEntries.filter((c) => c.length >= 2),
        (baseRgb, colors) => {
          const topK = Math.max(1, Math.floor(colors.length / 2));
          const sorted = sortByColorDistance(baseRgb, colors, topK);

          expect(sorted.length).toBeLessThanOrEqual(topK);

          for (let i = 0; i < sorted.length - 1; i++) {
            const distCurrent = rgbEuclideanDistance(baseRgb, sorted[i].rgb);
            const distNext = rgbEuclideanDistance(baseRgb, sorted[i + 1].rgb);
            expect(distCurrent).toBeLessThanOrEqual(distNext);
          }
        },
      ),
      { numRuns: 100 },
    );
  });
});

// ========== Property 1: LUT 棰滆壊缂撳瓨鍛戒腑璺宠繃璇锋眰 ==========

// **Validates: Requirements 1.3, 5.2, 5.3**
describe('Feature: palette-optimization, Property 1: LUT 棰滆壊缂撳瓨鍛戒腑璺宠繃璇锋眰', () => {

  // Lazy-import the store AFTER mock is set up
  let useConverterStore: typeof import('../stores/converter').useConverterStore;

  beforeAll(async () => {
    const mod = await import('../stores/converter');
    useConverterStore = mod.useConverterStore;
  });

  beforeEach(() => {
    mockApiFetchLutColors.mockClear();
  });

  /** Alphanumeric LUT name generator (1-20 chars). (瀛楁瘝鏁板瓧 LUT 鍚嶇О鐢熸垚鍣? */
  const arbLutName = fc.string({ minLength: 1, maxLength: 20 })
    .filter((s) => /^[a-zA-Z0-9]+$/.test(s));

  /** Random non-empty LutColorEntry array for cached data. (闅忔満闈炵┖ LutColorEntry 鏁扮粍) */
  const arbCachedColors = fc.array(
    arbLutColorEntry,
    { minLength: 1, maxLength: 30 },
  );

  it('fetchLutColors skips API call when cache matches lutName and lutColors is non-empty', async () => {
    await fc.assert(
      fc.asyncProperty(arbLutName, arbCachedColors, async (lutName, cachedColors) => {
        // Set up store state to simulate a cache hit
        useConverterStore.setState({
          lutColorsLutName: lutName,
          lutColors: cachedColors,
          lutColorsLoading: false,
        });

        mockApiFetchLutColors.mockClear();

        // Call fetchLutColors with the same lutName
        await useConverterStore.getState().fetchLutColors(lutName);

        // API should NOT have been called (cache hit)
        expect(mockApiFetchLutColors).not.toHaveBeenCalled();

        // lutColors data should remain unchanged
        const state = useConverterStore.getState();
        expect(state.lutColors).toEqual(cachedColors);
        expect(state.lutColorsLutName).toBe(lutName);
      }),
      { numRuns: 100 },
    );
  });
});

// ========== Generators for Property 2/3/4 ==========

/** Arbitrary 6-char hex string (no # prefix). (鏃?# 鍓嶇紑鐨?6 浣?hex 瀛楃涓茬敓鎴愬櫒) */
const hexChar = fc.constantFrom(...'0123456789abcdef'.split(''));
const arbHex6 = fc
  .tuple(hexChar, hexChar, hexChar, hexChar, hexChar, hexChar)
  .map((chars) => chars.join(''));

/** Arbitrary pair of distinct hex colors. (涓嶅悓 hex 棰滆壊瀵圭敓鎴愬櫒) */
const arbHexPair = fc
  .tuple(arbHex6, arbHex6)
  .filter(([a, b]) => a !== b);

// ========== Property 2: applyColorRemap 姝ｇ‘璁板綍鏄犲皠 ==========

// **Validates: Requirements 2.2**
describe('Feature: palette-optimization, Property 2: applyColorRemap 姝ｇ‘璁板綍鏄犲皠', () => {
  let useConverterStore: typeof import('../stores/converter').useConverterStore;

  beforeAll(async () => {
    const mod = await import('../stores/converter');
    useConverterStore = mod.useConverterStore;
  });

  beforeEach(() => {
    // Reset remap-related state before each test
    useConverterStore.setState({
      colorRemapMap: {},
      remapHistory: [],
      sessionId: null,
    });
  });

  it('applyColorRemap records mapping in colorRemapMap and pushes snapshot to remapHistory', () => {
    fc.assert(
      fc.property(arbHexPair, ([origHex, newHex]) => {
        // Reset state
        useConverterStore.setState({
          colorRemapMap: {},
          remapHistory: [],
          sessionId: null,
        });

        const historyLenBefore = useConverterStore.getState().remapHistory.length;

        useConverterStore.getState().applyColorRemap(origHex, newHex);

        const state = useConverterStore.getState();
        // colorRemapMap should contain the mapping
        expect(state.colorRemapMap[origHex]).toBe(newHex);
        // remapHistory length should increase by 1
        expect(state.remapHistory.length).toBe(historyLenBefore + 1);
      }),
      { numRuns: 100 },
    );
  });

  it('applyColorRemap accumulates multiple mappings correctly', () => {
    fc.assert(
      fc.property(
        fc.array(arbHexPair, { minLength: 1, maxLength: 10 }),
        (pairs) => {
          // Reset state
          useConverterStore.setState({
            colorRemapMap: {},
            remapHistory: [],
            sessionId: null,
          });

          for (let i = 0; i < pairs.length; i++) {
            const [origHex, newHex] = pairs[i];
            useConverterStore.getState().applyColorRemap(origHex, newHex);

            const state = useConverterStore.getState();
            // Each call should increase history by 1
            expect(state.remapHistory.length).toBe(i + 1);
            // Latest mapping should be recorded
            expect(state.colorRemapMap[origHex]).toBe(newHex);
          }
        },
      ),
      { numRuns: 100 },
    );
  });
});

// ========== Property 3: 鎾ら攢鎭㈠涓婁竴鐘舵€侊紙Round-Trip锛?==========

// **Validates: Requirements 2.5**
describe('Feature: palette-optimization, Property 3: undo round trip', () => {
  let useConverterStore: typeof import('../stores/converter').useConverterStore;

  beforeAll(async () => {
    const mod = await import('../stores/converter');
    useConverterStore = mod.useConverterStore;
  });

  beforeEach(() => {
    useConverterStore.setState({
      colorRemapMap: {},
      remapHistory: [],
      sessionId: null,
      originalPreviewUrl: '/api/files/original',
      previewImageUrl: '/api/files/original',
    });
  });

  it('undoColorRemap restores previous state and reduces history length by 1', () => {
    fc.assert(
      fc.property(
        fc.array(arbHexPair, { minLength: 1, maxLength: 8 }),
        (pairs) => {
          // Reset state
          useConverterStore.setState({
            colorRemapMap: {},
            remapHistory: [],
            sessionId: null,
            originalPreviewUrl: '/api/files/original',
            previewImageUrl: '/api/files/original',
          });

          // Apply all remaps
          for (const [origHex, newHex] of pairs) {
            useConverterStore.getState().applyColorRemap(origHex, newHex);
          }

          // Undo one by one and verify
          for (let i = pairs.length; i > 0; i--) {
            const stateBefore = useConverterStore.getState();
            const expectedMap =
              stateBefore.remapHistory.length > 0
                ? stateBefore.remapHistory[stateBefore.remapHistory.length - 1]
                : {};
            const expectedHistoryLen = stateBefore.remapHistory.length - 1;

            useConverterStore.getState().undoColorRemap();

            const stateAfter = useConverterStore.getState();
            expect(stateAfter.colorRemapMap).toEqual(expectedMap);
            expect(stateAfter.remapHistory.length).toBe(expectedHistoryLen);
          }

          // After all undos, map should be empty
          const finalState = useConverterStore.getState();
          expect(finalState.colorRemapMap).toEqual({});
          expect(finalState.remapHistory.length).toBe(0);
        },
      ),
      { numRuns: 100 },
    );
  });

  it('undoColorRemap is a no-op when history is empty', () => {
    fc.assert(
      fc.property(fc.constant(null), () => {
        useConverterStore.setState({
          colorRemapMap: {},
          remapHistory: [],
          sessionId: null,
        });

        useConverterStore.getState().undoColorRemap();

        const state = useConverterStore.getState();
        expect(state.colorRemapMap).toEqual({});
        expect(state.remapHistory.length).toBe(0);
      }),
      { numRuns: 100 },
    );
  });
});

// ========== Property 4: 娓呯┖鏇挎崲褰掗浂 ==========

// **Validates: Requirements 2.6**
describe('Feature: palette-optimization, Property 4: 娓呯┖鏇挎崲褰掗浂', () => {
  let useConverterStore: typeof import('../stores/converter').useConverterStore;

  beforeAll(async () => {
    const mod = await import('../stores/converter');
    useConverterStore = mod.useConverterStore;
  });

  beforeEach(() => {
    useConverterStore.setState({
      colorRemapMap: {},
      remapHistory: [],
      sessionId: null,
      originalPreviewUrl: '/api/files/original',
      previewImageUrl: '/api/files/original',
    });
  });

  it('clearAllRemaps resets colorRemapMap to {} and remapHistory to []', () => {
    fc.assert(
      fc.property(
        fc.array(arbHexPair, { minLength: 0, maxLength: 10 }),
        (pairs) => {
          // Reset and apply random remaps
          useConverterStore.setState({
            colorRemapMap: {},
            remapHistory: [],
            sessionId: null,
            originalPreviewUrl: '/api/files/original',
            previewImageUrl: '/api/files/original',
          });

          for (const [origHex, newHex] of pairs) {
            useConverterStore.getState().applyColorRemap(origHex, newHex);
          }

          // Clear all
          useConverterStore.getState().clearAllRemaps();

          const state = useConverterStore.getState();
          expect(state.colorRemapMap).toEqual({});
          expect(state.remapHistory).toEqual([]);
        },
      ),
      { numRuns: 100 },
    );
  });

  it('clearAllRemaps is idempotent 鈥?calling twice yields same empty state', () => {
    fc.assert(
      fc.property(
        fc.array(arbHexPair, { minLength: 1, maxLength: 5 }),
        (pairs) => {
          useConverterStore.setState({
            colorRemapMap: {},
            remapHistory: [],
            sessionId: null,
            originalPreviewUrl: '/api/files/original',
            previewImageUrl: '/api/files/original',
          });

          for (const [origHex, newHex] of pairs) {
            useConverterStore.getState().applyColorRemap(origHex, newHex);
          }

          useConverterStore.getState().clearAllRemaps();
          useConverterStore.getState().clearAllRemaps();

          const state = useConverterStore.getState();
          expect(state.colorRemapMap).toEqual({});
          expect(state.remapHistory).toEqual([]);
        },
      ),
      { numRuns: 100 },
    );
  });
});

