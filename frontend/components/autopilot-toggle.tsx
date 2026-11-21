"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Bot, Hand } from "lucide-react";

import type { AutopilotMode, AutopilotStatus } from "@/lib/types";
import { cn } from "@/lib/utils";
import { workspaceApi } from "@/lib/workspace-api";

/** Fired after the mode changes anywhere, so every view of it stays in step. */
export const AUTOPILOT_EVENT = "shelflife:autopilot";

export function announceAutopilot(status: AutopilotStatus) {
  window.dispatchEvent(new CustomEvent<AutopilotStatus>(AUTOPILOT_EVENT, { detail: status }));
}

const MODES: { id: AutopilotMode; label: string; icon: typeof Bot; title: string }[] = [
  { id: "manual", label: "Manual", icon: Hand, title: "Checks run when you ask." },
  {
    id: "auto",
    label: "Auto",
    icon: Bot,
    title: "Autopilot re-verifies due claims, revisits sources, and corrects affected documents on its own.",
  },
];

export function AutopilotToggle() {
  const [mode, setMode] = useState<AutopilotMode | null>(null);
  const [saving, setSaving] = useState(false);

  const refresh = useCallback(() => {
    workspaceApi
      .autopilot()
      .then((status) => setMode(status.mode))
      .catch(() => setMode(null));
  }, []);

  useEffect(() => {
    refresh();
    const onChange = (event: Event) => setMode((event as CustomEvent<AutopilotStatus>).detail.mode);
    window.addEventListener(AUTOPILOT_EVENT, onChange);
    const timer = window.setInterval(refresh, 15_000);
    return () => {
      window.removeEventListener(AUTOPILOT_EVENT, onChange);
      window.clearInterval(timer);
    };
  }, [refresh]);

  async function choose(next: AutopilotMode) {
    if (next === mode || saving) return;
    setSaving(true);
    setMode(next);
    try {
      announceAutopilot(await workspaceApi.setAutopilot({ mode: next }));
    } catch {
      refresh();
    } finally {
      setSaving(false);
    }
  }

  if (mode === null) return null;

  return (
    <div className="flex items-center gap-2" data-tour="mode-toggle">
      <div role="radiogroup" aria-label="Operating mode" className="flex flex-1 rounded-lg border bg-background p-0.5">
        {MODES.map((item) => {
          const Icon = item.icon;
          const active = mode === item.id;
          return (
            <button
              key={item.id}
              type="button"
              role="radio"
              aria-checked={active}
              title={item.title}
              disabled={saving}
              onClick={() => choose(item.id)}
              className={cn(
                "inline-flex flex-1 items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
                active ? "bg-primary text-primary-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
              )}
            >
              <Icon className="size-3.5" aria-hidden />
              {item.label}
              {item.id === "auto" && active && (
                <span className="size-1.5 rounded-full bg-fresh-line motion-safe:animate-pulse" aria-hidden />
              )}
            </button>
          );
        })}
      </div>
      <Link
        href="/autopilot"
        className="text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
      >
        Activity
      </Link>
    </div>
  );
}
