/**
 * ColorPreview2D — 2D preview image with click-to-select color/region support.
 * ColorPreview2D — 2D 预览图组件，支持点击选色/选区域。
 *
 * Replaces the 3D raycasting approach with direct pixel coordinate picking
 * on the quantized preview image, providing more accurate and performant
 * color selection across all four selection modes.
 * 用直接像素坐标拾取替代 3D raycasting，在所有四种选择模式下提供更精准、更高性能的颜色选择。
 */

import { useRef, useCallback, useMemo, useState, useEffect } from 'react';
import { useConverterStore } from '../../stores/converter';
import { useI18n } from '../../i18n/context';

/**
 * Convert a click on an <img> with object-contain to image pixel coordinates.
 * 将 object-contain 模式下 <img> 上的点击转换为图像像素坐标。
 *
 * @param event - The mouse event on the image element.
 * @param imgEl - The <img> DOM element.
 * @param naturalW - The intrinsic image width in pixels.
 * @param naturalH - The intrinsic image height in pixels.
 * @returns [pixelX, pixelY] in image space, or null if click is in letterbox padding.
 */
export function imgClickToPixel(
  event: React.MouseEvent<HTMLImageElement>,
  imgEl: HTMLImageElement,
  naturalW: number,
  naturalH: number,
): [number, number] | null {
  const rect = imgEl.getBoundingClientRect();
  const clientW = rect.width;
  const clientH = rect.height;

  if (naturalW <= 0 || naturalH <= 0 || clientW <= 0 || clientH <= 0) {
    return null;
  }

  // Compute the rendered image rect within the element (object-contain)
  const scale = Math.min(clientW / naturalW, clientH / naturalH);
  const renderedW = naturalW * scale;
  const renderedH = naturalH * scale;
  const offsetX = (clientW - renderedW) / 2;
  const offsetY = (clientH - renderedH) / 2;

  const relX = event.clientX - rect.left - offsetX;
  const relY = event.clientY - rect.top - offsetY;

  // Click in letterbox padding
  if (relX < 0 || relX >= renderedW || relY < 0 || relY >= renderedH) {
    return null;
  }

  const pixelX = Math.floor((relX / renderedW) * naturalW);
  const pixelY = Math.floor((relY / renderedH) * naturalH);

  return [
    Math.max(0, Math.min(naturalW - 1, pixelX)),
    Math.max(0, Math.min(naturalH - 1, pixelY)),
  ];
}

/**
 * Read the color of a pixel from an image via an off-screen canvas.
 * 通过离屏 canvas 读取图像某像素的颜色。
 *
 * @param imgEl - A loaded <img> element.
 * @param x - Pixel X coordinate.
 * @param y - Pixel Y coordinate.
 * @returns Hex string without '#' (e.g. "ff0000"), or null on failure.
 */
export function readPixelColor(
  imgEl: HTMLImageElement,
  x: number,
  y: number,
): string | null {
  try {
    const canvas = document.createElement('canvas');
    canvas.width = imgEl.naturalWidth;
    canvas.height = imgEl.naturalHeight;
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    if (!ctx) return null;
    ctx.drawImage(imgEl, 0, 0);
    const [r, g, b] = ctx.getImageData(x, y, 1, 1).data;
    return [r, g, b].map((c) => c.toString(16).padStart(2, '0')).join('');
  } catch {
    return null;
  }
}

/**
 * Find the closest palette entry to a given hex color.
 * 查找与给定 hex 最接近的调色板条目。
 */
