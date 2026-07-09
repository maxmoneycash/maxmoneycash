import { Dialog } from "@base-ui/react/dialog";
import React from "react";
import { X } from "lucide-react";
import { copy } from "../../lib/copy";
import { formatTokensCompact } from "../../lib/format-tokens";
import { ProviderIcon } from "../../ui/dashboard/components/ProviderIcon";

const ESTIMATED_USD_PER_MILLION_TOKENS = 1.75;

// Model name → provider brand (icon key + bar color). Colors mirror
// PROVIDER_COLORS in UsageOverview so distribution bars read the same
// across the app.
const MODEL_BRANDS = [
  [/claude|fable|opus|sonnet|haiku/, { provider: "CLAUDE", color: "#d97757" }],
  [/gpt|codex|o3|o4/, { provider: "CODEX", color: "#3b82f6" }],
  [/gemini/, { provider: "GEMINI", color: "#2196f3" }],
  [/composer|cursor/, { provider: "CURSOR", color: "#10b981" }],
  [/kimi/, { provider: "KIMI", color: "#a78bfa" }],
  [/mimo/, { provider: "MIMO", color: "#ff6900" }],
  [/copilot/, { provider: "COPILOT", color: "#6366f1" }],
  [/kiro/, { provider: "KIRO", color: "#6366f1" }],
  [/grok/, { provider: "GROK", color: "#f43f5e" }],
  [/deepseek/, { provider: "DEEPSEEK", color: "#4D6BFE" }],
  [/glm/, { provider: "ZCODE", color: "#14b8a6" }],
  [/hy3/, { provider: "WORKBUDDY", color: "#0ea5e9" }],
  [/minimax/, { provider: "MINIMAX", color: "#f59e0b" }],
];

function modelBrand(name) {
  const n = (name || "").toLowerCase();
  const hit = MODEL_BRANDS.find(([re]) => re.test(n));
  return hit ? hit[1] : { provider: "", color: "#9ca3af" };
}

function Stat({ label, value, title, className = "" }) {
  return (
    <div className={`flex min-w-0 flex-col gap-1.5 ${className}`} title={title}>
      <span className="text-[10px] font-semibold uppercase tracking-wider text-oai-gray-400 dark:text-oai-gray-500">
        {label}
      </span>
      <span className="truncate text-2xl font-semibold leading-none tracking-tight text-oai-black dark:text-white tabular-nums">
        {value}
      </span>
    </div>
  );
}

