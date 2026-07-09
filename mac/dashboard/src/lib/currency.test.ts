import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  CURRENCY_USD,
  DEFAULT_RATES,
  SUPPORTED_CURRENCY_CODES,
  applyCurrency,
  getCurrencySymbol,
  getInitialCurrency,
  getInitialExchangeRates,
  getRateFor,
  getSupportedCurrencies,
  isValidRate,
  normalizeCurrency,
  persistCurrency,
  persistExchangeRates,
} from "./currency";

beforeEach(() => {
  try {
    window.localStorage.clear();
  } catch (_e) {
    // localStorage unavailable (jsdom edge case); tests handle defaults.
  }
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("normalizeCurrency", () => {
  it("accepts all supported codes (case-insensitive)", () => {
    for (const code of SUPPORTED_CURRENCY_CODES) {
      expect(normalizeCurrency(code)).toBe(code);
      expect(normalizeCurrency(code.toLowerCase())).toBe(code);
      expect(normalizeCurrency(` ${code} `)).toBe(code);
    }
  });

  it("falls back to USD for unsupported / invalid input", () => {
    expect(normalizeCurrency("BTC")).toBe(CURRENCY_USD);
    expect(normalizeCurrency("")).toBe(CURRENCY_USD);
    expect(normalizeCurrency(null)).toBe(CURRENCY_USD);
    expect(normalizeCurrency(undefined)).toBe(CURRENCY_USD);
    expect(normalizeCurrency(42)).toBe(CURRENCY_USD);
  });
});

describe("isValidRate", () => {
  it("accepts positive finite numbers", () => {
    expect(isValidRate(7.2)).toBe(true);
    expect(isValidRate(0.001)).toBe(true);
  });

  it("rejects zero / negative / NaN / Infinity / non-numbers", () => {
    expect(isValidRate(0)).toBe(false);
    expect(isValidRate(-1)).toBe(false);
    expect(isValidRate(NaN)).toBe(false);
    expect(isValidRate(Infinity)).toBe(false);
    expect(isValidRate("7.2")).toBe(false);
    expect(isValidRate(null)).toBe(false);
  });
});

describe("getCurrencySymbol", () => {
  it("returns the right symbol for each supported code", () => {
    expect(getCurrencySymbol("USD")).toBe("$");
    expect(getCurrencySymbol("EUR")).toBe("€");
    expect(getCurrencySymbol("GBP")).toBe("£");
    expect(getCurrencySymbol("CNY")).toBe("¥");
    expect(getCurrencySymbol("JPY")).toBe("¥");
    expect(getCurrencySymbol("HKD")).toBe("HK$");
  });

  it("falls back to $ for unknown / invalid codes", () => {
    expect(getCurrencySymbol("BTC")).toBe("$");
    expect(getCurrencySymbol(null)).toBe("$");
    expect(getCurrencySymbol(undefined)).toBe("$");
    expect(getCurrencySymbol(42 as any)).toBe("$");
  });
});

describe("getSupportedCurrencies", () => {
  it("returns 6 entries with code/symbol/labelKey", () => {
    const list = getSupportedCurrencies();
    expect(list).toHaveLength(6);
    for (const item of list) {
      expect(typeof item.code).toBe("string");
      expect(typeof item.symbol).toBe("string");
      expect(item.labelKey.startsWith("settings.appearance.currency.opt.")).toBe(true);
    }
  });
});

describe("getRateFor", () => {
  it("returns 1 for USD regardless of input rates", () => {
    expect(getRateFor({ USD: 1, EUR: 0.92 }, "USD")).toBe(1);
    expect(getRateFor(null, "USD")).toBe(1);
  });

  it("returns the mapped rate when available", () => {
    expect(getRateFor({ EUR: 0.93 }, "EUR")).toBe(0.93);
  });

  it("falls back to DEFAULT_RATES when missing", () => {
    expect(getRateFor({}, "JPY")).toBe(DEFAULT_RATES.JPY);
    expect(getRateFor(null, "GBP")).toBe(DEFAULT_RATES.GBP);
  });
});

describe("applyCurrency", () => {
  it("returns USD unchanged", () => {
    expect(applyCurrency(100, "USD", { EUR: 0.92 })).toEqual({ value: 100, symbol: "$" });
  });

  it("multiplies by mapped rate", () => {
    const r = applyCurrency(10, "EUR", { EUR: 0.93 });
    expect(r.symbol).toBe("€");
    expect(r.value).toBeCloseTo(9.3, 5);
  });

  it("falls back to bundled default when rate missing", () => {
    const r = applyCurrency(10, "JPY", {});
    expect(r.symbol).toBe("¥");
    expect(r.value).toBeCloseTo(10 * DEFAULT_RATES.JPY, 5);
  });
});

describe("persist/getInitial currency", () => {
  it("round-trips supported codes", () => {
    persistCurrency("EUR");
    expect(getInitialCurrency()).toBe("EUR");
    persistCurrency("usd");
    expect(getInitialCurrency()).toBe("USD");
  });

  it("defaults to USD for empty / unsupported persisted value", () => {
    expect(getInitialCurrency()).toBe("USD");
    window.localStorage.setItem("tokentracker-currency", "weird");
    expect(getInitialCurrency()).toBe("USD");
  });
});

describe("persist/getInitial exchange rates", () => {
  it("returns bundled defaults when nothing persisted", () => {
    const state = getInitialExchangeRates();
    expect(state.source).toBe("default");
    expect(state.fetchedAt).toBeNull();
    expect(state.rates.USD).toBe(1);
    expect(state.rates.CNY).toBe(DEFAULT_RATES.CNY);
  });

  it("round-trips persisted rates", () => {
    persistExchangeRates({
      rates: { USD: 1, EUR: 0.9, CNY: 6.8 },
      source: "fetched",
      fetchedAt: 1_700_000_000_000,
    });
    const state = getInitialExchangeRates();
    expect(state.rates.EUR).toBe(0.9);
    expect(state.rates.CNY).toBe(6.8);
    expect(state.source).toBe("fetched");
    expect(state.fetchedAt).toBe(1_700_000_000_000);
  });

  it("recovers from corrupt persisted blob", () => {
    window.localStorage.setItem("tokentracker-exchange-rates", "{not json");
    const state = getInitialExchangeRates();
    expect(state.source).toBe("default");
    expect(state.rates.CNY).toBe(DEFAULT_RATES.CNY);
  });
});
