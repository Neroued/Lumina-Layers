import { useMemo, useState, useRef, useEffect, useCallback, type ReactNode } from "react"
import { createPortal } from "react-dom"
import { useConverterStore } from "../../stores/converter"
import Button from "../ui/Button"
import BatchResultSummary from "../ui/BatchResultSummary"
import ZoomableImage, { type ZoomableImageHoverSample } from "../ui/ZoomableImage"
import BedSizeSelector from "./BedSizeSelector"
import SlicerSelector from "./SlicerSelector"
import WikiTooltip from "../ui/WikiTooltip"
import { resolvePreviewHoverPixel } from "./actionBarHoverUtils"
import { useI18n } from "../../i18n/context"
import { useWorkspaceMode } from "../../hooks/useWorkspaceMode"
import { exportShareCard, exportSidecar } from "../../recipe/importFlow"

interface LayerHoverColorSample {
  displayIndex: number
  layerName: string
  colorHex: string | null
}

interface LayerCanvasBuffer {
  layerIndex: number
  name: string
  width: number
  height: number
  context: CanvasRenderingContext2D
}

interface PreviewCanvasBuffer {
  width: number
  height: number
  context: CanvasRenderingContext2D
}

function buildPreviewCanvasBuffer(image: HTMLImageElement): PreviewCanvasBuffer | null {
  const width = image.naturalWidth || image.width
  const height = image.naturalHeight || image.height
  if (width <= 0 || height <= 0) {
    return null
  }

  const canvas = document.createElement("canvas")
  canvas.width = width
  canvas.height = height
  const context = canvas.getContext("2d", { willReadFrequently: true })
  if (!context) {
    return null
  }

  context.drawImage(image, 0, 0)
  return { width, height, context }
}

const HOVER_POPOVER_DELAY_MS = 180
const MAGNIFIER_SIZE_PX = 152
const MAGNIFIER_ZOOM = 3
const MAGNIFIER_OFFSET_PX = 18
const INSPECTOR_WIDTH_PX = 248
const INSPECTOR_HEIGHT_PX = 310
const INSPECTOR_EDGE_MARGIN_PX = 8

function clampNumber(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max)
}

function mapPixelToBufferCoordinate(pixel: number, sourceSize: number, bufferSize: number): number {
  return clampNumber(
    Math.round((pixel / Math.max(sourceSize - 1, 1)) * (bufferSize - 1)),
    0,
    Math.max(bufferSize - 1, 0),
  )
}

function computeHoverInspectorStyle(sample: ZoomableImageHoverSample): { left: string; top: string } | null {
  if (typeof window === "undefined") {
    return null
  }

  const viewportWidth = window.innerWidth
  const viewportHeight = window.innerHeight
  if (viewportWidth <= 0 || viewportHeight <= 0) {
    return null
  }

  const containerLeft = sample.containerLeft
  const containerTop = sample.containerTop
  const containerRight = containerLeft + sample.containerWidth
  const containerBottom = containerTop + sample.containerHeight
  const pointerX = containerLeft + sample.containerX
  const pointerY = containerTop + sample.containerY

  const requiredHorizontal = INSPECTOR_WIDTH_PX + MAGNIFIER_OFFSET_PX
  const requiredVertical = INSPECTOR_HEIGHT_PX + MAGNIFIER_OFFSET_PX

  const spaceRight = viewportWidth - containerRight - INSPECTOR_EDGE_MARGIN_PX
  const spaceLeft = containerLeft - INSPECTOR_EDGE_MARGIN_PX
  const spaceBelow = viewportHeight - containerBottom - INSPECTOR_EDGE_MARGIN_PX
  const spaceAbove = containerTop - INSPECTOR_EDGE_MARGIN_PX

  const canPlaceRight = spaceRight >= requiredHorizontal
  const canPlaceLeft = spaceLeft >= requiredHorizontal
  const canPlaceBelow = spaceBelow >= requiredVertical
  const canPlaceAbove = spaceAbove >= requiredVertical

  let left = pointerX - INSPECTOR_WIDTH_PX / 2
  let top = pointerY - INSPECTOR_HEIGHT_PX / 2

  if (canPlaceRight || canPlaceLeft) {
    left = canPlaceRight && (!canPlaceLeft || spaceRight >= spaceLeft)
      ? containerRight + MAGNIFIER_OFFSET_PX
      : containerLeft - INSPECTOR_WIDTH_PX - MAGNIFIER_OFFSET_PX
  } else if (canPlaceBelow || canPlaceAbove) {
    top = canPlaceBelow && (!canPlaceAbove || spaceBelow >= spaceAbove)
      ? containerBottom + MAGNIFIER_OFFSET_PX
      : containerTop - INSPECTOR_HEIGHT_PX - MAGNIFIER_OFFSET_PX
  } else {
    const horizontalShortfall = Math.max(0, requiredHorizontal - Math.max(spaceRight, spaceLeft))
    const verticalShortfall = Math.max(0, requiredVertical - Math.max(spaceBelow, spaceAbove))
    if (horizontalShortfall <= verticalShortfall) {
      left = spaceRight >= spaceLeft
        ? containerRight + MAGNIFIER_OFFSET_PX
        : containerLeft - INSPECTOR_WIDTH_PX - MAGNIFIER_OFFSET_PX
    } else {
      top = spaceBelow >= spaceAbove
        ? containerBottom + MAGNIFIER_OFFSET_PX
        : containerTop - INSPECTOR_HEIGHT_PX - MAGNIFIER_OFFSET_PX
    }
  }

  const maxLeft = Math.max(INSPECTOR_EDGE_MARGIN_PX, viewportWidth - INSPECTOR_WIDTH_PX - INSPECTOR_EDGE_MARGIN_PX)
  const maxTop = Math.max(INSPECTOR_EDGE_MARGIN_PX, viewportHeight - INSPECTOR_HEIGHT_PX - INSPECTOR_EDGE_MARGIN_PX)

  return {
    left: `${clampNumber(left, INSPECTOR_EDGE_MARGIN_PX, maxLeft)}px`,
    top: `${clampNumber(top, INSPECTOR_EDGE_MARGIN_PX, maxTop)}px`,
  }
}

