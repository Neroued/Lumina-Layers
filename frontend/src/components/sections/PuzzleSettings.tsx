import { useMemo } from "react";
import { useConverterStore } from "../../stores/converter";
import { useI18n } from "../../i18n/context";
import Checkbox from "../ui/Checkbox";
import Dropdown from "../ui/Dropdown";
import Slider from "../ui/Slider";
import {
  cx,
  mutedSectionCardClass,
  workstationFieldLabelClass,
  workstationInputClass,
} from "../ui/panelPrimitives";

interface NumberFieldProps {
  label: string;
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  disabled?: boolean;
  unit?: string;
}

function NumberField({
  label,
  value,
  onChange,
  min,
  max,
  step = 1,
  disabled = false,
  unit,
}: NumberFieldProps) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className={workstationFieldLabelClass}>{label}</label>
      <div className="flex items-center gap-2">
        <input
          type="number"
          value={value}
          min={min}
          max={max}
          step={step}
          disabled={disabled}
          onChange={(event) => onChange(Number(event.target.value))}
          className={cx(workstationInputClass, "tabular-nums")}
        />
        {unit ? (
          <span className="text-xs font-medium text-slate-500 dark:text-slate-400">
            {unit}
          </span>
        ) : null}
      </div>
    </div>
  );
}

