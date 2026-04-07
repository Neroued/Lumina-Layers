import { useState, useRef, useCallback, useEffect, type ReactNode, type WheelEvent, type MouseEvent } from "react";
import { useI18n } from "../../i18n/context";

/** Clamp scale to the allowed zoom range [0.5, 5.0]. */
export function clampScale(value: number): number {
  return Math.min(5.0, Math.max(0.5, value));
}

/**
 * Compute the new translate after a zoom so the point under the cursor stays stationary.
 *
 * Formula: newTranslate = mousePos - (mousePos - oldTranslate) * (newScale / oldScale)
 */
export function computeZoomTranslate(
  mousePos: { x: number; y: number },
  oldTranslate: { x: number; y: number },
  oldScale: number,
  newScale: number,
): { x: number; y: number } {
  const ratio = newScale / oldScale;
  return {
    x: mousePos.x - (mousePos.x - oldTranslate.x) * ratio,
    y: mousePos.y - (mousePos.y - oldTranslate.y) * ratio,
  };
}

interface ZoomableImageProps {
  src: string;
  alt: string;
  className?: string;
  overlay?: ReactNode;
  floatingOverlay?: ReactNode;
  onHoverSample?: (sample: ZoomableImageHoverSample | null) => void;
  onImageReady?: (image: HTMLImageElement | null) => void;
}

export interface ZoomableImageHoverSample {
  containerX: number;
  containerY: number;
  containerWidth: number;
  containerHeight: number;
  containerLeft: number;
  containerTop: number;
  pixelX: number;
  pixelY: number;
  naturalWidth: number;
  naturalHeight: number;
}

