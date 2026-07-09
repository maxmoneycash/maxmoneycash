/**
 * InsForge Edge: list the signed-in user's active devices with per-device
 * usage totals for [from, to]. Powers the dashboard device filter dropdown
 * and the per-device usage card. Reuses account_usage_grouped (no DB change):
 * one RPC per device with p_device_ids=[id] gives that device's isolated sum.
 *
 * Auth: HS256 JWT_SECRET signature verification (same template as
 * tokentracker-account-summary). InsForge does NOT validate JWTs at the
 * gateway, so we verify the signature ourselves before returning per-user data.
 */
import { createClient } from "npm:@insforge/sdk";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization, apikey",
};

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...corsHeaders, "Content-Type": "application/json" },
  });
}

function b64urlToBytes(s: string): Uint8Array {
  const b64 = s.replace(/-/g, "+").replace(/_/g, "/");
  const pad = (4 - (b64.length % 4)) % 4;
  const raw = atob(b64 + "=".repeat(pad));
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

async function verifiedUserIdFromJwt(authHeader: string | null): Promise<string | null> {
  if (!authHeader) return null;
  const token = authHeader.replace(/^Bearer\s+/i, "").trim();
  if (!token) return null;
  const secret = Deno.env.get("JWT_SECRET");
  if (!secret) return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    const key = await crypto.subtle.importKey(
      "raw",
      new TextEncoder().encode(secret),
      { name: "HMAC", hash: "SHA-256" },
      false,
      ["verify"],
    );
    const data = new TextEncoder().encode(`${parts[0]}.${parts[1]}`);
    const sig = b64urlToBytes(parts[2]);
    const ok = await crypto.subtle.verify("HMAC", key, sig, data);
    if (!ok) return null;
    const payload = JSON.parse(new TextDecoder().decode(b64urlToBytes(parts[1]))) as Record<string, unknown>;
    if (typeof payload.exp === "number" && Date.now() / 1000 > payload.exp) return null;
    const sub = payload.sub;
    if (typeof sub === "string" && sub.length > 0) return sub;
    const uid = payload.user_id;
    if (typeof uid === "string" && uid.length > 0) return uid;
  } catch { /* ignore */ }
  return null;
}

interface DeviceRow {
  id: string;
  device_name: string | null;
  platform: string | null;
  created_at: string | null;
}

interface GroupedRow {
  total_tokens: number | null;
}

async function sumDeviceTokens(
  client: ReturnType<typeof createClient>,
  userId: string,
  deviceId: string,
  fromIso: string,
  toIso: string,
  tz: string | null,
  tzOffsetMinutes: number | null,
): Promise<number> {
  const { data, error } = await client.database.rpc("account_usage_grouped", {
    p_user_id: userId,
    p_device_ids: [deviceId],
    p_from: fromIso,
    p_to: toIso,
    p_trunc: "day",
    p_tz: tz,
    p_offset_min: tzOffsetMinutes,
  });
  if (error) {
    console.error(`account-devices: usage sum failed for device ${deviceId}: ${error.message}`);
    return 0;
  }
  const rows = (Array.isArray(data) ? data : []) as GroupedRow[];
  let sum = 0;
  for (const r of rows) sum += Number(r.total_tokens) || 0;
  return sum;
}

export default async function (req: Request): Promise<Response> {
  if (req.method === "OPTIONS")
    return new Response(null, { status: 204, headers: corsHeaders });
  if (req.method !== "GET") return json({ error: "Method not allowed" }, 405);

  const url = new URL(req.url);
  const from = url.searchParams.get("from") || "";
  const to = url.searchParams.get("to") || "";
  if (!from || !to) return json({ error: "Missing from/to" }, 400);
  const tz = url.searchParams.get("tz") || null;
  const tzOffsetRaw = url.searchParams.get("tz_offset_minutes");
  const tzOffsetMinutes = tzOffsetRaw != null && tzOffsetRaw !== "" ? Number(tzOffsetRaw) : null;

  const baseUrl = Deno.env.get("INSFORGE_BASE_URL");
  if (!baseUrl) return json({ error: "server misconfigured" }, 500);
  const incomingApiKey =
    req.headers.get("apikey") ?? req.headers.get("Apikey") ?? req.headers.get("x-api-key") ?? undefined;
  const anonKey =
    Deno.env.get("INSFORGE_ANON_KEY") ?? Deno.env.get("ANON_KEY") ?? incomingApiKey ?? undefined;
  const serviceRoleKey = Deno.env.get("INSFORGE_SERVICE_ROLE_KEY");
  if (!serviceRoleKey) return json({ error: "server misconfigured" }, 500);

  const client = createClient({
    baseUrl,
    edgeFunctionToken: serviceRoleKey,
    anonKey,
    ...(anonKey ? { headers: { apikey: anonKey } } : {}),
  });

  const userId = await verifiedUserIdFromJwt(req.headers.get("Authorization"));
  if (!userId) return json({ error: "Unauthorized" }, 401);

  let devices: DeviceRow[];
  try {
    const { data, error } = await client.database
      .from("tokentracker_devices")
      .select("id, device_name, platform, created_at")
      .eq("user_id", userId)
      .is("revoked_at", null);
    if (error) throw new Error(error.message);
    devices = (data ?? []) as DeviceRow[];
  } catch (e) {
    return json({ error: (e as Error).message }, 500);
  }

  // Widen the UTC window ±1 day so TZ-shifted edge hours are captured (mirrors
  // account-summary). The RPC handles per-device isolation + source-class
  // dedup; a single-device query needs no extra dedup.
  const startDate = new Date(`${from}T00:00:00Z`);
  startDate.setUTCDate(startDate.getUTCDate() - 1);
  const endDate = new Date(`${to}T00:00:00Z`);
  endDate.setUTCDate(endDate.getUTCDate() + 2);
  const rangeStart = startDate.toISOString();
  const rangeEnd = endDate.toISOString();

  // Per-device RPC errors are already degraded to 0 inside sumDeviceTokens;
  // this catch is a last-resort guard for unexpected (synchronous) failures.
  let withTotals: Array<DeviceRow & { total_tokens: number }>;
  try {
    withTotals = await Promise.all(
      devices.map(async (d) => ({
        ...d,
        total_tokens: await sumDeviceTokens(client, userId, d.id, rangeStart, rangeEnd, tz, tzOffsetMinutes),
      })),
    );
  } catch (e) {
    return json({ error: (e as Error).message }, 500);
  }

  withTotals.sort((a, b) => b.total_tokens - a.total_tokens);
  return json({ from, to, devices: withTotals });
}
