import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const TEST_ROOT = join(process.cwd(), "src", "__tests__");
const ALLOWED_FILES = new Set(["resource-url.test.ts"]);
const LOCALHOST_NEEDLE = ["localhost", "8000"].join(":");

function collectTestFiles(dir: string): string[] {
  const items = readdirSync(dir);
  const result: string[] = [];
  for (const item of items) {
    const fullPath = join(dir, item);
    const stat = statSync(fullPath);
    if (stat.isDirectory()) {
      result.push(...collectTestFiles(fullPath));
      continue;
    }
    if (/\.(test|property\.test)\.tsx?$/.test(item)) {
      result.push(fullPath);
    }
  }
  return result;
}

describe("URL localhost guard", () => {
  it("only resource-url.test.ts may contain backend host literals", () => {
    const violations: string[] = [];
    for (const filePath of collectTestFiles(TEST_ROOT)) {
      const fileName = filePath.split(/[\\/]/).pop() ?? "";
      if (ALLOWED_FILES.has(fileName)) {
        continue;
      }
      const text = readFileSync(filePath, "utf8");
      if (text.includes(LOCALHOST_NEEDLE)) {
        violations.push(relative(TEST_ROOT, filePath));
      }
    }
    expect(violations).toEqual([]);
  });
});