export default function ZoomableImage({
  src,
  alt,
  className,
  overlay,
  floatingOverlay,
  onHoverSample,
  onImageReady,
}: ZoomableImageProps) {
  const { t } = useI18n();
  const [scale, setScale] = useState(1);
  const [translate, setTranslate] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const dragStart = useRef({ x: 0, y: 0 });
  const translateAtDragStart = useRef({ x: 0, y: 0 });
  const lastHoverSignatureRef = useRef<string>("");

  const emitHoverSample = useCallback(
    (sample: ZoomableImageHoverSample | null) => {
      if (!onHoverSample) return;
      if (!sample) {
        if (lastHoverSignatureRef.current === "__null__") return;
        lastHoverSignatureRef.current = "__null__";
        onHoverSample(null);
        return;
      }
      const signature = `${sample.containerX},${sample.containerY},${sample.containerLeft},${sample.containerTop},${sample.pixelX},${sample.pixelY}`;
      if (signature === lastHoverSignatureRef.current) return;
      lastHoverSignatureRef.current = signature;
      onHoverSample(sample);
    },
    [onHoverSample],
  );

  const mapMouseToImagePixel = useCallback(
    (clientX: number, clientY: number): ZoomableImageHoverSample | null => {
      const container = containerRef.current;
      const image = imgRef.current;
      if (!container || !image) {
        return null;
      }
      const renderedWidth = image.clientWidth;
      const renderedHeight = image.clientHeight;
      const naturalWidth = image.naturalWidth;
      const naturalHeight = image.naturalHeight;
      if (renderedWidth <= 0 || renderedHeight <= 0 || naturalWidth <= 0 || naturalHeight <= 0) {
        return null;
      }

      const rect = container.getBoundingClientRect();
      const relX = clientX - rect.left;
      const relY = clientY - rect.top;
      const imageX = (relX - translate.x) / scale;
      const imageY = (relY - translate.y) / scale;
      if (imageX < 0 || imageX >= renderedWidth || imageY < 0 || imageY >= renderedHeight) {
        return null;
      }

      const pixelX = Math.floor((imageX / renderedWidth) * naturalWidth);
      const pixelY = Math.floor((imageY / renderedHeight) * naturalHeight);

      return {
        containerX: Math.round(relX),
        containerY: Math.round(relY),
        containerWidth: Math.round(rect.width),
        containerHeight: Math.round(rect.height),
        containerLeft: Math.round(rect.left),
        containerTop: Math.round(rect.top),
        pixelX: Math.max(0, Math.min(naturalWidth - 1, pixelX)),
        pixelY: Math.max(0, Math.min(naturalHeight - 1, pixelY)),
        naturalWidth,
        naturalHeight,
      };
    },
    [scale, translate],
  );

  useEffect(() => {
    emitHoverSample(null);
    onImageReady?.(null);
  }, [src, emitHoverSample, onImageReady]);

  useEffect(() => {
    const image = imgRef.current;
    if (!image || !onImageReady) {
      return;
    }
    if (!image.complete || image.naturalWidth <= 0 || image.naturalHeight <= 0) {
      return;
    }
    onImageReady(image);
  }, [src, onImageReady]);

  const resetZoom = useCallback(() => {
    setScale(1);
    setTranslate({ x: 0, y: 0 });
  }, []);

  const handleImageLoad = useCallback(() => {
    const image = imgRef.current;
    if (!image) {
      return;
    }
    onImageReady?.(image);
  }, [onImageReady]);

  const handleImageError = useCallback(() => {
    onImageReady?.(null);
  }, [onImageReady]);

  const handleWheel = useCallback(
    (e: WheelEvent<HTMLDivElement>) => {
      e.preventDefault();
      emitHoverSample(null);
      const rect = containerRef.current?.getBoundingClientRect();
      if (!rect) return;

      const mousePos = {
        x: e.clientX - rect.left,
        y: e.clientY - rect.top,
      };

      const newScale = clampScale(scale * (1 - e.deltaY * 0.001));
      const newTranslate = computeZoomTranslate(mousePos, translate, scale, newScale);

      setScale(newScale);
      setTranslate(newTranslate);
    },
    [scale, translate, emitHoverSample],
  );

  const handleMouseDown = useCallback(
    (e: MouseEvent<HTMLDivElement>) => {
      e.preventDefault();
      emitHoverSample(null);
      setIsDragging(true);
      dragStart.current = { x: e.clientX, y: e.clientY };
      translateAtDragStart.current = { ...translate };
    },
    [translate, emitHoverSample],
  );

  const handleMouseMove = useCallback(
    (e: MouseEvent<HTMLDivElement>) => {
      if (isDragging) {
        const dx = e.clientX - dragStart.current.x;
        const dy = e.clientY - dragStart.current.y;
        setTranslate({
          x: translateAtDragStart.current.x + dx,
          y: translateAtDragStart.current.y + dy,
        });
        emitHoverSample(null);
        return;
      }
      emitHoverSample(mapMouseToImagePixel(e.clientX, e.clientY));
    },
    [isDragging, emitHoverSample, mapMouseToImagePixel],
  );

  const handleMouseUp = useCallback(() => {
    setIsDragging(false);
  }, []);

  const handleMouseLeave = useCallback(() => {
    setIsDragging(false);
    emitHoverSample(null);
  }, [emitHoverSample]);

  return (
    <div className={`relative ${className ?? ""}`}>
      <div
        ref={containerRef}
        className="overflow-hidden cursor-grab active:cursor-grabbing"
        onWheel={handleWheel}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseLeave}
      >
        <div
          className="relative w-full"
          style={{
            transform: `translate(${translate.x}px, ${translate.y}px) scale(${scale})`,
            transformOrigin: "0 0",
          }}
        >
          <img
            ref={imgRef}
            src={src}
            alt={alt}
            crossOrigin="anonymous"
            onLoad={handleImageLoad}
            onError={handleImageError}
            draggable={false}
            className="block w-full select-none"
          />
          {overlay ? (
            <div className="pointer-events-none absolute inset-0">
              {overlay}
            </div>
          ) : null}
        </div>
      </div>
      {floatingOverlay ? (
        <div className="pointer-events-none absolute inset-0 z-10">
          {floatingOverlay}
        </div>
      ) : null}
      <button
        type="button"
        onClick={resetZoom}
        className="absolute top-2 right-2 rounded bg-black/30 dark:bg-black/60 px-2 py-1 text-xs text-white hover:bg-black/50 dark:hover:bg-black/80 transition-colors"
      >
        {t("zoom_reset")}
      </button>
    </div>
  );
}
