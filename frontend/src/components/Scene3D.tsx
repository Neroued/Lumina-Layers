import { Suspense, useRef, useState, useEffect, useCallback, useMemo } from "react";
import { Canvas, useThree, useFrame } from "@react-three/fiber";
import { OrbitControls, Environment, Html } from "@react-three/drei";
import { LIGHTING_CONFIG } from "./lightingConfig";
import * as THREE from "three";
import ModelViewer from "./ModelViewer";
import InteractiveModelViewer from "./InteractiveModelViewer";
import BedPlatform from "./BedPlatform";
import KeychainRing3D from "./KeychainRing3D";
import { useConverterStore } from "../stores/converter";
import { computeScaleFactor } from "../utils/scaleUtils";
import { useI18n } from "../i18n/context";
import { useThemeConfig } from "../hooks/useThemeConfig";
import { useWittyMessage } from "../hooks/useWittyMessage";
import {
  debugThreeLog,
  getHeapMemorySnapshot,
  getRendererInfoSnapshot,
  getThreePerfDebugConfig,
  summarizeObjectTree,
} from "../utils/threeDebug";

declare global {
  interface Window {
    __luminaCameraDebug?: () => {
      cameraPosition: { x: number; y: number; z: number };
      orbitTarget: { x: number; y: number; z: number };
      fov: number;
    };
  }
}

interface Scene3DProps {
  modelUrl?: string;
}

/**
 * Helper component rendered inside <Canvas> to expose the gl context
 * for screenshot functionality via a callback ref.
 */
function ScreenshotHelper({
  onGlReady,
}: {
  onGlReady: (gl: THREE.WebGLRenderer | null) => void;
}) {
  const { gl } = useThree();
  useEffect(() => {
    onGlReady(gl);
    return () => {
      onGlReady(null);
    };
  }, [gl, onGlReady]);
  return null;
}

/**
 * Expose camera debug info to window for tuning default view.
 * Run `window.__luminaCameraDebug()` in browser console to print current values.
 * 将相机调试信息暴露到 window，用于调优默认视角。
 */
function CameraDebugHelper() {
  const { camera, controls } = useThree();
  useEffect(() => {
    window.__luminaCameraDebug = () => {
      const pos = camera.position;
      const orbitControls =
        controls && "target" in controls
          ? (controls as { target?: THREE.Vector3 | null })
          : null;
      const target = orbitControls?.target ?? { x: 0, y: 0, z: 0 };
      const info = {
        cameraPosition: { x: +pos.x.toFixed(2), y: +pos.y.toFixed(2), z: +pos.z.toFixed(2) },
        orbitTarget: { x: +target.x.toFixed(2), y: +target.y.toFixed(2), z: +target.z.toFixed(2) },
        fov: (camera as THREE.PerspectiveCamera).fov,
      };
      console.log("📷 Camera Debug:", JSON.stringify(info, null, 2));
      return info;
    };
  }, [camera, controls]);
  return null;
}

/**
 * Inner component that syncs the Canvas clear color with the active theme.
 * Canvas 内部组件，将清除色与当前主题同步。
 */
function ThemeUpdater() {
  const { gl } = useThree();
  const themeColors = useThemeConfig();
  useEffect(() => {
    gl.setClearColor(themeColors.canvasClearColor);
  }, [gl, themeColors.canvasClearColor]);
  return null;
}

interface ScenePerformanceState {
  previewGlbUrl: string | null;
  enableOutline: boolean;
  enableCloisonne: boolean;
  structureMode: string;
}

