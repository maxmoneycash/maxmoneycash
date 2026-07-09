/**
 * InsForge Edge: anonymous daily heartbeat ingestion.
 *
 * POST { machine_hash, app_version, platform, shell } — sent at most once a
 * day per machine by the CLI/serve runtime (src/lib/telemetry.js). The
 * endpoint is deliberately anonymous (no JWT): machine_hash is a one-way
 * sha256 of the local machine id and cannot be joined to device rows. The
 * `day` bucket is computed server-side (UTC) so clients can't backfill or
 * spread rows. One row per (machine_hash, day); repeats within a day only
 * bump last_seen_at.
 *
 * `shell` upgrade rule: hook-spawned sync processes report "cli" even on
 * machines running the macOS/Windows app (the shell marker env is only set
 * on the app-spawned serve process), so a non-"cli" shell never gets
 * overwritten by a later "cli" heartbeat the same day.
 */
import { createClient } from "npm:@insforge/sdk";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization, apikey",
};

const TABLE = "tokentracker_telemetry_daily";
const MACHINE_HASH_RE = /^[0-9a-f]{64}$/;
const APP_VERSION_RE = /^[0-9A-Za-z.+-]{1,32}$/;
const PLATFORM_RE = /^[a-z0-9]{1,16}$/;
const SHELLS = new Set(["cli", "macos", "windows"]);

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...corsHeaders, "Content-Type": "application/json" },
  });
}

export default async function (req: Request): Promise<Response> {
  if (req.method === "OPTIONS")
    return new Response(null, { status: 204, headers: corsHeaders });
  if (req.method !== "POST") return json({ error: "Method not allowed" }, 405);

  const baseUrl = Deno.env.get("INSFORGE_BASE_URL");
  if (!baseUrl) return json({ error: "server misconfigured" }, 500);
  const serviceRoleKey = Deno.env.get("INSFORGE_SERVICE_ROLE_KEY");
  if (!serviceRoleKey) return json({ error: "server misconfigured" }, 500);
  const incomingApiKey =
    req.headers.get("apikey") ?? req.headers.get("Apikey") ?? req.headers.get("x-api-key") ?? undefined;
  const anonKey =
    Deno.env.get("INSFORGE_ANON_KEY") ?? Deno.env.get("ANON_KEY") ?? incomingApiKey ?? undefined;

  const body = (await req.json().catch(() => ({}))) as Record<string, unknown>;
  const machineHash = typeof body.machine_hash === "string" ? body.machine_hash : "";
  if (!MACHINE_HASH_RE.test(machineHash)) return json({ error: "invalid machine_hash" }, 400);
  const appVersion = typeof body.app_version === "string" ? body.app_version : "";
  if (!APP_VERSION_RE.test(appVersion)) return json({ error: "invalid app_version" }, 400);
  const platform = typeof body.platform === "string" ? body.platform : "";
  if (!PLATFORM_RE.test(platform)) return json({ error: "invalid platform" }, 400);
  const shell = typeof body.shell === "string" ? body.shell : "";
  if (!SHELLS.has(shell)) return json({ error: "invalid shell" }, 400);

  const day = new Date().toISOString().slice(0, 10);
  const nowIso = new Date().toISOString();

  const client = createClient({
    baseUrl,
    edgeFunctionToken: serviceRoleKey,
    anonKey,
    ...(anonKey ? { headers: { apikey: anonKey } } : {}),
  });

  try {
    const { data: existingRows, error: readError } = await client.database
      .from(TABLE)
      .select("machine_hash, shell")
      .eq("machine_hash", machineHash)
      .eq("day", day)
      .limit(1);
    if (readError) return json({ error: readError.message || "read failed" }, 500);

    const existing = Array.isArray(existingRows) && existingRows.length > 0
      ? (existingRows[0] as Record<string, unknown>)
      : null;

    if (existing) {
      const keptShell =
        shell === "cli" && typeof existing.shell === "string" && existing.shell !== "cli"
          ? existing.shell
          : shell;
      const { error: updateError } = await client.database
        .from(TABLE)
        .update({ last_seen_at: nowIso, app_version: appVersion, platform, shell: keptShell })
        .eq("machine_hash", machineHash)
        .eq("day", day);
      if (updateError) return json({ error: updateError.message || "update failed" }, 500);
      return new Response(null, { status: 204, headers: corsHeaders });
    }

    const { error: insertError } = await client.database.from(TABLE).insert([
      {
        machine_hash: machineHash,
        day,
        app_version: appVersion,
        platform,
        shell,
        first_seen_at: nowIso,
        last_seen_at: nowIso,
      },
    ]);
    if (insertError) {
      // PK race with a concurrent same-day heartbeat — the row exists now,
      // which is all this endpoint guarantees.
      if (/unique|duplicate|conflict/i.test(insertError.message || ""))
        return new Response(null, { status: 204, headers: corsHeaders });
      return json({ error: insertError.message || "insert failed" }, 500);
    }
    return new Response(null, { status: 204, headers: corsHeaders });
  } catch (e) {
    return json({ error: (e as Error).message }, 500);
  }
}