function rgbToHex(r: number, g: number, b: number): string {
  const toHex = (component: number) => component.toString(16).padStart(2, "0").toUpperCase()
  return `${toHex(r)}${toHex(g)}${toHex(b)}`
}

function areLayerSamplesEqual(left: LayerHoverColorSample[], right: LayerHoverColorSample[]): boolean {
  if (left === right) return true
  if (left.length !== right.length) return false
  for (let i = 0; i < left.length; i += 1) {
    const a = left[i]
    const b = right[i]
    if (a.displayIndex !== b.displayIndex || a.layerName !== b.layerName || a.colorHex !== b.colorHex) {
      return false
    }
  }
  return true
}

function areHoverSamplesEqual(
  left: ZoomableImageHoverSample | null,
  right: ZoomableImageHoverSample | null,
): boolean {
  if (left === right) return true
  if (!left || !right) return false
  return (
    left.containerX === right.containerX
    && left.containerY === right.containerY
    && left.containerWidth === right.containerWidth
    && left.containerHeight === right.containerHeight
    && left.containerLeft === right.containerLeft
    && left.containerTop === right.containerTop
    && left.pixelX === right.pixelX
    && left.pixelY === right.pixelY
    && left.naturalWidth === right.naturalWidth
    && left.naturalHeight === right.naturalHeight
  )
}