function ScenePerformanceReporter({
  renderCountRef,
  stateRef,
}: {
  renderCountRef: { current: number };
  stateRef: { current: ScenePerformanceState };
}) {
  const gl = useThree((state) => state.gl);
  const scene = useThree((state) => state.scene);
  const camera = useThree((state) => state.camera);
  const controls = useThree((state) => state.controls);
  const lastLogAtRef = useRef(performance.now());
  const frameCountRef = useRef(0);
  const totalFrameMsRef = useRef(0);
  const maxFrameMsRef = useRef(0);
  const slowFrameCountRef = useRef(0);
  const lastRenderCountRef = useRef(0);

  useEffect(() => {
    debugThreeLog("Scene3D.canvas", {
      event: "mount",
      renderer: getRendererInfoSnapshot(gl),
    });
    return () => {
      debugThreeLog("Scene3D.canvas", {
        event: "unmount",
      });
    };
  }, [gl]);

  useFrame((_, delta) => {
    const { enabled, intervalMs } = getThreePerfDebugConfig();
    if (!enabled) {
      return;
    }

    const deltaMs = delta * 1000;
    frameCountRef.current += 1;
    totalFrameMsRef.current += deltaMs;
    maxFrameMsRef.current = Math.max(maxFrameMsRef.current, deltaMs);
    if (deltaMs > 25) {
      slowFrameCountRef.current += 1;
    }

    const now = performance.now();
    const elapsed = now - lastLogAtRef.current;
    if (elapsed < intervalMs) {
      return;
    }

    const state = stateRef.current;
    const renderCountDelta = renderCountRef.current - lastRenderCountRef.current;
    const orbitTarget =
      controls && "target" in controls
        ? (controls as { target?: THREE.Vector3 | null }).target ?? null
        : null;

    debugThreeLog("Scene3D.runtime", {
      elapsed_ms: +elapsed.toFixed(1),
      fps: +((frameCountRef.current * 1000) / Math.max(elapsed, 1)).toFixed(1),
      avg_frame_ms:
        frameCountRef.current > 0
          ? +(totalFrameMsRef.current / frameCountRef.current).toFixed(2)
          : 0,
      max_frame_ms: +maxFrameMsRef.current.toFixed(2),
      slow_frame_count: slowFrameCountRef.current,
      react_render_count: renderCountDelta,
      preview_glb_url: state.previewGlbUrl,
      enable_outline: state.enableOutline,
      enable_cloisonne: state.enableCloisonne,
      structure_mode: state.structureMode,
      camera_position: {
        x: +camera.position.x.toFixed(2),
        y: +camera.position.y.toFixed(2),
        z: +camera.position.z.toFixed(2),
      },
      orbit_target: orbitTarget
        ? {
            x: +orbitTarget.x.toFixed(2),
            y: +orbitTarget.y.toFixed(2),
            z: +orbitTarget.z.toFixed(2),
          }
        : null,
      renderer: getRendererInfoSnapshot(gl),
      scene: summarizeObjectTree(scene),
      heap: getHeapMemorySnapshot(),
    });

    lastLogAtRef.current = now;
    lastRenderCountRef.current = renderCountRef.current;
    frameCountRef.current = 0;
    totalFrameMsRef.current = 0;
    maxFrameMsRef.current = 0;
    slowFrameCountRef.current = 0;
  });

  return null;
}

