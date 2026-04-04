import { useMemo, useState, type ReactNode } from "react"
import { createPortal } from "react-dom"
import { useConverterStore } from "../../stores/converter"
import Button from "../ui/Button"
import BatchResultSummary from "../ui/BatchResultSummary"
import ZoomableImage from "../ui/ZoomableImage"
import BedSizeSelector from "./BedSizeSelector"
import SlicerSelector from "./SlicerSelector"
import WikiTooltip from "../ui/WikiTooltip"
import { useI18n } from "../../i18n/context"
import { useWorkspaceMode } from "../../hooks/useWorkspaceMode"
import { exportShareCard, exportSidecar } from "../../recipe/importFlow"

export default function ActionBar() {
  const { t } = useI18n()
  const workspace = useWorkspaceMode()
  const [zoomedLayerIdx, setZoomedLayerIdx] = useState<number | null>(null)
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
        />
      )}

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

