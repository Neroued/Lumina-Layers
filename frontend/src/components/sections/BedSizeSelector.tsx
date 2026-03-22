import { useConverterStore } from "../../stores/converterStore";
import { useI18n } from "../../i18n/context";

export default function BedSizeSelector() {
  const { t } = useI18n();
  const bed_label = useConverterStore((s) => s.bed_label);

  return (
    <div className="flex items-center justify-between rounded-2xl border border-slate-200/80 bg-white/60 px-3 py-2 dark:border-slate-700/60 dark:bg-slate-900/50">
      <span className="text-[clamp(0.65rem,0.85vw,0.75rem)] font-medium text-slate-500 dark:text-slate-400">
        {t("bed_size_label")}
      </span>
      <span className="text-[clamp(0.65rem,0.85vw,0.75rem)] tabular-nums text-slate-700 dark:text-slate-200">
        {bed_label}
      </span>
    </div>
  );
}