function findClosestPaletteHex(
  hex: string,
  palette: Array<{ matched_hex: string }>,
): string | null {
  if (palette.length === 0) return null;

  const hexLower = hex.toLowerCase();
  // Exact match first
  const exact = palette.find((p) => p.matched_hex.toLowerCase() === hexLower);
  if (exact) return exact.matched_hex;

  // Color distance match
  const tr = parseInt(hex.slice(0, 2), 16);
  const tg = parseInt(hex.slice(2, 4), 16);
  const tb = parseInt(hex.slice(4, 6), 16);

  let bestDist = Infinity;
  let bestHex: string | null = null;

  for (const entry of palette) {
    const h = entry.matched_hex.replace(/^#/, '');
    const er = parseInt(h.slice(0, 2), 16);
    const eg = parseInt(h.slice(2, 4), 16);
    const eb = parseInt(h.slice(4, 6), 16);
    const dist = (tr - er) ** 2 + (tg - eg) ** 2 + (tb - eb) ** 2;
    if (dist < bestDist) {
      bestDist = dist;
      bestHex = entry.matched_hex;
    }
  }

  return bestHex;
}

// --------------- Zoom / Pan constants ---------------
const MIN_ZOOM = 0.5;
const MAX_ZOOM = 10;
const ZOOM_STEP = 1.15;

export default function ColorPreview2D() {
  const { t } = useI18n();
  const containerRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);

  // Use previewBaseImageUrl for a stable image that only changes on actual
  // content updates (initial preview, color replacement, undo), not on
  // region detection, color highlighting, or selection mode switching.
  const previewBaseImageUrl = useConverterStore((s) => s.previewBaseImageUrl);
  const previewImageUrl = useConverterStore((s) => s.previewImageUrl);
  const stableImageUrl = previewBaseImageUrl ?? previewImageUrl;

  // Preload mechanism: keep current displayUrl until new image is fully loaded,
  // preventing visible flash when stableImageUrl changes after replacement.
  const [displayUrl, setDisplayUrl] = useState<string | null>(stableImageUrl);
  useEffect(() => {
    if (!stableImageUrl) {
      setDisplayUrl(null);
      return;
    }
    if (stableImageUrl === displayUrl) return;
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => setDisplayUrl(stableImageUrl);
    img.onerror = () => setDisplayUrl(stableImageUrl);
    img.src = stableImageUrl;
  }, [stableImageUrl]); // eslint-disable-line react-hooks/exhaustive-deps

  const previewPixelWidth = useConverterStore((s) => s.previewPixelWidth);
  const previewPixelHeight = useConverterStore((s) => s.previewPixelHeight);
  const selectionMode = useConverterStore((s) => s.selectionMode);
  const selectedColor = useConverterStore((s) => s.selectedColor);
  const selectedColors = useConverterStore((s) => s.selectedColors);
  const palette = useConverterStore((s) => s.palette);
  const isLoading = useConverterStore((s) => s.isLoading);
  const replacePreviewLoading = useConverterStore((s) => s.replacePreviewLoading);
  const colorContours = useConverterStore((s) => s.colorContours);
  const regionData = useConverterStore((s) => s.regionData);
  const selectedRegions = useConverterStore((s) => s.selectedRegions);

  const setSelectedColor = useConverterStore((s) => s.setSelectedColor);
  const toggleColorInSelection = useConverterStore((s) => s.toggleColorInSelection);
  const detectRegion = useConverterStore((s) => s.detectRegion);
  const detectAndAccumulateRegion = useConverterStore((s) => s.detectAndAccumulateRegion);

  // --------------- Zoom / Pan state ---------------
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const isPanningRef = useRef(false);
  const panStartRef = useRef({ x: 0, y: 0, panX: 0, panY: 0 });
  const didDragRef = useRef(false);

  // Track container dimensions for explicit image fitting.
  // Re-run when displayUrl changes so the observer attaches after the
  // placeholder is replaced by the main view (containerRef becomes valid).
  const [cSize, setCSize] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect;
      setCSize({ w: width, h: height });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [displayUrl]);

  // Track image natural dimensions
  const [natSize, setNatSize] = useState({ w: 0, h: 0 });
  const handleImgLoad = useCallback(() => {
    const img = imgRef.current;
    if (img) setNatSize({ w: img.naturalWidth, h: img.naturalHeight });
  }, []);

  // Compute fitted image dimensions (image scaled to fit container)
  const fitScale =
    natSize.w > 0 && natSize.h > 0 && cSize.w > 0 && cSize.h > 0
      ? Math.min(cSize.w / natSize.w, cSize.h / natSize.h)
      : 0;
  const fittedW = natSize.w * fitScale;
  const fittedH = natSize.h * fitScale;

  // Reset zoom/pan when the image source changes
  useEffect(() => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }, [stableImageUrl]);

  // Mouse wheel → zoom, centred on cursor
  const handleWheel = useCallback(
    (e: React.WheelEvent<HTMLDivElement>) => {
      e.preventDefault();
      const container = containerRef.current;
      if (!container) return;

      const rect = container.getBoundingClientRect();
      const cursorX = e.clientX - rect.left;
      const cursorY = e.clientY - rect.top;

      setZoom((prevZoom) => {
        const factor = e.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP;
        const newZoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, prevZoom * factor));
        const scale = newZoom / prevZoom;
        // Adjust pan so the point under the cursor stays fixed
        setPan((prev) => ({
          x: cursorX - scale * (cursorX - prev.x),
          y: cursorY - scale * (cursorY - prev.y),
        }));
        return newZoom;
      });
    },
    [],
  );

  // Pan via drag
  const handlePointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      // Only pan with middle button or when zoom is at exactly 1× (no zoom)
      if (e.button !== 1 && zoom === 1) return;
      if (e.button === 2) return; // ignore right-click
      isPanningRef.current = true;
      didDragRef.current = false;
      panStartRef.current = { x: e.clientX, y: e.clientY, panX: pan.x, panY: pan.y };
      (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
    },
    [zoom, pan],
  );

  const handlePointerMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!isPanningRef.current) return;
      const dx = e.clientX - panStartRef.current.x;
      const dy = e.clientY - panStartRef.current.y;
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) didDragRef.current = true;
      setPan({ x: panStartRef.current.panX + dx, y: panStartRef.current.panY + dy });
    },
    [],
  );

  const handlePointerUp = useCallback(() => {
    isPanningRef.current = false;
  }, []);

  // Double-click to reset zoom/pan
  const handleDoubleClick = useCallback(() => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }, []);

  /**
   * Map a mouse event on the container to raw image pixel coordinates,
   * accounting for current zoom/pan transform and fit-to-container scaling.
   */
  const containerClickToPixel = useCallback(
    (e: React.MouseEvent<HTMLDivElement>): [number, number] | null => {
      const container = containerRef.current;
      if (!container || !natSize.w || !natSize.h || !fittedW || !fittedH) return null;

      const cRect = container.getBoundingClientRect();
      const cW = cRect.width;
      const cH = cRect.height;
      if (cW <= 0 || cH <= 0) return null;

      // Centred offset of the fitted image within the container
      const baseOffX = (cW - fittedW) / 2;
      const baseOffY = (cH - fittedH) / 2;

      // Invert CSS transform: translate(pan) scale(zoom) with origin 0 0
      const relX = e.clientX - cRect.left;
      const relY = e.clientY - cRect.top;
      const ix = (relX - pan.x) / zoom - baseOffX;
      const iy = (relY - pan.y) / zoom - baseOffY;
      const px = Math.floor((ix / fittedW) * natSize.w);
      const py = Math.floor((iy / fittedH) * natSize.h);

      if (px < 0 || px >= natSize.w || py < 0 || py >= natSize.h) return null;
      return [px, py];
    },
    [zoom, pan, natSize, fittedW, fittedH],
  );

  const handleClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (replacePreviewLoading) return;
      if (didDragRef.current) return; // ignore click after drag
      if (!previewPixelWidth || !previewPixelHeight) return;

      const imgEl = imgRef.current;
      if (!imgEl) return;

      const pixel = containerClickToPixel(e);
      if (!pixel) return;
      const [px, py] = pixel;

      switch (selectionMode) {
        case 'select-all': {
          const rawHex = readPixelColor(imgEl, px, py);
          if (!rawHex) return;
          const paletteHex = findClosestPaletteHex(rawHex, palette);
          if (!paletteHex) return;
          toggleColorInSelection(paletteHex);
          if (selectedColors.has(paletteHex)) {
            const remaining = Array.from(selectedColors).filter((c) => c !== paletteHex);
            setSelectedColor(remaining.length > 0 ? remaining[remaining.length - 1] : null);
          } else {
            setSelectedColor(paletteHex);
          }
          break;
        }
        case 'current':
        case 'region':
          detectRegion(px, py);
          break;
        case 'multi-select':
          detectAndAccumulateRegion(px, py);
          break;
      }
    },
    [
      replacePreviewLoading,
      previewPixelWidth,
      previewPixelHeight,
      selectionMode,
      palette,
      selectedColors,
      containerClickToPixel,
      toggleColorInSelection,
      setSelectedColor,
      detectRegion,
      detectAndAccumulateRegion,
    ],
  );

  // Collect contour polygons to render as SVG overlays
  const svgContours = useMemo(() => {
    if (!previewPixelWidth || !previewPixelHeight) return [];

    const targets: Array<{ hex: string; polygons: number[][][] }> = [];

    if (
      (selectionMode === 'current' || selectionMode === 'region') &&
      selectedColor &&
      regionData?.contours &&
      regionData.contours.length > 0
    ) {
      targets.push({ hex: selectedColor, polygons: regionData.contours });
    } else if (selectionMode === 'multi-select' && selectedRegions.length > 0) {
      for (const region of selectedRegions) {
        if (region.contours && region.contours.length > 0) {
          const hex = region.colorHex.replace(/^#/, '');
          targets.push({ hex, polygons: region.contours });
        }
      }
    } else if (selectionMode === 'select-all' && selectedColors.size > 0) {
      for (const hex of selectedColors) {
        if (colorContours[hex]) {
          targets.push({ hex, polygons: colorContours[hex] });
        }
      }
    } else if (selectedColor && colorContours[selectedColor]) {
      targets.push({ hex: selectedColor, polygons: colorContours[selectedColor] });
    }

    return targets;
  }, [
    selectionMode,
    selectedColor,
    selectedColors,
    selectedRegions,
    regionData,
    colorContours,
    previewPixelWidth,
    previewPixelHeight,
  ]);


  if (!displayUrl) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-sm text-slate-500 dark:text-slate-400">
        {isLoading ? (
          <>
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-slate-300 border-t-slate-600 dark:border-slate-600 dark:border-t-slate-300" />
            <span>{t('color_2d_generating_preview')}</span>
          </>
        ) : (
          t('color_2d_no_preview')
        )}
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="relative h-full w-full overflow-hidden bg-slate-200/60 dark:bg-slate-900/60"
      style={{ cursor: zoom > 1 ? 'grab' : 'crosshair' }}
      onWheel={handleWheel}
      onClick={handleClick}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onDoubleClick={handleDoubleClick}
    >
      {replacePreviewLoading && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-slate-950/40">
          <p className="text-xs text-slate-100">{t('lut_grid_loading')}</p>
        </div>
      )}

      <div
        className="pointer-events-none absolute inset-0 z-20 border-2"
        style={{ borderColor: 'var(--info-border)' }}
        aria-hidden="true"
      >
        <div
          className="absolute right-2 top-2 rounded-full border px-2 py-1 text-[10px] font-semibold"
          style={{
            borderColor: 'var(--info-border)',
            background: 'var(--info-soft)',
            color: 'var(--surface-text-muted)',
          }}
        >
          {t('preview_debug_main_2d')}
        </div>
      </div>

      {/* Zoom indicator */}
      {zoom !== 1 && (
        <div className="absolute left-2 top-2 z-20 rounded-full bg-slate-900/60 px-2 py-0.5 text-[10px] text-slate-100 backdrop-blur-sm">
          {Math.round(zoom * 100)}%
        </div>
      )}

      {/* Inner wrapper — positioned by zoom/pan transform */}
      <div
        className="absolute inset-0 flex items-center justify-center"
        style={{
          transformOrigin: '0 0',
          transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
          pointerEvents: 'none',
        }}
      >
        {/* Image + SVG wrapper — explicitly sized to fitted image dimensions
            so SVG overlay shares the exact same bounding box as the image */}
        {fittedW > 0 && fittedH > 0 && (
          <div className="relative" style={{ width: fittedW, height: fittedH }}>
            <img
              ref={imgRef}
              src={displayUrl ?? undefined}
              alt="2D color preview"
              crossOrigin="anonymous"
              onLoad={handleImgLoad}
              className="block h-full w-full"
              style={replacePreviewLoading ? { opacity: 0.6 } : undefined}
              draggable={false}
            />

            {/* SVG contour overlays — raw pixel coordinate space */}
            {svgContours.length > 0 && previewPixelWidth && previewPixelHeight && (
              <svg
                viewBox={`0 0 ${previewPixelWidth} ${previewPixelHeight}`}
                className="pointer-events-none absolute inset-0 h-full w-full"
                style={{ zIndex: 5 }}
              >
                {svgContours.map(({ hex, polygons }, ti) =>
                  polygons.map((polygon, pi) => {
                    if (polygon.length < 3) return null;
                    const previewWidthMm = useConverterStore.getState().preview_width_mm;
                    if (!previewWidthMm || previewWidthMm <= 0) return null;
                    const pixelScale = previewWidthMm / previewPixelWidth;

                    const points = polygon
                      .map(([xMm, yMm]) => {
                        const px = xMm / pixelScale;
                        const py = previewPixelHeight - yMm / pixelScale;
                        return `${px},${py}`;
                      })
                      .join(' ');

                    return (
                      <polygon
                        key={`${hex}-${ti}-${pi}`}
                        points={points}
                        fill="none"
                        stroke="#00ffff"
                        strokeWidth={Math.max(1, previewPixelWidth / 500)}
                        strokeLinejoin="round"
                        opacity={0.85}
                      />
                    );
                  }),
                )}
              </svg>
            )}
          </div>
        )}

        {/* Fallback: show image while computing fit dimensions */}
        {(fittedW <= 0 || fittedH <= 0) && (
          <img
            ref={imgRef}
            src={displayUrl ?? undefined}
            alt="2D color preview"
            crossOrigin="anonymous"
            onLoad={handleImgLoad}
            className="max-h-full max-w-full"
            draggable={false}
          />
        )}
      </div>
    </div>
  );
}