export default function ActionBar() {
  const { t } = useI18n()
  const workspace = useWorkspaceMode()
  const [zoomedLayerIdx, setZoomedLayerIdx] = useState<number | null>(null)
  const [hoverSample, setHoverSample] = useState<ZoomableImageHoverSample | null>(null)
  const [hoverLayerColors, setHoverLayerColors] = useState<LayerHoverColorSample[]>([])
  const [hoverSurfaceHex, setHoverSurfaceHex] = useState<string | null>(null)
  const [previewCanvasBuffer, setPreviewCanvasBuffer] = useState<PreviewCanvasBuffer | null>(null)
  const [layerCanvasBuffers, setLayerCanvasBuffers] = useState<LayerCanvasBuffer[]>([])
  const pendingHoverSampleRef = useRef<ZoomableImageHoverSample | null>(null)
  const hoverDelayTimerRef = useRef<number | null>(null)
  const magnifierCanvasRef = useRef<HTMLCanvasElement>(null)
  const fetchedLayerSessionRef = useRef<string | null>(null)
  const layerSampleCacheRef = useRef<Map<string, LayerHoverColorSample[]>>(new Map())
  const surfaceSampleCacheRef = useRef<Map<string, string | null>>(new Map())
  const imageFile = useConverterStore((s) => s.imageFile)
  const lut_name = useConverterStore((s) => s.lut_name)
  const isLoading = useConverterStore((s) => s.isLoading)
  const isGenerating = useConverterStore((s) => s.isGenerating)
  const error = useConverterStore((s) => s.error)
  const previewImageUrl = useConverterStore((s) => s.previewImageUrl)
  const previewBaseImageUrl = useConverterStore((s) => s.previewBaseImageUrl)
  const selectionMode = useConverterStore((s) => s.selectionMode)
  const selectedRegions = useConverterStore((s) => s.selectedRegions)
  const previewWidthMm = useConverterStore((s) => s.preview_width_mm)
  const previewPixelWidth = useConverterStore((s) => s.previewPixelWidth)
  const previewPixelHeight = useConverterStore((s) => s.previewPixelHeight)
  const bedLabel = useConverterStore((s) => s.bed_label)
  const bedSizes = useConverterStore((s) => s.bedSizes)
  const submitPreview = useConverterStore((s) => s.submitPreview)
  const submitGenerate = useConverterStore((s) => s.submitGenerate)
  const submitFullPipeline = useConverterStore((s) => s.submitFullPipeline)
  const threemfDiskPath = useConverterStore((s) => s.threemfDiskPath)
  const downloadUrl = useConverterStore((s) => s.downloadUrl)
  const sessionId = useConverterStore((s) => s.sessionId)
  const largeFormatEnabled = useConverterStore((s) => s.largeFormatEnabled)

  const batchMode = useConverterStore((s) => s.batchMode)
  const batchFiles = useConverterStore((s) => s.batchFiles)
  const batchLoading = useConverterStore((s) => s.batchLoading)
  const batchResult = useConverterStore((s) => s.batchResult)
  const submitBatch = useConverterStore((s) => s.submitBatch)

  const fetchLayerImages = useConverterStore((s) => s.fetchLayerImages)
  const layerImagesLoading = useConverterStore((s) => s.layerImagesLoading)
  const layerImages = useConverterStore((s) => s.layerImages)

  const [isExporting, setIsExporting] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)

  const canSubmit = !!imageFile && !!lut_name
  const canBatchSubmit = batchFiles.length > 0 && !!lut_name
  const previewDisplayUrl = selectionMode === "multi-select"
    ? (previewImageUrl ?? previewBaseImageUrl)
    : previewImageUrl
  const hasPreview = !!previewDisplayUrl && !!sessionId
  const activeMultiSelectRegionId = selectionMode === "multi-select" && selectedRegions.length > 0
    ? selectedRegions[selectedRegions.length - 1].regionId
    : null

  const previewOverlay = useMemo(() => {
    if (
      selectionMode !== "multi-select" ||
      selectedRegions.length === 0 ||
      !previewWidthMm ||
      !previewPixelWidth ||
      !previewPixelHeight ||
      previewWidthMm <= 0 ||
      previewPixelWidth <= 0 ||
      previewPixelHeight <= 0
    ) {
      return null
    }

    const pixelScale = previewWidthMm / previewPixelWidth
    if (!(pixelScale > 0)) {
      return null
    }

    const polygons: ReactNode[] = []

    for (const region of selectedRegions) {
      if (
        region.regionId === activeMultiSelectRegionId ||
        !region.contours ||
        region.contours.length === 0
      ) {
        continue
      }

      for (let polygonIndex = 0; polygonIndex < region.contours.length; polygonIndex += 1) {
        const polygon = region.contours[polygonIndex]
        if (polygon.length < 3) {
          continue
        }

        const points = polygon
          .map(([x, y]) => `${x / pixelScale},${previewPixelHeight - y / pixelScale}`)
          .join(" ")

        polygons.push(
          <polygon
            key={`${region.regionId}-${polygonIndex}`}
            data-testid="preview-multi-select-polygon"
            points={points}
            className="fill-sky-400/25 stroke-sky-400/85"
            strokeWidth={1}
            strokeLinejoin="round"
            vectorEffect="non-scaling-stroke"
          />,
        )
      }
    }

    if (polygons.length === 0) {
      return null
    }

    return (
      <svg
        data-testid="preview-multi-select-overlay"
        viewBox={`0 0 ${previewPixelWidth} ${previewPixelHeight}`}
        className="h-full w-full"
        aria-hidden="true"
      >
        {polygons}
      </svg>
    )
  }, [activeMultiSelectRegionId, previewPixelHeight, previewPixelWidth, previewWidthMm, selectedRegions, selectionMode])

  const previewDebugOverlay = useMemo(() => (
    <div
      className="pointer-events-none absolute inset-0 border-2"
      style={{ borderColor: "var(--warning-border)" }}
      aria-hidden="true"
    >
      <div
        className="absolute left-2 top-2 rounded-full border px-2 py-1 text-[10px] font-semibold"
        style={{
          borderColor: "var(--warning-border)",
          background: "var(--warning-soft)",
          color: "var(--surface-text-muted)",
        }}
      >
        {t("preview_debug_action_2d")}
      </div>
    </div>
  ), [t])

  const handlePreviewImageReady = useCallback((image: HTMLImageElement | null) => {
    if (!image) {
      setPreviewCanvasBuffer(null)
      surfaceSampleCacheRef.current.clear()
      return
    }

    const buffer = buildPreviewCanvasBuffer(image)
    setPreviewCanvasBuffer(buffer)
    surfaceSampleCacheRef.current.clear()
  }, [])

  useEffect(() => {
    if (!sessionId) {
      fetchedLayerSessionRef.current = null
      return
    }

    if (!hasPreview || layerImagesLoading || layerImages.length > 0) {
      return
    }

    if (fetchedLayerSessionRef.current === sessionId) {
      return
    }

    fetchedLayerSessionRef.current = sessionId
    void fetchLayerImages()
  }, [hasPreview, sessionId, layerImagesLoading, layerImages.length, fetchLayerImages])

  useEffect(() => {
    if (!previewDisplayUrl) {
      setPreviewCanvasBuffer(null)
      layerSampleCacheRef.current.clear()
      surfaceSampleCacheRef.current.clear()
      setHoverSample(null)
      setHoverLayerColors([])
      setHoverSurfaceHex(null)
      return
    }

    layerSampleCacheRef.current.clear()
    surfaceSampleCacheRef.current.clear()
    setHoverSample(null)
    setHoverLayerColors([])
    setHoverSurfaceHex(null)
  }, [previewDisplayUrl])

  useEffect(() => {
    let cancelled = false

    if (layerImages.length === 0) {
      setLayerCanvasBuffers([])
      layerSampleCacheRef.current.clear()
      return () => {
        cancelled = true
      }
    }

    const buildBuffers = async () => {
      const loaded = await Promise.all(
        layerImages.map(
          (layer) =>
            new Promise<LayerCanvasBuffer | null>((resolve) => {
              const image = new Image()
              image.crossOrigin = "anonymous"
              image.onload = () => {
                const width = image.naturalWidth || image.width
                const height = image.naturalHeight || image.height
                if (width <= 0 || height <= 0) {
                  resolve(null)
                  return
                }
                const canvas = document.createElement("canvas")
                canvas.width = width
                canvas.height = height
                const context = canvas.getContext("2d", { willReadFrequently: true })
                if (!context) {
                  resolve(null)
                  return
                }
                context.drawImage(image, 0, 0)
                resolve({
                  layerIndex: layer.layer_index,
                  name: layer.name,
                  width,
                  height,
                  context,
                })
              }
              image.onerror = () => resolve(null)
              image.src = layer.url
            }),
        ),
      )

      if (cancelled) return
      setLayerCanvasBuffers(loaded.filter((entry): entry is LayerCanvasBuffer => entry !== null))
      layerSampleCacheRef.current.clear()
    }

    void buildBuffers()

    return () => {
      cancelled = true
    }
  }, [layerImages])

  useEffect(() => {
    return () => {
      if (hoverDelayTimerRef.current !== null) {
        window.clearTimeout(hoverDelayTimerRef.current)
        hoverDelayTimerRef.current = null
      }
    }
  }, [])

  useEffect(() => {
    if (!hoverSample) {
      setHoverLayerColors((previous) => (previous.length === 0 ? previous : []))
      setHoverSurfaceHex((previous) => (previous === null ? previous : null))
      return
    }

    const surfaceCacheKey = `${hoverSample.pixelX},${hoverSample.pixelY}`
    const resolvedLayerPixel = resolvePreviewHoverPixel(hoverSample, {
      rawWidth: previewPixelWidth,
      rawHeight: previewPixelHeight,
      previewWidthMm,
      bedLabel,
      bedSizes,
    })
    const layerBaseWidth = previewPixelWidth && previewPixelWidth > 0 ? previewPixelWidth : hoverSample.naturalWidth
    const layerBaseHeight = previewPixelHeight && previewPixelHeight > 0 ? previewPixelHeight : hoverSample.naturalHeight

    const previewBuffer = previewCanvasBuffer
    if (!previewBuffer) {
      setHoverSurfaceHex((previous) => (previous === null ? previous : null))
    } else {
      const cachedSurface = surfaceSampleCacheRef.current.get(surfaceCacheKey)
      if (cachedSurface !== undefined) {
        setHoverSurfaceHex((previous) => (previous === cachedSurface ? previous : cachedSurface))
      } else {
        let sampledSurface: string | null = null
        const x = mapPixelToBufferCoordinate(hoverSample.pixelX, hoverSample.naturalWidth, previewBuffer.width)
        const y = mapPixelToBufferCoordinate(hoverSample.pixelY, hoverSample.naturalHeight, previewBuffer.height)
        try {
          const rgba = previewBuffer.context.getImageData(x, y, 1, 1).data
          sampledSurface = rgba[3] <= 8 ? null : rgbToHex(rgba[0], rgba[1], rgba[2])
        } catch {
          sampledSurface = null
        }
        surfaceSampleCacheRef.current.set(surfaceCacheKey, sampledSurface)
        setHoverSurfaceHex((previous) => (previous === sampledSurface ? previous : sampledSurface))
      }
    }

    const buffers = layerCanvasBuffers
    if (!resolvedLayerPixel || buffers.length === 0) {
      setHoverLayerColors((previous) => (previous.length === 0 ? previous : []))
      return
    }

    const layerCacheKey = `${resolvedLayerPixel.pixelX},${resolvedLayerPixel.pixelY}`
    const cachedLayers = layerSampleCacheRef.current.get(layerCacheKey)
    if (cachedLayers) {
      setHoverLayerColors((previous) => (areLayerSamplesEqual(previous, cachedLayers) ? previous : cachedLayers))
      return
    }

    const sampledLayers = buffers.map((layer, index) => {
      const x = mapPixelToBufferCoordinate(resolvedLayerPixel.pixelX, layerBaseWidth, layer.width)
      const y = mapPixelToBufferCoordinate(resolvedLayerPixel.pixelY, layerBaseHeight, layer.height)

      try {
        const rgba = layer.context.getImageData(x, y, 1, 1).data
        const alpha = rgba[3]
        return {
          displayIndex: index + 1,
          layerName: layer.name,
          colorHex: alpha <= 8 ? null : rgbToHex(rgba[0], rgba[1], rgba[2]),
        }
      } catch {
        return {
          displayIndex: index + 1,
          layerName: layer.name,
          colorHex: null,
        }
      }
    })

    layerSampleCacheRef.current.set(layerCacheKey, sampledLayers)
    setHoverLayerColors((previous) => (areLayerSamplesEqual(previous, sampledLayers) ? previous : sampledLayers))
  }, [hoverSample, previewPixelWidth, previewPixelHeight, previewWidthMm, bedLabel, bedSizes, previewCanvasBuffer, layerCanvasBuffers])

  useEffect(() => {
    const magnifierCanvas = magnifierCanvasRef.current
    const context = magnifierCanvas?.getContext("2d")
    if (!magnifierCanvas || !context) {
      return
    }

    context.clearRect(0, 0, magnifierCanvas.width, magnifierCanvas.height)

    if (!hoverSample) {
      return
    }

    const previewBuffer = previewCanvasBuffer
    if (!previewBuffer) {
      return
    }

    const centerX = mapPixelToBufferCoordinate(hoverSample.pixelX, hoverSample.naturalWidth, previewBuffer.width)
    const centerY = mapPixelToBufferCoordinate(hoverSample.pixelY, hoverSample.naturalHeight, previewBuffer.height)

    const sourceSize = MAGNIFIER_SIZE_PX / MAGNIFIER_ZOOM
    const maxSourceX = Math.max(0, previewBuffer.width - sourceSize)
    const maxSourceY = Math.max(0, previewBuffer.height - sourceSize)
    const sourceX = clampNumber(centerX - sourceSize / 2, 0, maxSourceX)
    const sourceY = clampNumber(centerY - sourceSize / 2, 0, maxSourceY)

    context.imageSmoothingEnabled = false
    context.drawImage(
      previewBuffer.context.canvas,
      sourceX,
      sourceY,
      sourceSize,
      sourceSize,
      0,
      0,
      magnifierCanvas.width,
      magnifierCanvas.height,
    )

    const center = magnifierCanvas.width / 2
    context.strokeStyle = "rgba(255, 255, 255, 0.9)"
    context.lineWidth = 1
    context.beginPath()
    context.moveTo(center, 0)
    context.lineTo(center, magnifierCanvas.height)
    context.moveTo(0, center)
    context.lineTo(magnifierCanvas.width, center)
    context.stroke()
  }, [hoverSample, previewCanvasBuffer])

  const handlePreviewHoverSample = useCallback((sample: ZoomableImageHoverSample | null) => {
    pendingHoverSampleRef.current = sample

    if (hoverDelayTimerRef.current !== null) {
      window.clearTimeout(hoverDelayTimerRef.current)
      hoverDelayTimerRef.current = null
    }

    if (sample === null) {
      setHoverSample((previous) => (previous === null ? previous : null))
      return
    }

    setHoverSample((previous) => (previous === null ? previous : null))

    hoverDelayTimerRef.current = window.setTimeout(() => {
      hoverDelayTimerRef.current = null
      const pending = pendingHoverSampleRef.current
      if (!pending) {
        return
      }
      setHoverSample((previous) => (areHoverSamplesEqual(previous, pending) ? previous : pending))
    }, HOVER_POPOVER_DELAY_MS)
  }, [])

  const hoverInspectorStyle = hoverSample ? computeHoverInspectorStyle(hoverSample) : null

  const hoverInspectorContent = hoverSample && hoverInspectorStyle ? (
    <div
      className="pointer-events-none fixed z-[60]"
      style={hoverInspectorStyle}
      data-testid="action-hover-inspector"
    >
      <div
        className="w-[248px] rounded-xl border p-2 shadow-xl backdrop-blur-sm"
        style={{
          borderColor: "var(--surface-outline)",
          background: "var(--surface-panel-strong)",
          color: "var(--surface-text-muted)",
        }}
      >
        <div
          className="relative overflow-hidden rounded-md border"
          style={{ borderColor: "var(--surface-outline)" }}
        >
          <canvas
            ref={magnifierCanvasRef}
            width={MAGNIFIER_SIZE_PX}
            height={MAGNIFIER_SIZE_PX}
            className="h-[152px] w-[152px]"
            aria-label={t("viewer_hover_magnifier")}
          />
          <span
            className="absolute left-2 top-2 rounded border px-1.5 py-0.5 text-[10px]"
            style={{
              borderColor: "var(--surface-outline)",
              background: "var(--surface-section-muted)",
            }}
          >
            {t("viewer_hover_magnifier")}
          </span>
        </div>

        <div className="mt-2 space-y-1 text-[11px]">
          <div className="flex items-center justify-between">
            <span>{t("viewer_hover_pixel")}</span>
            <span className="font-mono">({hoverSample.pixelX}, {hoverSample.pixelY})</span>
          </div>
          <div className="flex items-center justify-between gap-2">
            <span>{t("viewer_hover_surface_color")}</span>
            <span className="inline-flex items-center gap-1.5 font-mono">
              <span
                className="h-3 w-3 rounded border"
                style={{
                  borderColor: "var(--surface-outline)",
                  backgroundColor: hoverSurfaceHex ? `#${hoverSurfaceHex}` : "transparent",
                }}
              />
              {hoverSurfaceHex ? `#${hoverSurfaceHex}` : t("viewer_hover_transparent")}
            </span>
          </div>
        </div>

        <div
          className="mt-2 border-t pt-2"
          style={{ borderColor: "var(--surface-outline)" }}
        >
          <div className="mb-1 text-[11px] font-semibold">
            {t("viewer_hover_layers_title")}
          </div>
          {layerImagesLoading && hoverLayerColors.length === 0 ? (
            <p className="text-[11px]">{t("viewer_hover_loading_layers")}</p>
          ) : hoverLayerColors.length > 0 ? (
            <ul className="max-h-28 space-y-1 overflow-y-auto pr-1 text-[11px]">
              {hoverLayerColors.map((layer) => (
                <li
                  key={`${layer.displayIndex}-${layer.layerName}`}
                  className="flex items-center justify-between gap-2"
                >
                  <span className="truncate">
                    {t("action_layer_nth")}{layer.displayIndex}{t("action_layer_unit")}
                  </span>
                  <span className="inline-flex items-center gap-1.5 font-mono">
                    <span
                      className="h-2.5 w-2.5 rounded border"
                      style={{
                        borderColor: "var(--surface-outline)",
                        backgroundColor: layer.colorHex ? `#${layer.colorHex}` : "transparent",
                      }}
                    />
                    {layer.colorHex ? `#${layer.colorHex}` : t("viewer_hover_transparent")}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[11px]">{t("viewer_hover_no_layer_data")}</p>
          )}
        </div>
      </div>
    </div>
  ) : null

  const hoverInspectorOverlay = hoverInspectorContent && typeof document !== "undefined"
    ? createPortal(hoverInspectorContent, document.body)
    : null

  return (
    <div className="flex flex-col gap-3">
      {batchMode ? (
        <>
          {!canBatchSubmit && (
            <p className="text-xs text-yellow-600 dark:text-yellow-400">{t("action_batch_upload_hint")}</p>
          )}

          <div className={`gap-2 ${workspace.isCompact ? "grid grid-cols-1" : "flex flex-wrap"}`}>
            <Button
              label={t("action_batch_generate")}
              variant="primary"
              onClick={() => void submitBatch()}
              disabled={!canBatchSubmit || batchLoading}
              loading={batchLoading}
            />
          </div>

          {batchResult && <BatchResultSummary result={batchResult} />}
        </>
      ) : (
        <>
          {!canSubmit && (
            <p className="text-xs text-yellow-600 dark:text-yellow-400">{t("action_upload_hint")}</p>
          )}

          <div className="grid grid-cols-1 gap-2">
            <Button
              label={t("action_preview")}
              variant="secondary"
              onClick={submitPreview}
              disabled={!canSubmit || isLoading}
              loading={isLoading}
              className="w-full"
            />
            <WikiTooltip
              title={t("action_generate_model_title")}
              description={t("action_generate_model_desc")}
              wikiUrl="https://github.com/pekingduck/lumina-layers/wiki/Image-Converter"
            >
              <Button
                label={t("action_generate")}
                variant="primary"
                onClick={() => void submitGenerate()}
                disabled={!canSubmit || isLoading || isGenerating}
                loading={isGenerating}
                className="w-full"
              />
            </WikiTooltip>
            {hasPreview && (
              <Button
                label={layerImagesLoading ? t("action_layers_loading") : t("action_view_layers")}
                variant="secondary"
                onClick={() => void fetchLayerImages()}
                disabled={layerImagesLoading}
                loading={layerImagesLoading}
                className="w-full"
              />
            )}
            {hasPreview && (
              <div className="flex gap-2">
                <Button
                  label={isExporting ? t("recipe_export_loading") : t("recipe_export_btn")}
                  variant="secondary"
                  onClick={() => {
                    setIsExporting(true)
                    setExportError(null)
                    exportShareCard()
                      .then(() => setExportError(null))
                      .catch((err: unknown) => {
                        setExportError(err instanceof Error ? err.message : "Export failed")
                      })
                      .finally(() => setIsExporting(false))
                  }}
                  disabled={isExporting}
                  loading={isExporting}
                  className="flex-1"
                />
                <Button
                  label={t("recipe_export_sidecar_btn")}
                  variant="secondary"
                  onClick={() => {
                    setIsExporting(true)
                    setExportError(null)
                    exportSidecar()
                      .then(() => setExportError(null))
                      .catch((err: unknown) => {
                        setExportError(err instanceof Error ? err.message : "Export failed")
                      })
                      .finally(() => setIsExporting(false))
                  }}
                  disabled={isExporting}
                  className="flex-1"
                />
              </div>
            )}
            {exportError && (
              <div className="text-xs text-red-500 dark:text-red-400">
                {t("recipe_export_error").replace("{error}", exportError)}
              </div>
            )}
          </div>
        </>
      )}

      {error && (
        <div className="text-xs text-red-500 dark:text-red-400">{error}</div>
      )}

      <BedSizeSelector />

      {previewDisplayUrl && (
        <ZoomableImage
          src={previewDisplayUrl}
          alt={t("action_preview_alt")}
          className="w-full rounded-[22px] border border-gray-300 dark:border-gray-700"
          overlay={previewOverlay}
          floatingOverlay={previewDebugOverlay}
          onHoverSample={handlePreviewHoverSample}
          onImageReady={handlePreviewImageReady}
        />
      )}
      {hoverInspectorOverlay}

      {layerImages.length > 0 && (
        <div className="rounded-lg border border-gray-200 p-3 dark:border-gray-700">
          <h4 className="mb-2 text-xs font-medium text-gray-600 dark:text-gray-400">{t("action_layers_title")}</h4>
          <div className={`grid gap-2 ${workspace.isCompact ? "grid-cols-2 sm:grid-cols-3" : "grid-cols-3 sm:grid-cols-4 md:grid-cols-5"}`}>
            {layerImages.map((layer, idx) => (
              <div
                key={layer.layer_index}
                className="group cursor-pointer flex flex-col items-center gap-1"
                onClick={() => setZoomedLayerIdx(idx)}
              >
                <div className="relative w-full overflow-hidden rounded border border-gray-200 dark:border-gray-600">
                  <img
                    src={layer.url}
                    alt={`${t("action_layer_nth")}${idx + 1}${t("action_layer_unit")}`}
                    className="w-full transition-transform group-hover:scale-105"
                    draggable={false}
                  />
                  <div className="absolute inset-0 flex items-center justify-center bg-black/0 transition-colors group-hover:bg-black/20">
                    <span className="text-sm text-white opacity-0 transition-opacity group-hover:opacity-100">{t("action_zoom_icon")}</span>
                  </div>
                </div>
                <span className="text-[11px] text-gray-600 dark:text-gray-400">
                  {t("action_layer_nth")}{idx + 1}{t("action_layer_unit")}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {zoomedLayerIdx !== null && layerImages[zoomedLayerIdx] && createPortal(
        <div
          className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/80"
          onClick={() => setZoomedLayerIdx(null)}
        >
          <div
            className="relative flex max-h-[95vh] max-w-[95vw] flex-col items-center"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-3 flex w-full items-center justify-between">
              <span className="text-base font-medium text-white">
                {t("action_layer_nth")}{zoomedLayerIdx + 1}{t("action_layer_unit")}
              </span>
              <div className={`items-center gap-2 ${workspace.isCompact ? "grid grid-cols-[1fr_auto] gap-y-1" : "flex"}`}>
                <button
                  className="rounded-lg px-3 py-1 text-sm text-white/80 hover:bg-slate-200/15 disabled:opacity-30 dark:hover:bg-slate-700/30"
                  onClick={() => setZoomedLayerIdx(Math.max(0, zoomedLayerIdx - 1))}
                  disabled={zoomedLayerIdx === 0}
                >
                  {t("action_layer_prev_arrow")} {t("action_layer_prev")}
                </button>
                <span className="text-sm text-white/60">{zoomedLayerIdx + 1} / {layerImages.length}</span>
                <button
                  className="rounded-lg px-3 py-1 text-sm text-white/80 hover:bg-slate-200/15 disabled:opacity-30 dark:hover:bg-slate-700/30"
                  onClick={() => setZoomedLayerIdx(Math.min(layerImages.length - 1, zoomedLayerIdx + 1))}
                  disabled={zoomedLayerIdx === layerImages.length - 1}
                >
                  {t("action_layer_next")} {t("action_layer_next_arrow")}
                </button>
                <button
                  className="ml-2 rounded-lg p-2 text-white/80 hover:bg-slate-200/15 dark:hover:bg-slate-700/30"
                  onClick={() => setZoomedLayerIdx(null)}
                  aria-label={t("action_close_overlay")}
                >
                  {t("action_close_icon")}
                </button>
              </div>
            </div>
            <img
              src={layerImages[zoomedLayerIdx].url}
              alt={`${t("action_layer_nth")}${zoomedLayerIdx + 1}${t("action_layer_unit")}`}
              className="max-h-[85vh] max-w-full rounded-lg object-contain"
              draggable={false}
            />
          </div>
        </div>,
        document.body,
      )}

      <SlicerSelector
        threemfDiskPath={threemfDiskPath}
        downloadUrl={downloadUrl}
        canSubmit={canSubmit}
        largeFormat={largeFormatEnabled}
        onAutoGenerate={async () => {
          await submitFullPipeline()
          return useConverterStore.getState().threemfDiskPath ?? null
        }}
      />
    </div>
  )
}

