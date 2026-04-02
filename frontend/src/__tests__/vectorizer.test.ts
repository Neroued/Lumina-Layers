/**
 * Unit tests for vectorizerStore and buildFileUrl.
 * vectorizerStore 和 buildFileUrl 单元测试。
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { useVectorizerStore } from "../stores/vectorizerStore";
import { buildFileUrl } from "../components/VectorizerPanel";

// Mock apiClient for buildFileUrl tests
vi.mock("../api/client", () => ({
  default: {
    defaults: { baseURL: "/api" },
    post: vi.fn(),
    get: vi.fn(),
  },
}));

// Mock vectorizeImage to avoid real API calls
vi.mock("../api/vectorizer", () => ({
  vectorizeImage: vi.fn(),
}));

// Mock converterStore and widgetStore for send-to-converter tests
vi.mock("../stores/converter", () => ({
  useConverterStore: {
    getState: vi.fn(() => ({
      setImageFile: vi.fn(),
    })),
  },
}));

vi.mock("../stores/widgetStore", () => ({
  useWidgetStore: {
    getState: vi.fn(() => ({
      setActiveTab: vi.fn(),
    })),
  },
}));

function resetStore() {
  useVectorizerStore.getState().reset();
}

describe("vectorizerStore", () => {
  beforeEach(() => {
    resetStore();
  });

  // --- Initial state ---
  it("has correct initial state", () => {
    const state = useVectorizerStore.getState();
    expect(state.imageFile).toBeNull();
    expect(state.imagePreviewUrl).toBeNull();
    expect(state.isProcessing).toBe(false);
    expect(state.error).toBeNull();
    expect(state.result).toBeNull();
    expect(state.abortController).toBeNull();
  });

  it("has default params with all 23 fields", () => {
    const { params } = useVectorizerStore.getState();
    const keys = Object.keys(params);
    expect(keys).toHaveLength(23);
    expect(params.num_colors).toBe(0);
    expect(params.smoothness).toBe(0.5);
    expect(params.detail_level).toBe(-1);
  });

  // --- setParam ---
  it("setParam updates a single parameter", () => {
    useVectorizerStore.getState().setParam("num_colors", 32);
    expect(useVectorizerStore.getState().params.num_colors).toBe(32);
  });

  it("setParam does not affect other parameters", () => {
    const before = { ...useVectorizerStore.getState().params };
    useVectorizerStore.getState().setParam("smoothness", 0.9);
    const after = useVectorizerStore.getState().params;
    expect(after.smoothness).toBe(0.9);
    expect(after.num_colors).toBe(before.num_colors);
    expect(after.detail_level).toBe(before.detail_level);
  });

  // --- cancel ---
  it("cancel sets isProcessing=false and abortController=null", () => {
    // Simulate processing state
    const controller = new AbortController();
    useVectorizerStore.setState({
      isProcessing: true,
      abortController: controller,
    });

    useVectorizerStore.getState().cancel();

    const state = useVectorizerStore.getState();
    expect(state.isProcessing).toBe(false);
    expect(state.abortController).toBeNull();
  });

  it("cancel aborts the active AbortController", () => {
    const controller = new AbortController();
    const abortSpy = vi.spyOn(controller, "abort");
    useVectorizerStore.setState({
      isProcessing: true,
      abortController: controller,
    });

    useVectorizerStore.getState().cancel();
    expect(abortSpy).toHaveBeenCalled();
  });

  it("cancel is a no-op when not processing", () => {
    // Should not throw
    useVectorizerStore.getState().cancel();
    expect(useVectorizerStore.getState().isProcessing).toBe(false);
  });

  // --- reset ---
  it("reset restores all state to defaults", () => {
    // Mutate state
    useVectorizerStore.setState({
      isProcessing: true,
      error: "some error",
      result: {
        status: "ok",
        message: "done",
        svg_url: "/files/test.svg",
        width: 100,
        height: 100,
        num_shapes: 10,
        num_colors: 5,
        palette: ["#ff0000"],
      },
    });
    useVectorizerStore.getState().setParam("num_colors", 128);

    useVectorizerStore.getState().reset();

    const state = useVectorizerStore.getState();
    expect(state.imageFile).toBeNull();
    expect(state.imagePreviewUrl).toBeNull();
    expect(state.isProcessing).toBe(false);
    expect(state.error).toBeNull();
    expect(state.result).toBeNull();
    expect(state.params.num_colors).toBe(0);
    expect(state.params.smoothness).toBe(0.5);
  });

  // --- submit without image ---
  it("submit does nothing when imageFile is null", async () => {
    await useVectorizerStore.getState().submit();
    expect(useVectorizerStore.getState().isProcessing).toBe(false);
  });
});

describe("buildFileUrl", () => {
  it("prepends apiClient baseURL to relative path", () => {
    const url = buildFileUrl("/files/test.svg");
    expect(url).toBe("/api/files/test.svg");
  });

  it("handles empty relative path", () => {
    const url = buildFileUrl("");
    expect(url).toBe("/api");
  });
});
