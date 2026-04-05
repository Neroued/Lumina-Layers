/**
 * ColorWorkstation — fixed bottom-center entry bar for the 2D color overlay.
 * ColorWorkstation — 固定在视口底部中央的入口条，点击打开 2D 颜色编辑覆盖层。
 *
 * Renders outside the DndContext, does not participate in drag-and-drop.
 * Clicking the title bar opens the full-screen Color2DOverlay.
 * 在 DndContext 之外渲染，不参与拖拽系统。
 * 点击标题栏打开全屏 Color2DOverlay。
 */

import { forwardRef, useMemo } from 'react';
import { useWidgetStore } from '../../stores/widgetStore';
import { useSettingsStore } from '../../stores/settingsStore';
import { useI18n } from '../../i18n/context';
import { cx, workstationShellClass } from '../ui/panelPrimitives';
import type { WorkspaceMode } from '../../types/workspace';

/** Title bar height in pixels. (标题栏高度) */
export const COLOR_WORKSTATION_TITLE_BAR_HEIGHT = 32;
export const COLOR_WORKSTATION_WIDTH = 1500;

interface ColorWorkstationProps {
  workspaceWidth?: number;
  dockWidth?: number;
  mode?: WorkspaceMode;
}

// Chevron icons removed in favor of iOS style drag handle

const ColorWorkstation = forwardRef<HTMLDivElement, ColorWorkstationProps>(function ColorWorkstation({
  workspaceWidth,
  dockWidth = 0,
  mode = 'standard',
}, ref) {
  const activeTab = useWidgetStore((s) => s.activeTab);
  const openOverlay = useWidgetStore((s) => s.openColor2DOverlay);
  const enableBlur = useSettingsStore((s) => s.enableBlur);
  const { t } = useI18n();

  const panelWidth = useMemo(() => {
    if (!workspaceWidth || workspaceWidth <= 0) {
      return `min(${COLOR_WORKSTATION_WIDTH}px, calc(100vw - 24px))`;
    }

    const sideClearance = dockWidth > 0 ? dockWidth * 2 + 32 : 24;
    const modeFloor = mode === 'compact' ? 560 : 720;
    const modeMax = mode === 'compact' ? 1040 : COLOR_WORKSTATION_WIDTH;
    const safeWidth = Math.max(modeFloor, workspaceWidth - sideClearance);
    return `${Math.min(modeMax, safeWidth)}px`;
  }, [dockWidth, mode, workspaceWidth]);

  // Only render on converter tab
  if (activeTab !== 'converter') return null;

  return (
    <div
      ref={ref}
      data-testid="color-workstation"
      style={{
        position: 'fixed',
        bottom: 0,
        left: '50%',
        transform: 'translateX(-50%)',
        width: panelWidth,
        maxWidth: 'calc(100vw - 24px)',
        height: COLOR_WORKSTATION_TITLE_BAR_HEIGHT,
        zIndex: 35,
        overflow: 'hidden',
      }}
      className={cx(
        workstationShellClass,
        "border-x border-t border-slate-200/80 dark:border-slate-800/80",
        "bg-slate-100/98 shadow-[var(--shadow-panel-top)] dark:bg-slate-950/98",
        enableBlur && "backdrop-blur-[2px]"
      )}
    >
      {/* Click to open 2D color overlay */}
      <div
        onClick={openOverlay}
        className="flex w-full cursor-pointer select-none items-center justify-center border-b border-slate-200/70 bg-slate-100 transition-colors hover:bg-slate-100/90 dark:border-slate-800/80 dark:bg-slate-950 dark:hover:bg-slate-900"
        style={{ height: COLOR_WORKSTATION_TITLE_BAR_HEIGHT }}
        aria-label={t('widget.colorWorkstation')}
      >
        <div className="h-1.5 w-12 rounded-full bg-slate-400/60 transition-transform hover:scale-x-110 hover:bg-slate-500 dark:bg-slate-500/60 dark:hover:bg-slate-400" />
        <span className="ml-2 text-xs text-slate-500 dark:text-slate-400">{t('widget.colorWorkstationHint')}</span>
      </div>
    </div>
  );
});

export default ColorWorkstation;