export default function PuzzleSettings() {
  const { t } = useI18n();
  const puzzleEnabled = useConverterStore((s) => s.puzzleEnabled);
  const puzzleStyle = useConverterStore((s) => s.puzzleStyle);
  const puzzleSizingMode = useConverterStore((s) => s.puzzleSizingMode);
  const pieceWidthMm = useConverterStore((s) => s.pieceWidthMm);
  const pieceHeightMm = useConverterStore((s) => s.pieceHeightMm);
  const puzzleRows = useConverterStore((s) => s.puzzleRows);
  const puzzleCols = useConverterStore((s) => s.puzzleCols);
  const targetPieceCount = useConverterStore((s) => s.targetPieceCount);
  const connectorStyle = useConverterStore((s) => s.connectorStyle);
  const labelsEnabled = useConverterStore((s) => s.labelsEnabled);
  const engraveBackLabels = useConverterStore((s) => s.engraveBackLabels);
  const irregularityStrength = useConverterStore((s) => s.irregularityStrength);
  const minNeckWidthMm = useConverterStore((s) => s.minNeckWidthMm);
  const puzzleWarnings = useConverterStore((s) => s.puzzleWarnings);
  const puzzleResolvedRows = useConverterStore((s) => s.puzzleResolvedRows);
  const puzzleResolvedCols = useConverterStore((s) => s.puzzleResolvedCols);
  const puzzleResolvedPieceCount = useConverterStore(
    (s) => s.puzzleResolvedPieceCount,
  );
  const puzzleDerivedPieceWidthMm = useConverterStore(
    (s) => s.puzzleDerivedPieceWidthMm,
  );
  const puzzleDerivedPieceHeightMm = useConverterStore(
    (s) => s.puzzleDerivedPieceHeightMm,
  );
  const batchMode = useConverterStore((s) => s.batchMode);

  const setPuzzleEnabled = useConverterStore((s) => s.setPuzzleEnabled);
  const setPuzzleStyle = useConverterStore((s) => s.setPuzzleStyle);
  const setPuzzleSizingMode = useConverterStore((s) => s.setPuzzleSizingMode);
  const setPieceWidthMm = useConverterStore((s) => s.setPieceWidthMm);
  const setPieceHeightMm = useConverterStore((s) => s.setPieceHeightMm);
  const setPuzzleRows = useConverterStore((s) => s.setPuzzleRows);
  const setPuzzleCols = useConverterStore((s) => s.setPuzzleCols);
  const setTargetPieceCount = useConverterStore((s) => s.setTargetPieceCount);
  const setConnectorStyle = useConverterStore((s) => s.setConnectorStyle);
  const setLabelsEnabled = useConverterStore((s) => s.setLabelsEnabled);
  const setEngraveBackLabels = useConverterStore((s) => s.setEngraveBackLabels);
  const setIrregularityStrength = useConverterStore(
    (s) => s.setIrregularityStrength,
  );
  const setMinNeckWidthMm = useConverterStore((s) => s.setMinNeckWidthMm);

  const styleOptions = useMemo(
    () => [
      { label: t("puzzle_style_regular"), value: "regular" },
      { label: t("puzzle_style_irregular"), value: "irregular" },
    ],
    [t],
  );

  const sizingModeOptions = useMemo(
    () => [
      { label: t("puzzle_sizing_piece_size"), value: "piece_size" },
      { label: t("puzzle_sizing_grid"), value: "grid" },
      { label: t("puzzle_sizing_piece_count"), value: "piece_count" },
    ],
    [t],
  );

  const connectorOptions = useMemo(
    () => [
      { label: t("puzzle_connector_classic"), value: "classic" },
      { label: t("puzzle_connector_easy_cut"), value: "easy_cut" },
    ],
    [t],
  );

  const resolvedGridText =
    puzzleResolvedRows && puzzleResolvedCols
      ? `${puzzleResolvedCols} × ${puzzleResolvedRows}`
      : "—";
  const requestedGridText =
    puzzleSizingMode === "grid" ? `${puzzleCols} × ${puzzleRows}` : "—";
  const requestedPieceCountText =
    puzzleSizingMode === "piece_count"
      ? String(targetPieceCount)
      : puzzleSizingMode === "grid"
        ? String(puzzleRows * puzzleCols)
        : "—";
  const resolvedPieceCountText =
    puzzleResolvedPieceCount !== null ? String(puzzleResolvedPieceCount) : "—";
  const resolvedPieceSizeText =
    puzzleDerivedPieceWidthMm !== null && puzzleDerivedPieceHeightMm !== null
      ? `${puzzleDerivedPieceWidthMm.toFixed(1)} × ${puzzleDerivedPieceHeightMm.toFixed(1)} mm`
      : "—";

  return (
    <div className="flex flex-col gap-4">
      <Checkbox
        label={t("puzzle_enable")}
        checked={puzzleEnabled}
        onChange={setPuzzleEnabled}
        disabled={batchMode}
      />

      {batchMode ? (
        <div className={mutedSectionCardClass}>
          <p className="text-xs text-slate-600 dark:text-slate-300">
            {t("puzzle_batch_disabled_hint")}
          </p>
        </div>
      ) : null}

      {puzzleEnabled ? (
        <>
          <Dropdown
            label={t("puzzle_style")}
            value={puzzleStyle}
            options={styleOptions}
            onChange={(value) => setPuzzleStyle(value as "regular" | "irregular")}
          />

          <Dropdown
            label={t("puzzle_sizing_mode")}
            value={puzzleSizingMode}
            options={sizingModeOptions}
            onChange={(value) =>
              setPuzzleSizingMode(value as "piece_size" | "grid" | "piece_count")
            }
          />

          {puzzleSizingMode === "piece_size" ? (
            <>
              <Slider
                label={t("puzzle_piece_width")}
                value={pieceWidthMm}
                min={5}
                max={200}
                step={1}
                unit="mm"
                onChange={setPieceWidthMm}
              />
              <Slider
                label={t("puzzle_piece_height")}
                value={pieceHeightMm}
                min={5}
                max={200}
                step={1}
                unit="mm"
                onChange={setPieceHeightMm}
              />
            </>
          ) : null}

          {puzzleSizingMode === "grid" ? (
            <div className="grid grid-cols-2 gap-3">
              <NumberField
                label={t("puzzle_rows")}
                value={puzzleRows}
                min={1}
                max={200}
                onChange={setPuzzleRows}
              />
              <NumberField
                label={t("puzzle_cols")}
                value={puzzleCols}
                min={1}
                max={200}
                onChange={setPuzzleCols}
              />
            </div>
          ) : null}

          {puzzleSizingMode === "piece_count" ? (
            <NumberField
              label={t("puzzle_target_piece_count")}
              value={targetPieceCount}
              min={2}
              max={2000}
              onChange={setTargetPieceCount}
            />
          ) : null}

          <Dropdown
            label={t("puzzle_connector_style")}
            value={connectorStyle}
            options={connectorOptions}
            onChange={(value) =>
              setConnectorStyle(value as "classic" | "easy_cut")
            }
          />

          <Checkbox
            label={t("puzzle_labels")}
            checked={labelsEnabled}
            onChange={setLabelsEnabled}
          />

          <Checkbox
            label={t("puzzle_engrave_back_labels")}
            checked={engraveBackLabels}
            onChange={setEngraveBackLabels}
            disabled
          />
          <p className="-mt-2 px-1 text-xs text-slate-500 dark:text-slate-400">
            {t("puzzle_back_engrave_unavailable_hint")}
          </p>

          {puzzleStyle === "irregular" ? (
            <>
              <Slider
                label={t("puzzle_irregularity_strength")}
                value={irregularityStrength}
                min={0}
                max={1}
                step={0.01}
                onChange={setIrregularityStrength}
                displayDecimals={2}
              />
              <Slider
                label={t("puzzle_min_neck_width")}
                value={minNeckWidthMm}
                min={0.2}
                max={20}
                step={0.1}
                unit="mm"
                onChange={setMinNeckWidthMm}
              />
            </>
          ) : null}

          <div className={mutedSectionCardClass}>
            <div className="flex flex-col gap-2 text-sm text-slate-700 dark:text-slate-200">
              <div className="flex items-center justify-between gap-3">
                <span>{t("puzzle_summary_requested_grid")}</span>
                <span className="font-mono">{requestedGridText}</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span>{t("puzzle_summary_requested_piece_count")}</span>
                <span className="font-mono">{requestedPieceCountText}</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span>{t("puzzle_summary_grid")}</span>
                <span className="font-mono">{resolvedGridText}</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span>{t("puzzle_summary_piece_count")}</span>
                <span className="font-mono">{resolvedPieceCountText}</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span>{t("puzzle_summary_piece_size")}</span>
                <span className="font-mono text-right">
                  {resolvedPieceSizeText}
                </span>
              </div>
            </div>
          </div>

          {puzzleWarnings.length > 0 ? (
            <div className={mutedSectionCardClass}>
              <p className="mb-2 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
                {t("puzzle_warnings")}
              </p>
              <div className="flex flex-col gap-1 text-xs text-amber-700 dark:text-amber-300">
                {puzzleWarnings.map((warning, index) => (
                  <p key={`${warning}-${index}`}>{warning}</p>
                ))}
              </div>
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
