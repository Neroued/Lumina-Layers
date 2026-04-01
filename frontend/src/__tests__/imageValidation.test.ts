/**
 * 鍗曞厓娴嬭瘯: isValidImageType銆丄CCEPT_IMAGE_FORMATS銆乮18n 閿欒娑堟伅
 * Feature: alpha-channel-support
 *
 * Validates: Requirements 1.1, 1.3, 1.4, 3.1, 3.2, 4.1, 4.2, 5.1
 */
import { describe, it, expect } from "vitest";
import {
  isValidImageType,
  ACCEPT_IMAGE_FORMATS,
} from "../stores/converter";
import { translations } from "../i18n/translations";

const SUPPORTED_MIME_TYPES = [
  "image/jpeg",
  "image/png",
  "image/svg+xml",
  "image/webp",
  "image/heic",
  "image/heif",
] as const;

describe("isValidImageType 鈥?鏀寔鐨勬牸寮忚繑鍥?true", () => {
  it.each(SUPPORTED_MIME_TYPES)("returns true for %s", (mime) => {
    expect(isValidImageType(mime)).toBe(true);
  });
});

describe("isValidImageType 鈥?涓嶆敮鎸佺殑鏍煎紡杩斿洖 false", () => {
  it.each(["application/pdf", "text/plain", "image/bmp", "image/tiff", ""])(
    'returns false for "%s"',
    (mime) => {
      expect(isValidImageType(mime)).toBe(false);
    },
  );
});

const RAW_FILE_NAMES = [
  "photo.dng",
  "photo.cr2",
  "photo.cr3",
  "photo.nef",
  "photo.arw",
  "photo.orf",
  "photo.rw2",
  "photo.raf",
  "photo.pef",
  "photo.srw",
  "photo.raw",
] as const;

describe("RAW files accepted by extension", () => {
  it.each(RAW_FILE_NAMES)("returns true for %s with empty MIME", (fileName) => {
    expect(isValidImageType("", fileName)).toBe(true);
  });
});

describe("ACCEPT_IMAGE_FORMATS 甯搁噺", () => {
  it("鍖呭惈鎵€鏈?6 绉嶆敮鎸佺殑 MIME 绫诲瀷", () => {
    for (const mime of SUPPORTED_MIME_TYPES) {
      expect(ACCEPT_IMAGE_FORMATS).toContain(mime);
    }
  });

  it("鏄€楀彿鍒嗛殧鐨勫瓧绗︿覆", () => {
    const parts = ACCEPT_IMAGE_FORMATS.split(",");
    expect(parts.length).toBeGreaterThanOrEqual(17);
    parts.forEach((part) => {
      expect(part.trim()).not.toBe("");
    });
  });
});

/**
 * i18n 閿欒娑堟伅娴嬭瘯
 * Validates: Requirements 4.1, 4.2
 */
describe("i18n basic_image_format_error 缈昏瘧", () => {
  const entry = translations["basic_image_format_error"];

  it("缈昏瘧 key 瀛樺湪", () => {
    expect(entry).toBeDefined();
  });

  it("涓枃娑堟伅鍖呭惈 WebP 鍜?HEIC", () => {
    expect(entry.zh).toContain("WebP");
    expect(entry.zh).toContain("HEIC");
  });

  it("鑻辨枃娑堟伅鍖呭惈 WebP 鍜?HEIC", () => {
    expect(entry.en).toContain("WebP");
    expect(entry.en).toContain("HEIC");
  });
});

