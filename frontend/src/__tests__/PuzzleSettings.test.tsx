import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import PuzzleSettings from "../components/sections/PuzzleSettings";
import { useConverterStore } from "../stores/converter";

vi.mock("../i18n/context", () => ({
  useI18n: () => ({ t: (key: string) => key, lang: "en" as const }),
}));

describe("PuzzleSettings", () => {
  beforeEach(() => {
    useConverterStore.setState({
      puzzleEnabled: true,
      puzzleStyle: "regular",
      puzzleSizingMode: "grid",
      pieceWidthMm: 20,
      pieceHeightMm: 20,
      puzzleRows: 4,
      puzzleCols: 5,
      targetPieceCount: 24,
      connectorStyle: "classic",
      labelsEnabled: false,
      engraveBackLabels: false,
      irregularityStrength: 0.35,
      minNeckWidthMm: 1.2,
      puzzleWarnings: [],
      puzzleResolvedRows: 4,
      puzzleResolvedCols: 5,
      puzzleResolvedPieceCount: 18,
      puzzleDerivedPieceWidthMm: 16.5,
      puzzleDerivedPieceHeightMm: 18.2,
      batchMode: false,
    });
  });

  it("shows requested and resolved puzzle summary values separately", () => {
    render(<PuzzleSettings />);

    expect(screen.getByText("puzzle_summary_requested_grid")).toBeInTheDocument();
    expect(screen.getByText("puzzle_summary_requested_piece_count")).toBeInTheDocument();
    expect(screen.getByText("20")).toBeInTheDocument();
    expect(screen.getAllByText("5 × 4")).toHaveLength(2);
    expect(screen.getByText("18")).toBeInTheDocument();
    expect(screen.getByText("16.5 × 18.2 mm")).toBeInTheDocument();
  });

  it("shows that back-label engraving is currently unavailable", () => {
    render(<PuzzleSettings />);

    expect(
      screen.getByText("puzzle_back_engrave_unavailable_hint"),
    ).toBeInTheDocument();
  });
});
