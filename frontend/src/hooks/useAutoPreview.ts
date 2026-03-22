import { useEffect, useRef } from "react";
import { useConverterStore } from "../stores/converterStore";

/**
 * Auto-trigger preview when preconditions are met.
 * 当图片已上传、LUT 已选择、裁剪模态框已关闭、且当前图片已手动预览过时，
 * 后续参数变化自动触发预览（300ms 防抖）。
 *
 * 新上传的图片必须先手动点击"预览"按钮，之后参数变化才会自动触发。
 */
export function useAutoPreview(): void {
  const imageFile = useConverterStore((s) => s.imageFile);
  const lut_name = useConverterStore((s) => s.lut_name);
  const cropModalOpen = useConverterStore((s) => s.cropModalOpen);
  const hue_enable = useConverterStore((s) => s.hue_enable);
  const chroma_gate = useConverterStore((s) => s.chroma_gate);
  const hasManualPreview = useConverterStore((s) => s.hasManualPreview);
  const submitPreview = useConverterStore((s) => s.submitPreview);

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastTriggeredRef = useRef<{
    imageFile: File | null;
    lut_name: string;
    hue_enable: boolean;
    chroma_gate: number;
  }>({
    imageFile: null,
    lut_name: "",
    hue_enable: false,
    chroma_gate: 15,
  });

  useEffect(() => {
    // Clear any pending timer on every dependency change
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }

    // Check preconditions: 必须有图片、有 LUT、裁剪弹窗关闭、且已手动预览过
    if (!imageFile || !lut_name || cropModalOpen || !hasManualPreview) {
      return;
    }

    // Skip if same combination was already triggered
    const last = lastTriggeredRef.current;
    if (
      last.imageFile === imageFile &&
      last.lut_name === lut_name &&
      last.hue_enable === hue_enable &&
      last.chroma_gate === chroma_gate
    ) {
      return;
    }

    // hasManualPreview just flipped to true (manual preview completed).
    // Seed the ref so we don't re-trigger what was just manually run.
    if (last.imageFile === null) {
      lastTriggeredRef.current = { imageFile, lut_name, hue_enable, chroma_gate };
      return;
    }

    // Debounce 300ms then trigger preview
    timerRef.current = setTimeout(() => {
      lastTriggeredRef.current = {
        imageFile,
        lut_name,
        hue_enable,
        chroma_gate,
      };
      submitPreview();
    }, 300);

    // Cleanup on unmount
    return () => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [
    imageFile,
    lut_name,
    cropModalOpen,
    hue_enable,
    chroma_gate,
    hasManualPreview,
    submitPreview,
  ]);
}
