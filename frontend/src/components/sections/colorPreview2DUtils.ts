/**
 * Convert a click on an <img> with object-contain to image pixel coordinates.
 * 将 object-contain 模式下 <img> 上的点击转换为图像像素坐标。
 *
 * @param event - The mouse event on the image element.
 * @param imgEl - The <img> DOM element.
 * @param naturalW - The intrinsic image width in pixels.
 * @param naturalH - The intrinsic image height in pixels.
 * @returns [pixelX, pixelY] in image space, or null if click is in letterbox padding.
 */
export function imgClickToPixel(
  event: React.MouseEvent<HTMLImageElement>,
  imgEl: HTMLImageElement,
  naturalW: number,
  naturalH: number,
): [number, number] | null {
  const rect = imgEl.getBoundingClientRect();
  const clientW = rect.width;
  const clientH = rect.height;

  if (naturalW <= 0 || naturalH <= 0 || clientW <= 0 || clientH <= 0) {
    return null;
  }

  const scale = Math.min(clientW / naturalW, clientH / naturalH);
  const renderedW = naturalW * scale;
  const renderedH = naturalH * scale;
  const offsetX = (clientW - renderedW) / 2;
  const offsetY = (clientH - renderedH) / 2;

  const relX = event.clientX - rect.left - offsetX;
  const relY = event.clientY - rect.top - offsetY;

  if (relX < 0 || relX >= renderedW || relY < 0 || relY >= renderedH) {
    return null;
  }

  const pixelX = Math.floor((relX / renderedW) * naturalW);
  const pixelY = Math.floor((relY / renderedH) * naturalH);

  return [
    Math.max(0, Math.min(naturalW - 1, pixelX)),
    Math.max(0, Math.min(naturalH - 1, pixelY)),
  ];
}

/**
 * Read the color of a pixel from an image via an off-screen canvas.
 * 通过离屏 canvas 读取图像某像素的颜色。
 *
 * @param imgEl - A loaded <img> element.
 * @param x - Pixel X coordinate.
 * @param y - Pixel Y coordinate.
 * @returns Hex string without '#' (e.g. "ff0000"), or null on failure.
 */
export function readPixelColor(
  imgEl: HTMLImageElement,
  x: number,
  y: number,
): string | null {
  try {
    const canvas = document.createElement('canvas');
    canvas.width = imgEl.naturalWidth;
    canvas.height = imgEl.naturalHeight;
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    if (!ctx) return null;
    ctx.drawImage(imgEl, 0, 0);
    const [r, g, b] = ctx.getImageData(x, y, 1, 1).data;
    return [r, g, b].map((c) => c.toString(16).padStart(2, '0')).join('');
  } catch {
    return null;
  }
}
