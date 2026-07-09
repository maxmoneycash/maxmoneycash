import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { CornerDownLeft, Search } from "lucide-react";
import { getNavGroups } from "../../components/Sidebar.jsx";
import { ProviderIcon } from "./ProviderIcon.jsx";
import { getInstalledSkills } from "../../../lib/skills-api";
import { copy } from "../../../lib/copy";
import { cn } from "../../../lib/cn";

const IS_LOCAL_HOST =
  typeof window !== "undefined" &&
  (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1");

// A token tracker's command palette indexes things a skill manager has no concept
// of: the usage/cost views (Usage, Limits, Leaderboard) alongside installed
// skills. Cmd/Ctrl+K from anywhere with the dashboard chrome.
export function CommandPalette() {
  const navigate = useNavigate();
  const reduceMotion = useReducedMotion();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [skills, setSkills] = useState([]);
  const inputRef = useRef(null);
  const listRef = useRef(null);

  // Global open shortcut. Requires the meta/ctrl modifier, so it never collides
  // with plain typing in any input on the page.
  useEffect(() => {
    const onKeyDown = (event) => {
      const isToggle = (event.metaKey || event.ctrlKey) && (event.key === "k" || event.key === "K");
      if (isToggle) {
        event.preventDefault();
        setOpen((prev) => !prev);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  // Load installed skills once per open (local CLI only — no cloud source).
  useEffect(() => {
    if (!open) return;
    setQuery("");
    setActive(0);
    const id = requestAnimationFrame(() => inputRef.current?.focus());
    if (IS_LOCAL_HOST && !skills.length) {
      getInstalledSkills()
        .then((data) => setSkills(data?.skills || []))
        .catch(() => setSkills([]));
    }
    return () => cancelAnimationFrame(id);
  }, [open, skills.length]);

  const items = useMemo(() => {
    const pages = getNavGroups().flatMap((group) =>
      group.items.map((item) => ({
        kind: "page",
        id: `page:${item.id}`,
        label: item.label,
        sub: copy("cmdk.group.pages"),
        Icon: item.icon,
        run: () => navigate(item.to),
      })),
    );
    const skillItems = (skills || []).map((skill) => ({
      kind: "skill",
      id: `skill:${skill.id || skill.directory}`,
      label: skill.name || skill.directory,
      sub: skill.repoOwner && skill.repoName ? `${skill.repoOwner}/${skill.repoName}` : copy("cmdk.group.skills"),
      provider: (skill.targets || [])[0] || "claude",
      run: () => navigate(`/skills?skill=${encodeURIComponent(skill.directory || skill.id)}`),
    }));
    return [...pages, ...skillItems];
  }, [navigate, skills]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (item) =>
        item.label.toLowerCase().includes(q) || String(item.sub || "").toLowerCase().includes(q),
    );
  }, [items, query]);

  useEffect(() => {
    if (active >= filtered.length) setActive(filtered.length ? filtered.length - 1 : 0);
  }, [active, filtered.length]);

  // Keep the active row scrolled into view.
  useEffect(() => {
    if (!open) return;
    const node = listRef.current?.querySelector(`[data-cmdk-index="${active}"]`);
    node?.scrollIntoView({ block: "nearest" });
  }, [active, open]);

  const close = useCallback(() => setOpen(false), []);

  const choose = useCallback(
    (item) => {
      if (!item) return;
      close();
      item.run();
    },
    [close],
  );

  const onInputKeyDown = (event) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((i) => Math.min(i + 1, Math.max(0, filtered.length - 1)));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      choose(filtered[active]);
    } else if (event.key === "Escape") {
      event.preventDefault();
      close();
    }
  };

  const overlayTransition = { duration: reduceMotion ? 0 : 0.12 };
  const panelTransition = reduceMotion
    ? { duration: 0 }
    : { type: "spring", stiffness: 460, damping: 34, mass: 0.6 };

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          className="fixed inset-0 z-[120] flex items-start justify-center px-4 pt-[16vh]"
          initial={reduceMotion ? false : { opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={overlayTransition}
        >
          <button
            type="button"
            aria-label={copy("cmdk.close")}
            onClick={close}
            className="absolute inset-0 cursor-default bg-oai-black/40"
          />
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-label={copy("cmdk.open_aria")}
            initial={reduceMotion ? false : { opacity: 0, y: -8, scale: 0.985 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={reduceMotion ? { opacity: 0 } : { opacity: 0, y: -8, scale: 0.985 }}
            transition={panelTransition}
            className="relative w-full max-w-xl overflow-hidden rounded-2xl border border-oai-gray-200 bg-oai-white shadow-2xl dark:border-oai-gray-800 dark:bg-oai-gray-950"
          >
            <div className="flex items-center gap-2.5 border-b border-oai-gray-200 px-4 dark:border-oai-gray-800">
              <Search className="h-4 w-4 shrink-0 text-oai-gray-400" aria-hidden />
              <input
                ref={inputRef}
                type="text"
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setActive(0);
                }}
                onKeyDown={onInputKeyDown}
                aria-label={copy("cmdk.placeholder")}
                aria-controls="cmdk-listbox"
                aria-activedescendant={filtered[active] ? `cmdk-opt-${active}` : undefined}
                role="combobox"
                aria-expanded="true"
                placeholder={copy("cmdk.placeholder")}
                className="h-12 w-full bg-transparent text-sm text-oai-black placeholder:text-oai-gray-400 focus:outline-none dark:text-white"
              />
            </div>

            <div ref={listRef} id="cmdk-listbox" role="listbox" className="max-h-[min(56vh,22rem)] overflow-y-auto p-1.5">
              {filtered.length === 0 ? (
                <div className="px-3 py-8 text-center text-sm text-oai-gray-500 dark:text-oai-gray-400">
                  {copy("cmdk.empty")}
                </div>
              ) : (
                filtered.map((item, index) => {
                  const selected = index === active;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      role="option"
                      id={`cmdk-opt-${index}`}
                      data-cmdk-index={index}
                      aria-selected={selected}
                      onMouseMove={() => setActive(index)}
                      onClick={() => choose(item)}
                      className={cn(
                        "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm transition-colors",
                        selected
                          ? "bg-oai-gray-100 text-oai-black dark:bg-oai-gray-800/70 dark:text-white"
                          : "text-oai-gray-700 dark:text-oai-gray-200",
                      )}
                    >
                      <span className="flex h-5 w-5 shrink-0 items-center justify-center text-oai-gray-500 dark:text-oai-gray-400">
                        {item.kind === "skill" ? (
                          <ProviderIcon provider={item.provider} size={16} />
                        ) : (
                          <item.Icon className="h-4 w-4" aria-hidden />
                        )}
                      </span>
                      <span className="min-w-0 flex-1 truncate font-medium">{item.label}</span>
                      <span className="shrink-0 truncate text-xs text-oai-gray-400 dark:text-oai-gray-500">
                        {item.sub}
                      </span>
                      {selected ? (
                        <CornerDownLeft className="h-3.5 w-3.5 shrink-0 text-oai-gray-400" aria-hidden />
                      ) : null}
                    </button>
                  );
                })
              )}
            </div>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
