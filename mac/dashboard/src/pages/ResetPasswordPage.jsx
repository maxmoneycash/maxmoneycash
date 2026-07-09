import React, { useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useInsforgeAuth } from "../contexts/InsforgeAuthContext.jsx";
import { LoginCard } from "../components/LoginCard.jsx";
import { copy } from "../lib/copy";

function firstQueryValue(searchParams, keys) {
  for (const key of keys) {
    const value = searchParams.get(key);
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}

export function ResetPasswordPage() {
  const [searchParams] = useSearchParams();
  const { enabled } = useInsforgeAuth();

  const tokenFromUrl = useMemo(
    () => firstQueryValue(searchParams, ["otp", "token", "reset_token", "insforge_token"]),
    [searchParams],
  );
  const initialEmail = useMemo(() => firstQueryValue(searchParams, ["email"]), [searchParams]);
  const initialCode = useMemo(() => firstQueryValue(searchParams, ["code"]), [searchParams]);

  if (!enabled) {
    return (
      <div className="min-h-screen bg-oai-gray-950 text-oai-white font-oai antialiased dark flex flex-col">
        <header className="border-b border-oai-gray-900 px-4 sm:px-6 py-4">
          <Link to="/login" className="text-sm font-medium text-oai-gray-400 hover:text-white no-underline">
            {copy("reset_password.back_to_sign_in")}
          </Link>
        </header>
        <main className="flex-1 flex items-center justify-center px-4">
          <p className="text-oai-gray-400 text-center max-w-md">{copy("login.cloud_only")}</p>
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-oai-gray-950 text-oai-white font-oai antialiased dark flex flex-col">
      <header className="border-b border-oai-gray-900 px-4 sm:px-6 h-16 flex items-center justify-between">
        <Link
          to="/login"
          className="text-sm font-medium text-oai-gray-400 hover:text-white no-underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oai-brand-500 rounded"
        >
          {copy("reset_password.back_to_sign_in")}
        </Link>
      </header>

      <main className="flex-1 flex items-center justify-center px-4 py-12">
        <div className="w-full max-w-md border border-oai-gray-900 bg-oai-gray-950 rounded-2xl overflow-hidden shadow-2xl">
          <LoginCard
            hideLogo
            initialMode={tokenFromUrl ? "reset_confirm" : "reset_email"}
            tokenFromUrl={tokenFromUrl}
            initialEmail={initialEmail}
            initialCode={initialCode}
          />
        </div>
      </main>
    </div>
  );
}