export function CommunityStatsModal({ isOpen, onClose, communityStats }) {
  if (!communityStats || communityStats.status !== "ready") return null;

  const totalTokens = Number(communityStats.tokenFloor) || 0;
  const totalDevs = Number(communityStats.totalEntries) || 0;
  const estimatedGlobalSpend = (totalTokens / 1_000_000) * ESTIMATED_USD_PER_MILLION_TOKENS;

  // Real model-level data from the dedicated endpoint
  const topModels = Array.isArray(communityStats.topModels)
    ? communityStats.topModels.slice(0, 10)
    : [];
  // Bars scale against the leading model so the top row fills its track.
  const maxShare = topModels.reduce((max, m) => Math.max(max, Number(m.share) || 0), 0) || 1;

  return (
    <Dialog.Root open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        {/* Backdrop overlay */}
        <Dialog.Backdrop className="fixed inset-0 z-[100] bg-black/40 backdrop-blur-[2px] transition-opacity duration-200 ease-out data-[ending-style]:opacity-0 data-[starting-style]:opacity-0" />

        <Dialog.Viewport className="fixed inset-0 z-[101] flex items-center justify-center p-4">
          <Dialog.Popup className="relative flex w-full max-w-md flex-col gap-5 max-h-[85vh] overflow-y-auto rounded-2xl bg-white p-6 shadow-2xl ring-1 ring-oai-gray-200 transition-[opacity,transform] duration-[220ms] ease-[cubic-bezier(0.16,1,0.3,1)] data-[ending-style]:translate-y-2 data-[ending-style]:scale-[0.96] data-[ending-style]:opacity-0 data-[starting-style]:translate-y-2 data-[starting-style]:scale-[0.96] data-[starting-style]:opacity-0 dark:bg-oai-gray-900 dark:ring-oai-gray-800">

            {/* Close Button */}
            <Dialog.Close
              className="absolute top-4 right-4 p-1.5 rounded-lg text-oai-gray-400 dark:text-oai-gray-500 hover:bg-oai-gray-100 dark:hover:bg-oai-gray-800 hover:text-oai-black dark:hover:text-white transition-colors cursor-pointer"
              aria-label={copy("shared.dialog.close")}
            >
              <X className="size-4" />
            </Dialog.Close>

            {/* Header */}
            <div className="pr-8">
              <Dialog.Title className="text-lg font-bold tracking-tight text-oai-black dark:text-white">
                {copy("leaderboard.community.modal.title")}
              </Dialog.Title>
              <Dialog.Description className="mt-1 text-xs text-oai-gray-400 dark:text-oai-gray-500">
                {copy("leaderboard.community.modal.description")}
              </Dialog.Description>
            </div>

            {/* Key figures: one quiet band, no boxes */}
            <div className="grid grid-cols-3 divide-x divide-oai-gray-100 border-y border-oai-gray-100 py-4 dark:divide-oai-gray-800/80 dark:border-oai-gray-800/80">
              <Stat
                className="pr-4"
                label={copy("leaderboard.community.modal.total_tokens")}
                value={formatTokensCompact(totalTokens)}
                title={copy("leaderboard.community.modal.tokens_title", {
                  count: totalTokens.toLocaleString("en-US"),
                })}
              />
              <Stat
                className="px-4"
                label={copy("leaderboard.community.modal.active_devs")}
                value={totalDevs.toLocaleString("en-US")}
                title={copy("leaderboard.community.modal.active_devs_detail", {
                  count: totalDevs.toLocaleString("en-US"),
                })}
              />
              <Stat
                className="pl-4"
                label={copy("leaderboard.community.modal.global_spend")}
                value={`$${formatTokensCompact(estimatedGlobalSpend)}`}
                title={copy("leaderboard.community.modal.global_spend_detail", {
                  amount: Math.round(estimatedGlobalSpend).toLocaleString("en-US"),
                })}
              />
            </div>

            {/* Top models: ranked rows with a share bar behind each row */}
            {topModels.length > 0 && (
              <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-oai-gray-400 dark:text-oai-gray-500">
                    {copy("leaderboard.community.modal.top_models")}
                  </span>
                  <span className="text-[10px] text-oai-gray-400 dark:text-oai-gray-500">
                    {copy("leaderboard.community.modal.all_time")}
                  </span>
                </div>

                <div className="flex flex-col gap-0.5">
                  {topModels.map((model, index) => {
                    const brand = modelBrand(model.name);
                    const share = Number(model.share) || 0;
                    return (
                      <div
                        key={model.name}
                        className="relative flex h-9 items-center gap-2.5 overflow-hidden px-2.5"
                      >
                        <div
                          className="absolute inset-y-0 left-0"
                          style={{
                            width: `${Math.max((share / maxShare) * 100, 2)}%`,
                            backgroundColor: `${brand.color}24`,
                          }}
                          aria-hidden="true"
                        />
                        <span className="relative w-4 shrink-0 text-right font-mono text-[11px] text-oai-gray-400 dark:text-oai-gray-500 tabular-nums">
                          {index + 1}
                        </span>
                        <ProviderIcon
                          provider={brand.provider}
                          size={15}
                          className="relative shrink-0 text-oai-gray-500 dark:text-oai-gray-400"
                        />
                        <span
                          className="relative min-w-0 flex-1 truncate text-[13px] font-medium text-oai-gray-700 dark:text-oai-gray-200"
                          title={model.name}
                        >
                          {model.name}
                        </span>
                        <span
                          className="relative shrink-0 text-xs font-semibold text-oai-black dark:text-white tabular-nums"
                          title={copy("leaderboard.community.modal.tokens_title", {
                            count: Number(model.tokens).toLocaleString("en-US"),
                          })}
                        >
                          {formatTokensCompact(model.tokens)}
                        </span>
                        <span className="relative w-11 shrink-0 text-right text-[11px] text-oai-gray-400 dark:text-oai-gray-500 tabular-nums">
                          {share}%
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Note */}
            <p className="text-[11px] leading-normal text-oai-gray-400 dark:text-oai-gray-500">
              {copy("leaderboard.community.modal.note")}
            </p>

          </Dialog.Popup>
        </Dialog.Viewport>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
