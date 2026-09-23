import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  load: () => 1,
}));

const ROWS = [1, 2, 3];

describe("outer suite", () => {
  const doubled = ROWS.map((row) => row * 2);

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("adds numbers", () => {
    if (doubled.length > 0) {
      expect(1 + 1).toBe(2);
    }
  });

  describe.each([1, 2])("inner suite %s", (n) => {
    it.each(ROWS)("row %s is positive", (row) => {
      expect(row * n).toBeGreaterThan(0);
    });
  });
});

it("stands alone", () => {
  expect(true).toBe(true);
});
