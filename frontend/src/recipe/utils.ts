/**
 * Recipe utility functions: hashing, base64 conversion, asset building.
 * 配方工具函数：哈希、base64 转换、asset 构建。
 */

import type { AssetEntry } from "./types";

/**
 * Compute SHA-256 hex digest of an ArrayBuffer using Web Crypto API.
 * 使用 Web Crypto API 计算 ArrayBuffer 的 SHA-256 十六进制摘要。
 */
export async function sha256Hex(data: ArrayBuffer): Promise<string> {
  const hashBuffer = await crypto.subtle.digest("SHA-256", data);
  const bytes = new Uint8Array(hashBuffer);
  let hex = "";
  for (let i = 0; i < bytes.length; i++) {
    hex += bytes[i].toString(16).padStart(2, "0");
  }
  return hex;
}

/**
 * Convert a File/Blob to a base64-encoded string (no data-URI prefix).
 * 将 File/Blob 转换为 base64 编码字符串（不含 data-URI 前缀）。
 */
export function fileToBase64(file: File | Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      // Strip "data:...;base64," prefix
      const idx = result.indexOf(",");
      resolve(idx >= 0 ? result.slice(idx + 1) : result);
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

/**
 * Convert a base64-encoded string back to a File object.
 * 将 base64 编码字符串还原为 File 对象。
 */
export function base64ToFile(
  b64: string,
  filename: string,
  mimeType: string,
): File {
  const binaryStr = atob(b64);
  const bytes = new Uint8Array(binaryStr.length);
  for (let i = 0; i < binaryStr.length; i++) {
    bytes[i] = binaryStr.charCodeAt(i);
  }
  return new File([bytes], filename, { type: mimeType });
}

/**
 * Build an AssetEntry from a File, computing sha256 and base64 payload.
 * 从 File 构建 AssetEntry，计算 sha256 和 base64 负载。
 */
export async function buildAssetEntry(file: File): Promise<AssetEntry> {
  const buffer = await file.arrayBuffer();
  const [hash, payload] = await Promise.all([
    sha256Hex(buffer),
    fileToBase64(file),
  ]);
  return {
    filename: file.name,
    mime_type: file.type || "application/octet-stream",
    byte_size: file.size,
    sha256: hash,
    encoding: "base64",
    payload_b64: payload,
  };
}

/**
 * Compute SHA-256 hex digest of a UTF-8 string.
 * 计算 UTF-8 字符串的 SHA-256 十六进制摘要。
 */
export async function sha256String(str: string): Promise<string> {
  const encoder = new TextEncoder();
  return sha256Hex(encoder.encode(str).buffer as ArrayBuffer);
}
