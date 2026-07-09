import { describe, expect, it, vi } from "vitest";
import {
  isLikelyExpiredAccessToken,
  resolveAuthAccessToken,
  resolveAuthAccessTokenWithRetry,
} from "../auth-token";

describe("resolveAuthAccessToken", () => {
  it("falls back to object.accessToken when getAccessToken returns null", async () => {
    const token = await resolveAuthAccessToken({
      accessToken: "fallback-token",
      getAccessToken: async () => null,
    });

    expect(token).toBe("fallback-token");
  });

  it("falls back to object.accessToken when getAccessToken throws", async () => {
    const token = await resolveAuthAccessToken({
      accessToken: "fallback-token",
      getAccessToken: async () => {
        throw new Error("boom");
      },
    });

    expect(token).toBe("fallback-token");
  });

  it("prefers getAccessToken when it returns a valid token", async () => {
    const token = await resolveAuthAccessToken({
      accessToken: "fallback-token",
      getAccessToken: async () => "fresh-token",
    });

    expect(token).toBe("fresh-token");
  });
});

describe("resolveAuthAccessTokenWithRetry", () => {
  it("returns token after transient nulls", async () => {
    let calls = 0;
    const auth = {
      getAccessToken: vi.fn(async () => {
        calls++;
        if (calls < 3) return null;
        return "ok-token";
      }),
    };
    const token = await resolveAuthAccessTokenWithRetry(auth, { maxAttempts: 6, baseDelayMs: 1 });
    expect(token).toBe("ok-token");
    expect(calls).toBe(3);
  });
});

describe("isLikelyExpiredAccessToken", () => {
  function makeJwt(expSeconds: number) {
    const encode = (value: unknown) =>
      Buffer.from(JSON.stringify(value)).toString("base64url").replace(/=/g, "");
    return `${encode({ alg: "HS256", typ: "JWT" })}.${encode({ exp: expSeconds })}.sig`;
  }

  it("returns true for expired jwt", () => {
    const token = makeJwt(Math.floor(Date.now() / 1000) - 60);
    expect(isLikelyExpiredAccessToken(token)).toBe(true);
  });

  it("returns false for valid jwt", () => {
    const token = makeJwt(Math.floor(Date.now() / 1000) + 3600);
    expect(isLikelyExpiredAccessToken(token)).toBe(false);
  });

  it("returns false for non-jwt token", () => {
    expect(isLikelyExpiredAccessToken("opaque-token")).toBe(false);
  });
});
