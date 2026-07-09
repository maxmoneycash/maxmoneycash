import React, { useEffect } from "react";
import { AnimatePresence, motion } from "motion/react";
import { X } from "lucide-react";
import { useInsforgeAuth } from "../contexts/InsforgeAuthContext.jsx";
import { useLoginModal } from "../contexts/LoginModalContext.jsx";
import { LoginCard } from "./LoginCard.jsx";

export function LoginModal() {
  const { isOpen, closeLoginModal } = useLoginModal();
  const { enabled } = useInsforgeAuth();

  // Handle Escape key
  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e) => {
      if (e.key === "Escape") closeLoginModal();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [isOpen, closeLoginModal]);

  if (!enabled) return null;

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          className="fixed inset-0 z-[100] flex items-center justify-center p-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
        >
          {/* Backdrop */}
          <motion.div
            className="absolute inset-0 bg-black/40 dark:bg-black/60"
            onClick={closeLoginModal}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          />

          {/* Card Wrapper */}
          <motion.div
            className="relative w-full max-w-[420px] rounded-2xl border border-oai-gray-200 dark:border-oai-gray-800 bg-white dark:bg-oai-gray-950 shadow-2xl overflow-hidden"
            initial={{ opacity: 0, scale: 0.95, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 10 }}
            transition={{ duration: 0.2 }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Close button */}
            <button
              type="button"
              onClick={closeLoginModal}
              className="absolute right-4 top-4 z-10 text-oai-gray-400 dark:text-oai-gray-500 hover:text-oai-black dark:hover:text-white transition-colors"
            >
              <X className="h-5 w-5" />
            </button>

            {/* LoginCard Form */}
            <LoginCard onSuccess={closeLoginModal} className="p-6 bg-transparent" />
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
