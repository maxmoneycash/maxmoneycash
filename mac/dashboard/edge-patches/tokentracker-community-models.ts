/**
 * InsForge Edge: public community model-level token breakdown.
 *
 * Aggregates per-model token usage across all users for the full lifetime
 * via the same `leaderboard_usage_grouped` RPC used by the refresh function.
 * Public endpoint (no auth required) — data is anonymous aggregate stats.
 *
 * Response:
 * {
 *   top_models: [{ name, tokens, share }],
 *   total_tokens: number,
 *   period: "total",
 *   from: string,
 *   to: string,
 *   generated_at: string
 * }
 */
import { createClient } from "npm:@insforge/sdk";

const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization, apikey",
};

function json(data: unknown, status = 200, extraHeaders: Record<string, string> = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...cors, "Content-Type": "application/json", ...extraHeaders },
  });
}

export default async function (req: Request): Promise<Response> {
  if (req.method === "OPTIONS")
    return new Response(null, { status: 204, headers: cors });

  const baseUrl = Deno.env.get("INSFORGE_BASE_URL")!;
  const incomingApiKey =
    req.headers.get("apikey") ??
    req.headers.get("Apikey") ??
    req.headers.get("x-api-key") ??
    undefined;
  const anonKey =
    Deno.env.get("INSFORGE_ANON_KEY") ??
    Deno.env.get("ANON_KEY") ??
    incomingApiKey ??
    undefined;
  const serviceRoleKey = Deno.env.get("INSFORGE_SERVICE_ROLE_KEY");
  if (!serviceRoleKey) return json({ error: "server misconfigured" }, 500);

  const client = createClient({
    baseUrl,
    edgeFunctionToken: serviceRoleKey,
    anonKey,
    ...(anonKey ? { headers: { apikey: anonKey } } : {}),
  });

  // Full lifetime — matches refresh function's "total" period (1970-01-01 to today).
  const now = new Date();
  const from_day = "1970-01-01";
  const end = new Date(
    Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()),
  );
  const to_day = end.toISOString().slice(0, 10);

  const rangeStart = `${from_day}T00:00:00Z`;
  const nextDay = new Date(to_day + "T00:00:00Z");
  nextDay.setUTCDate(nextDay.getUTCDate() + 1);
  const rangeEnd = nextDay.toISOString();

  try {
    const { data: grouped, error } = await client.database.rpc(
      "leaderboard_usage_grouped",
      { p_from: rangeStart, p_to: rangeEnd },
    );
    if (error) return json({ error: error.message }, 500);

    // Aggregate by model name across all users.
    const modelMap = new Map<string, number>();
    for (const row of (grouped || []) as Array<{
      model: string;
      total_tokens: number;
    }>) {
      const m = (row.model || "").trim();
      if (!m || m.toLowerCase() === "auto") continue;
      modelMap.set(
        m,
        (modelMap.get(m) || 0) + (Number(row.total_tokens) || 0),
      );
    }

    const totalTokens = [...modelMap.values()].reduce((s, v) => s + v, 0);
    const topModels = [...modelMap.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 15)
      .map(([name, tokens]) => ({
        name,
        tokens,
        share:
          totalTokens > 0
            ? Math.round((tokens / totalTokens) * 1000) / 10
            : 0,
      }));

    return json(
      {
        top_models: topModels,
        total_tokens: totalTokens,
        period: "total",
        from: from_day,
        to: to_day,
        generated_at: new Date().toISOString(),
      },
      200,
      // All-time cumulative stats move slowly; don't rerun the full-lifetime
      // aggregation for every anonymous landing-page hit.
      { "Cache-Control": "public, max-age=300" },
    );
  } catch (e) {
    return json({ error: String((e as Error).message || e) }, 500);
  }
}
