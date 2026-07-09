import { formatCompactNumber } from "./format";

// Landing-only compact formatter: the community total is past a trillion
// tokens, which the shared formatCompactNumber caps at "B" (e.g. "2211.8B").
export function formatTokensCompact(value) {
  const n = Number(value) || 0;
  if (n >= 1e12) {
    const t = Number((n / 1e12).toFixed(2)).toString();
    return `${t}T`;
  }
  return formatCompactNumber(n);
}
