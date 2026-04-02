import { useEffect } from "react";
import { motion } from "framer-motion";
import { useI18n } from "../i18n/context";
import { useWorkspaceMode } from "../hooks/useWorkspaceMode";
import { useLutCompareStore } from "../stores/lutCompareStore";
import Dropdown from "./ui/Dropdown";
import Button from "./ui/Button";
import {
  PanelIntro,
  StatusBanner,
  desktopPrimaryColumnClass,
  desktopSecondaryColumnClass,
  mutedSectionCardClass,
  resolveDesktopSplitLayoutClass,
  resolvePanelSurfaceClass,
  resolveSectionCardClass,
} from "./ui/panelPrimitives";

function formatMetric(value: number): string {
  return value.toFixed(2);
}

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export default function LutComparePanel() {
  const { t } = useI18n();
  const workspace = useWorkspaceMode();
  const {
    lutList,
    lutListLoading,
    lutAName,
    lutBName,
    lutAInfo,
    lutBInfo,
    lutAInfoLoading,
    lutBInfoLoading,
    comparing,
    compareResult,
    error,
    fetchLutList,
    selectLutA,
    selectLutB,
    executeCompare,
    clearError,
  } = useLutCompareStore();

  useEffect(() => {
    void fetchLutList();
  }, [fetchLutList]);

  const lutOptions = lutList.map((lut) => ({
    label: lut.name,
    value: lut.name,
  }));

  const compareDisabled = comparing || !lutAName || !lutBName;
  const stats = compareResult?.stats ?? null;

  return (
    <motion.aside
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", damping: 25, stiffness: 300 }}
      data-testid="lut-compare-panel"
      className={`${resolvePanelSurfaceClass(workspace.mode)} flex flex-col gap-5`}
    >
      <PanelIntro
        eyebrow={t("tab.lutCompare")}
        title={t("lut_compare_title")}
        description={t("lut_compare_desc")}
      />

      <div className={resolveDesktopSplitLayoutClass(workspace.mode)}>
        <div className={desktopPrimaryColumnClass}>
          <section
            data-testid="lut-compare-lut-a-dropdown"
            className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-3`}
          >
            <Dropdown
              label={t("lut_compare_lut_a_label")}
              value={lutAName}
              options={lutOptions}
              onChange={(value) => void selectLutA(value)}
              disabled={lutListLoading || comparing}
              placeholder={t("lut_compare_lut_a_placeholder")}
            />
            {lutAInfoLoading && (
              <StatusBanner tone="info">{t("lut_manager_loading")}</StatusBanner>
            )}
            {lutAInfo && (
              <div className="rounded-2xl border border-slate-200/80 bg-white/55 px-3 py-2 text-sm text-slate-600 dark:border-slate-700/80 dark:bg-slate-900/55 dark:text-slate-300">
                {t("lut_manager_mode_summary")
                  .replace("{mode}", lutAInfo.color_mode)
                  .replace("{count}", String(lutAInfo.color_count))}
              </div>
            )}
          </section>

          <section
            data-testid="lut-compare-lut-b-dropdown"
            className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-3`}
          >
            <Dropdown
              label={t("lut_compare_lut_b_label")}
              value={lutBName}
              options={lutOptions}
              onChange={(value) => void selectLutB(value)}
              disabled={lutListLoading || comparing}
              placeholder={t("lut_compare_lut_b_placeholder")}
            />
            {lutBInfoLoading && (
              <StatusBanner tone="info">{t("lut_manager_loading")}</StatusBanner>
            )}
            {lutBInfo && (
              <div className="rounded-2xl border border-slate-200/80 bg-white/55 px-3 py-2 text-sm text-slate-600 dark:border-slate-700/80 dark:bg-slate-900/55 dark:text-slate-300">
                {t("lut_manager_mode_summary")
                  .replace("{mode}", lutBInfo.color_mode)
                  .replace("{count}", String(lutBInfo.color_count))}
              </div>
            )}
          </section>

          <Button
            label={t("lut_compare_compare_btn")}
            variant="primary"
            onClick={() => void executeCompare()}
            disabled={compareDisabled}
            loading={comparing}
            className="w-full xl:w-auto"
          />
        </div>

        <div className={desktopSecondaryColumnClass}>
          {error && (
            <StatusBanner
              data-testid="error-message"
              tone="error"
              action={
                <button
                  onClick={clearError}
                  className="rounded-full border border-current/20 px-2 py-1 text-xs text-red-600 transition-colors hover:bg-red-500/10 dark:text-red-300"
                  aria-label={t("lut_manager_close_error")}
                >
                  ×
                </button>
              }
            >
              {error}
            </StatusBanner>
          )}

          {compareResult && stats && (
            <StatusBanner
              data-testid="compare-result"
              tone="success"
              title={t("lut_compare_result_title")}
            >
              <p>{compareResult.message}</p>
              <p>
                {t("lut_compare_matched")}: {stats.matched_recipe_count} |{" "}
                {t("lut_compare_identical")}: {stats.identical_rgb_count}
              </p>
              <p>
                {t("lut_compare_mean")}: {formatMetric(stats.mean_delta_e00)} |{" "}
                {t("lut_compare_p95")}: {formatMetric(stats.p95_delta_e00)} |{" "}
                {t("lut_compare_max")}: {formatMetric(stats.max_delta_e00)}
              </p>
              <p>
                {t("lut_compare_coverage_a")}: {formatPercent(stats.recipe_coverage_a)} |{" "}
                {t("lut_compare_coverage_b")}: {formatPercent(stats.recipe_coverage_b)}
              </p>
            </StatusBanner>
          )}

          {compareResult?.warnings.length ? (
            <StatusBanner
              data-testid="compare-warnings"
              tone="warning"
              title={t("lut_compare_warnings_title")}
            >
              <ul className="list-disc pl-5">
                {compareResult.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </StatusBanner>
          ) : null}

          <section
            data-testid="worst-diffs"
            className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-4`}
          >
            <div>
              <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">
                {t("lut_compare_worst_title")}
              </h3>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                {t("lut_compare_worst_desc")}
              </p>
            </div>

            {compareResult?.worst_diffs.length ? (
              <div className="flex flex-col gap-3">
                {compareResult.worst_diffs.map((item, index) => (
                  <div
                    key={`${item.recipe.join("|")}-${index}`}
                    className="rounded-[24px] border border-slate-200/80 bg-white/55 p-4 shadow-[var(--shadow-control)] dark:border-slate-700/80 dark:bg-slate-900/55"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold text-slate-900 dark:text-slate-50">
                          {item.recipe.join(" / ")}
                        </p>
                        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                          {t("lut_compare_delta")}: {formatMetric(item.delta_e00)}
                        </p>
                      </div>
                      <div className="shrink-0 text-right text-xs text-slate-500 dark:text-slate-400">
                        <p>{item.hex_a}</p>
                        <p>{item.hex_b}</p>
                      </div>
                    </div>

                    <div className="mt-3 flex items-center gap-3">
                      <div className="flex items-center gap-2">
                        <span
                          className="h-6 w-6 rounded-full border border-slate-200/80 dark:border-slate-700/80"
                          style={{ backgroundColor: item.hex_a }}
                        />
                        <span className="text-xs text-slate-600 dark:text-slate-300">
                          A
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span
                          className="h-6 w-6 rounded-full border border-slate-200/80 dark:border-slate-700/80"
                          style={{ backgroundColor: item.hex_b }}
                        />
                        <span className="text-xs text-slate-600 dark:text-slate-300">
                          B
                        </span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className={`${mutedSectionCardClass} flex min-h-[220px] flex-col justify-center gap-3`}>
                <p className="text-sm font-medium text-slate-700 dark:text-slate-200">
                  {compareResult ? t("lut_compare_no_diffs") : t("lut_compare_no_result")}
                </p>
                <p className="text-sm leading-6 text-slate-500 dark:text-slate-400">
                  {t("lut_compare_desc")}
                </p>
              </div>
            )}
          </section>
        </div>
      </div>
    </motion.aside>
  );
}