function Scene3D({ modelUrl }: Scene3DProps) {
  const { t } = useI18n();
  const themeColors = useThemeConfig();
  const containerRef = useRef<HTMLDivElement>(null);
  const glRef = useRef<THREE.WebGLRenderer | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);

  // Witty Loading Messages (Req 1.4 & Enhancements)
  const isLoading = useConverterStore((s) => s.isLoading);
  const wittyMsg = useWittyMessage(2000, isLoading);

  const previewGlbUrl = useConverterStore((s) => s.previewGlbUrl);
  const colorRemapMap = useConverterStore((s) => s.colorRemapMap);
  const colorHeightMap = useConverterStore((s) => s.color_height_map);
  const selectedColor = useConverterStore((s) => s.selectedColor);
  const baseHeight = useConverterStore((s) => s.spacer_thick);
  const enableRelief = useConverterStore((s) => s.enable_relief);
  const setSelectedColor = useConverterStore((s) => s.setSelectedColor);
  const spacerThick = useConverterStore((s) => s.spacer_thick);
  const structureMode = useConverterStore((s) => s.structure_mode);
  const enableOutline = useConverterStore((s) => s.enable_outline);
  const outlineWidth = useConverterStore((s) => s.outline_width);
  const enableCloisonne = useConverterStore((s) => s.enable_cloisonne);
  const wireWidthMm = useConverterStore((s) => s.wire_width_mm);
  const wireHeightMm = useConverterStore((s) => s.wire_height_mm);
  const sceneRenderCountRef = useRef(0);
  sceneRenderCountRef.current += 1;
  const perfStateRef = useRef<ScenePerformanceState>({
    previewGlbUrl,
    enableOutline,
    enableCloisonne,
    structureMode,
  });

  useEffect(() => {
    perfStateRef.current = {
      previewGlbUrl,
      enableOutline,
      enableCloisonne,
      structureMode,
    };
  }, [
    previewGlbUrl,
    enableOutline,
    enableCloisonne,
    structureMode,
  ]);

  useEffect(() => {
    debugThreeLog("Scene3D.state", {
      preview_glb_url: previewGlbUrl,
      enable_outline: enableOutline,
      enable_cloisonne: enableCloisonne,
      structure_mode: structureMode,
    });
  }, [
    previewGlbUrl,
    enableOutline,
    enableCloisonne,
    structureMode,
  ]);

  // Real-time scale dimensions
  const targetWidth = useConverterStore((s) => s.target_width_mm);
  const targetHeight = useConverterStore((s) => s.target_height_mm);
  const previewWidth = useConverterStore((s) => s.preview_width_mm);
  const previewHeight = useConverterStore((s) => s.preview_height_mm);

  const { scaleX, scaleY } = computeScaleFactor(
    targetWidth, targetHeight, previewWidth, previewHeight
  );
  const canvasCamera = useMemo(
    () => ({ position: [0, -57, 474] as [number, number, number], fov: 45 }),
    [],
  );
  const canvasGl = useMemo(() => ({ preserveDrawingBuffer: true }), []);

  // Keychain ring params
  const addLoop = useConverterStore((s) => s.add_loop);
  const loopWidth = useConverterStore((s) => s.loop_width);
  const loopLength = useConverterStore((s) => s.loop_length);
  const loopHole = useConverterStore((s) => s.loop_hole);
  const loopAngle = useConverterStore((s) => s.loop_angle);
  const loopOffsetX = useConverterStore((s) => s.loop_offset_x);
  const loopOffsetY = useConverterStore((s) => s.loop_offset_y);
  const loopPositionPreset = useConverterStore((s) => s.loop_position_preset);
  const modelBounds = useConverterStore((s) => s.modelBounds);

  // Listen to fullscreenchange event
  useEffect(() => {
    const handler = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", handler);
    return () => document.removeEventListener("fullscreenchange", handler);
  }, []);

  useEffect(() => {
    return () => {
      const canvas = glRef.current?.domElement as (HTMLCanvasElement & {
        __luminaContextLostHandler?: (e: Event) => void;
        __luminaContextRestoredHandler?: () => void;
      }) | undefined;
      if (canvas?.__luminaContextLostHandler) {
        canvas.removeEventListener("webglcontextlost", canvas.__luminaContextLostHandler);
        delete canvas.__luminaContextLostHandler;
      }
      if (canvas?.__luminaContextRestoredHandler) {
        canvas.removeEventListener("webglcontextrestored", canvas.__luminaContextRestoredHandler);
        delete canvas.__luminaContextRestoredHandler;
      }
      glRef.current = null;
    };
  }, []);

  const handleGlReady = useCallback((gl: THREE.WebGLRenderer | null) => {
    glRef.current = gl;
  }, []);

  const toggleFullscreen = useCallback(() => {
    if (!containerRef.current) return;
    if (document.fullscreenElement) {
      document.exitFullscreen();
    } else {
      containerRef.current.requestFullscreen().catch(() => {
        // Fullscreen API not available, fail silently
      });
    }
  }, []);

  const takeScreenshot = useCallback(() => {
    const gl = glRef.current;
    if (!gl) return;
    // Render one frame with preserveDrawingBuffer behavior
    try {
      const dataUrl = gl.domElement.toDataURL("image/png");
      const link = document.createElement("a");
      link.download = `lumina-3d-screenshot-${Date.now()}.png`;
      link.href = dataUrl;
      link.click();
    } catch (err) {
      console.warn("Screenshot failed:", err);
    }
  }, []);

  const handleColorClick = useCallback(
    (hex: string | null) => {
      setSelectedColor(hex);
    },
    [setSelectedColor],
  );

  const handlePointerMissed = useCallback(() => {
    const hitRef = (window as unknown as Record<string, unknown>).__luminaColorHitRef as
      | React.RefObject<boolean>
      | undefined;
    if (hitRef?.current) {
      hitRef.current = false;
      return;
    }
    setSelectedColor(null);
  }, [setSelectedColor]);

  const handleCanvasCreated = useCallback(
    ({ gl }: { gl: THREE.WebGLRenderer }) => {
      gl.setClearColor(themeColors.canvasClearColor);
      const canvas = gl.domElement;
      const handleContextLost = (e: Event) => {
        e.preventDefault();
      };
      const handleContextRestored = () => {
        gl.setSize(canvas.clientWidth, canvas.clientHeight);
      };
      canvas.addEventListener("webglcontextlost", handleContextLost);
      canvas.addEventListener("webglcontextrestored", handleContextRestored);
      const canvasRecord = canvas as HTMLCanvasElement & {
        __luminaContextLostHandler?: (e: Event) => void;
        __luminaContextRestoredHandler?: () => void;
      };
      canvasRecord.__luminaContextLostHandler = handleContextLost;
      canvasRecord.__luminaContextRestoredHandler = handleContextRestored;
    },
    [themeColors.canvasClearColor],
  );

  // Check if Fullscreen API is available
  const fullscreenSupported = typeof document.fullscreenElement !== "undefined";

  const canvasElement = useMemo(() => (
    <Canvas
      camera={canvasCamera}
      gl={canvasGl}
      onPointerMissed={handlePointerMissed}
      onCreated={handleCanvasCreated}
    >
      <ScreenshotHelper onGlReady={handleGlReady} />
      <CameraDebugHelper />
      <ThemeUpdater />
      <ScenePerformanceReporter
        renderCountRef={sceneRenderCountRef}
        stateRef={perfStateRef}
      />
      <Suspense fallback={null}>
        <Environment
          files={LIGHTING_CONFIG.environment.hdrFile}
          background={false}
          environmentIntensity={themeColors.environmentIntensity}
        />
      </Suspense>
      <directionalLight
        position={[...LIGHTING_CONFIG.keyLight.position]}
        intensity={themeColors.keyLightIntensity}
        color={themeColors.keyLightColor}
      />
      <OrbitControls
        makeDefault
        enableDamping
        dampingFactor={0.1}
        minDistance={10}
        maxDistance={2000}
      />
      <BedPlatform />
      {modelUrl ? (
        <Suspense fallback={null}>
          <ModelViewer url={modelUrl} />
        </Suspense>
      ) : previewGlbUrl ? (
        <Suspense fallback={null}>
          <InteractiveModelViewer
            url={previewGlbUrl}
            colorRemapMap={colorRemapMap}
            colorHeightMap={colorHeightMap}
            selectedColor={selectedColor}
            baseHeight={baseHeight}
            enableRelief={enableRelief}
            onColorClick={handleColorClick}
            scaleX={scaleX}
            scaleY={scaleY}
            spacerThick={spacerThick}
            structureMode={structureMode}
            enableOutline={enableOutline}
            outlineWidth={outlineWidth}
            enableCloisonne={enableCloisonne}
            wireWidthMm={wireWidthMm}
            wireHeightMm={wireHeightMm}
          />
        </Suspense>
      ) : null}
      {addLoop && modelBounds && (
        <KeychainRing3D
          enabled={addLoop}
          width={loopWidth}
          length={loopLength}
          hole={loopHole}
          angle={loopAngle}
          offsetX={loopOffsetX}
          offsetY={loopOffsetY}
          positionPreset={loopPositionPreset}
          modelBounds={modelBounds}
        />
      )}

      {isLoading && (
        <Html center position={[0, 0, 80]} zIndexRange={[100, 0]}>
          <div
            className="flex flex-col items-center justify-center gap-4 select-none pointer-events-none"
            data-testid="loading-overlay"
          >
            <div className="relative flex items-center justify-center p-4">
              <div className="relative flex h-20 w-20 items-center justify-center">
                <div className="absolute inset-0 rgb-loader-ring" />
                <div className="h-3 w-3 rounded-full bg-slate-100/90 dark:bg-slate-50/90" />
              </div>
            </div>
            <div className="rounded-full border border-white/10 bg-gray-900/92 px-4 py-2">
              <p className="whitespace-nowrap text-sm font-medium tracking-wide text-white">
                {wittyMsg}
              </p>
            </div>
          </div>
        </Html>
      )}
    </Canvas>
  ), [
    canvasCamera,
    canvasGl,
    handlePointerMissed,
    handleCanvasCreated,
    handleGlReady,
    themeColors.environmentIntensity,
    themeColors.keyLightIntensity,
    themeColors.keyLightColor,
    modelUrl,
    previewGlbUrl,
    colorRemapMap,
    colorHeightMap,
    selectedColor,
    baseHeight,
    enableRelief,
    handleColorClick,
    scaleX,
    scaleY,
    spacerThick,
    structureMode,
    enableOutline,
    outlineWidth,
    enableCloisonne,
    wireWidthMm,
    wireHeightMm,
    addLoop,
    modelBounds,
    loopWidth,
    loopLength,
    loopHole,
    loopAngle,
    loopOffsetX,
    loopOffsetY,
    loopPositionPreset,
    isLoading,
    wittyMsg,
  ]);

  return (
    <div
      ref={containerRef}
      className="relative w-full h-full"
      data-testid="scene3d-container"
    >
      {/* Toolbar buttons */}
      <div className="absolute top-2 right-2 z-10 flex gap-1">
        {fullscreenSupported && (
          <button
            onClick={toggleFullscreen}
            className="rounded px-2 py-1 text-xs font-medium bg-slate-100/85 text-gray-700 transition-colors hover:bg-gray-200 dark:bg-gray-700/80 dark:text-gray-200 dark:hover:bg-gray-600 backdrop-blur-sm"
            aria-label={isFullscreen ? t("viewer_exit_fullscreen") : t("viewer_fullscreen")}
            title={isFullscreen ? t("viewer_exit_fullscreen") : t("viewer_fullscreen")}
          >
            {isFullscreen ? "⛶" : "⛶"} {isFullscreen ? t("viewer_exit_fullscreen") : t("viewer_fullscreen")}
          </button>
        )}
        <button
          onClick={takeScreenshot}
          className="rounded px-2 py-1 text-xs font-medium bg-slate-100/85 text-gray-700 transition-colors hover:bg-gray-200 dark:bg-gray-700/80 dark:text-gray-200 dark:hover:bg-gray-600 backdrop-blur-sm"
          aria-label={t("viewer_screenshot")}
          title={t("viewer_screenshot")}
        >
          {t("viewer_screenshot")}
        </button>
      </div>

      {canvasElement}
    </div>
  );
}

export default Scene3D;
