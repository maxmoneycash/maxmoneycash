import { render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TokenGalaxy } from "./TokenGalaxy";

vi.mock("three", () => ({
  WebGLRenderer: vi.fn(() => {
    throw new Error("webgl unavailable");
  }),
}));

describe("TokenGalaxy", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("re-renders the static fallback when WebGL renderer creation fails", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});

    const { container } = render(<TokenGalaxy mode="full" progressRef={{ current: 0 }} />);

    await waitFor(() => {
      expect(container.firstElementChild).toHaveAttribute("data-mode", "static");
    });
  });
});
