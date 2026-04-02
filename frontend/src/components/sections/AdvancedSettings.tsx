import { useConverterStore } from "../../stores/converter";
import { useI18n } from "../../i18n/context";
import Slider from "../ui/Slider";
import Checkbox from "../ui/Checkbox";

export default function AdvancedSettings() {
  const { t } = useI18n();
  const quantize_colors = useConverterStore((s) => s.quantize_colors);
  const bg_tol = useConverterStore((s) => s.bg_tol);
  const auto_bg = useConverterStore((s) => s.auto_bg);
  const enable_cleanup = useConverterStore((s) => s.enable_cleanup);
  const separate_backing = useConverterStore((s) => s.separate_backing);
  const hue_enable = useConverterStore((s) => s.hue_enable);
  const chroma_gate = useConverterStore((s) => s.chroma_gate);
  const imageFile = useConverterStore((s) => s.imageFile);
  const autoDetectLoading = useConverterStore((s) => s.autoDetectColorsLoading);
  const setQuantizeColors = useConverterStore((s) => s.setQuantizeColors);
  const setBgTol = useConverterStore((s) => s.setBgTol);
  const setAutoBg = useConverterStore((s) => s.setAutoBg);
  const setEnableCleanup = useConverterStore((s) => s.setEnableCleanup);
  const setSeparateBacking = useConverterStore((s) => s.setSeparateBacking);
  const setHueEnable = useConverterStore((s) => s.setHueEnable);
  const setChromaGate = useConverterStore((s) => s.setChromaGate);
  const autoDetectColors = useConverterStore((s) => s.autoDetectColors);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <Slider label={t("adv_quantize_colors")} value={quantize_colors} min={8} max={256} step={8} onChange={setQuantizeColors} />
        <button
          type="button"
          disabled={!imageFile || autoDetectLoading}
          onClick={autoDetectColors}
          className="self-end px-3 py-1 text-xs rounded-md bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {autoDetectLoading ? t("conv_auto_color_calculating") : t("conv_auto_color_btn")}
        </button>
      </div>
      <Slider label={t("adv_bg_tolerance")} value={bg_tol} min={0} max={150} step={1} onChange={setBgTol} />
      <Checkbox label={t("adv_auto_bg")} checked={auto_bg} onChange={setAutoBg} />
      <Checkbox label={t("adv_enable_cleanup")} checked={enable_cleanup} onChange={setEnableCleanup} />
      <Checkbox label={t("adv_separate_backing")} checked={separate_backing} onChange={setSeparateBacking} />
      <Checkbox label={t("adv_hue_protection")} checked={hue_enable} onChange={setHueEnable} />
      {hue_enable && (
        <Slider label={t("adv_chroma_gate")} value={chroma_gate} min={0} max={50} step={1} onChange={setChromaGate} />
      )}
    </div>
  );
}
