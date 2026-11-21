"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { ChevronLeft, ChevronRight, Compass, LoaderCircle, Pause, Play, X } from "lucide-react";

import { announceAutopilot } from "@/components/autopilot-toggle";
import { readingTime, targetSelector, TOUR_STEPS, type TourAction } from "@/lib/tour-steps";
import { workspaceApi } from "@/lib/workspace-api";

const STORAGE_KEY = "shelflife-tour";
const POPOVER_WIDTH = 340;
const GAP = 12;

type Phase = "idle" | "preparing" | "showing" | "finished";

interface Box {
  top: number;
  left: number;
  width: number;
  height: number;
}

function readStored(): { step: number; done: boolean } | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as { step: number; done: boolean }) : null;
  } catch {
    return null;
  }
}

function store(value: { step: number; done: boolean }) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  } catch {
    // Storage can be unavailable; the tour still works for this visit.
  }
}

const sleep = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));

/**
 * The first matching element that is actually on screen. Some anchors exist twice,
 * such as the mode switch in the desktop sidebar and in the phone menu, and only one
 * of them is visible at a time.
 */
function findVisible(selector: string): Element | null {
  for (const element of document.querySelectorAll(selector)) {
    if (element.getClientRects().length > 0) return element;
  }
  return null;
}

async function waitForElement(selector: string, timeout: number, cancelled: () => boolean): Promise<Element | null> {
  const started = Date.now();
  while (Date.now() - started < timeout && !cancelled()) {
    const element = findVisible(selector);
    if (element) return element;
    await sleep(150);
  }
  return null;
}

function place(target: Box | null): { top: number; left: number } {
  const width = Math.min(POPOVER_WIDTH, window.innerWidth - 32);
  if (!target) {
    return { top: window.innerHeight / 2 - 110, left: window.innerWidth / 2 - width / 2 };
  }
  const height = 240;
  const centred = Math.min(Math.max(16, target.left + target.width / 2 - width / 2), window.innerWidth - width - 16);
  const besideTop = Math.min(Math.max(16, target.top), window.innerHeight - height - 16);
  const below = target.top + target.height + GAP;
  if (below + height < window.innerHeight) return { top: below, left: centred };
  if (target.top - height - GAP >= 16) return { top: target.top - height - GAP, left: centred };
  // A tall target leaves no room above or below: sit beside it, so it stays readable.
  if (target.left - width - GAP >= 16) return { top: besideTop, left: target.left - width - GAP };
  if (target.left + target.width + GAP + width <= window.innerWidth - 16) {
    return { top: besideTop, left: target.left + target.width + GAP };
  }
  return { top: window.innerHeight - height - 16, left: centred };
}

/**
 * The automatic walkthrough. It drives the real app step by step, pointing at each
 * feature with an explanation, and moves on by itself. It starts on a first visit
 * and can be paused, stepped through, closed, or replayed.
 */
export function GuidedTour() {
  const router = useRouter();
  const pathname = usePathname();
  const [index, setIndex] = useState(0);
  const [phase, setPhase] = useState<Phase>("idle");
  const [paused, setPaused] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [box, setBox] = useState<Box | null>(null);
  const [remaining, setRemaining] = useState(0);
  const run = useRef(0);
  // The preparing step waits for navigation to land, so it reads the path through a ref.
  const pathRef = useRef(pathname);
  useEffect(() => {
    pathRef.current = pathname;
  }, [pathname]);

  const step = TOUR_STEPS[index];

  // Start on a first visit, or resume where a reload interrupted it.
  useEffect(() => {
    const saved = readStored();
    if (saved?.done) {
      Promise.resolve().then(() => setPhase("finished"));
      return;
    }
    Promise.resolve().then(() => {
      setIndex(Math.min(saved?.step ?? 0, TOUR_STEPS.length - 1));
      setPhase("preparing");
    });
  }, []);

  const finish = useCallback(() => {
    run.current += 1;
    store({ step: 0, done: true });
    setPhase("finished");
    setBox(null);
  }, []);

  const goTo = useCallback(
    (next: number) => {
      run.current += 1;
      if (next >= TOUR_STEPS.length) {
        finish();
        return;
      }
      const bounded = Math.max(0, next);
      store({ step: bounded, done: false });
      setIndex(bounded);
      setBox(null);
      setPhase("preparing");
    },
    [finish],
  );

  // Prepare a step: navigate, run its actions, then find its target.
  useEffect(() => {
    if (phase !== "preparing" || !step) return;
    const token = ++run.current;
    const cancelled = () => run.current !== token;

    async function act(action: TourAction) {
      if ("pause" in action) return sleep(action.pause);
      if ("autopilot" in action) {
        try {
          announceAutopilot(await workspaceApi.setAutopilot({ mode: action.autopilot }));
        } catch {
          // The walkthrough goes on without it.
        }
        return;
      }
      if ("waitFor" in action) {
        await waitForElement(targetSelector(action.waitFor), action.timeout ?? 15000, cancelled);
        return;
      }
      const element = await waitForElement(targetSelector(action.click), action.optional ? 2500 : 12000, cancelled);
      if (element instanceof HTMLElement) {
        element.scrollIntoView({ block: "center", behavior: "smooth" });
        await sleep(250);
        element.click();
      }
    }

    (async () => {
      if (step.route && pathRef.current !== step.route) {
        router.push(step.route);
        const started = Date.now();
        while (pathRef.current !== step.route && Date.now() - started < 10000 && !cancelled()) await sleep(100);
        await sleep(400);
      }
      for (const action of step.actions ?? []) {
        if (cancelled()) return;
        await act(action);
      }
      if (cancelled()) return;
      if (step.target) {
        const element = await waitForElement(targetSelector(step.target), 8000, cancelled);
        if (cancelled()) return;
        if (element instanceof HTMLElement) {
          element.scrollIntoView({ block: "center", behavior: "smooth" });
          await sleep(450);
        }
      } else {
        window.scrollTo({ top: 0, behavior: "smooth" });
      }
      if (cancelled()) return;
      setRemaining(readingTime(step));
      setPhase("showing");
    })();
  }, [phase, step, router]);

  // Keep the highlight on its target as the page scrolls, resizes or re-renders.
  useLayoutEffect(() => {
    if (phase !== "showing" || !step?.target) return;
    const selector = targetSelector(step.target);
    const measure = () => {
      const element = findVisible(selector);
      if (!element) {
        setBox(null);
        return;
      }
      const rect = element.getBoundingClientRect();
      const top = Math.max(rect.top, 8);
      const bottom = Math.min(rect.bottom, window.innerHeight - 8);
      setBox({ top, left: rect.left, width: rect.width, height: Math.max(bottom - top, 24) });
    };
    measure();
    const timer = window.setInterval(measure, 250);
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [phase, step]);

  // Count down and move on, unless paused or the pointer rests on the explanation.
  useEffect(() => {
    if (phase !== "showing" || paused || hovered) return;
    if (remaining <= 0) {
      Promise.resolve().then(() => goTo(index + 1));
      return;
    }
    const timer = window.setTimeout(() => setRemaining((value) => value - 100), 100);
    return () => window.clearTimeout(timer);
  }, [phase, paused, hovered, remaining, index, goTo]);

  if (phase === "idle" || phase === "finished") {
    return (
      <button
        type="button"
        onClick={() => {
          setPaused(false);
          goTo(0);
        }}
        className="fixed right-5 bottom-5 z-[60] inline-flex items-center gap-2 rounded-full border border-brand/30 bg-card px-4 py-2.5 text-xs font-semibold shadow-lg outline-none hover:border-brand/60 hover:bg-brand-soft focus-visible:ring-2 focus-visible:ring-ring"
      >
        <Compass className="size-4 text-brand" aria-hidden />
        {phase === "finished" ? "Replay tour" : "Take the tour"}
      </button>
    );
  }

  const total = TOUR_STEPS.length;
  const position = place(phase === "showing" ? box : null);
  const width = Math.min(POPOVER_WIDTH, typeof window === "undefined" ? POPOVER_WIDTH : window.innerWidth - 32);
  const progress = phase === "showing" ? 1 - remaining / readingTime(step) : 0;

  return (
    <>
      {phase === "showing" && box && (
        <div
          aria-hidden
          className="pointer-events-none fixed z-[55] rounded-lg transition-all duration-300"
          style={{
            top: box.top - 6,
            left: box.left - 6,
            width: box.width + 12,
            height: box.height + 12,
            boxShadow: "0 0 0 3px var(--brand), 0 0 0 9999px color-mix(in oklch, var(--foreground) 14%, transparent)",
          }}
        />
      )}
      <div
        role="dialog"
        aria-live="polite"
        aria-label={`Tour step ${index + 1} of ${total}: ${step.title}`}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        className="fixed z-[60] flex flex-col gap-3 rounded-2xl border border-brand/40 bg-popover p-5 shadow-2xl transition-[top,left] duration-300"
        style={{ top: position.top, left: position.left, width }}
      >
        <div className="flex items-start justify-between gap-2">
          <p className="text-[0.7rem] font-semibold tracking-[0.12em] text-brand uppercase">
            Step {index + 1} of {total}
          </p>
          <button type="button" onClick={finish} aria-label="End the tour" className="-mt-1 -mr-1 rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground">
            <X className="size-4" aria-hidden />
          </button>
        </div>
        <div className="flex flex-col gap-1.5">
          <h2 className="text-base leading-6 font-semibold tracking-tight">{step.title}</h2>
          {phase === "preparing" ? (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <LoaderCircle className="size-4 motion-safe:animate-spin" aria-hidden />
              Working on it…
            </p>
          ) : (
            <p className="text-sm leading-6 text-muted-foreground">{step.body}</p>
          )}
        </div>
        <div className="h-0.5 overflow-hidden rounded-full bg-muted">
          <div className="h-full bg-brand transition-[width] duration-100" style={{ width: `${Math.round(progress * 100)}%` }} />
        </div>
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1">
            <button type="button" onClick={() => goTo(index - 1)} disabled={index === 0} aria-label="Previous step" className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40">
              <ChevronLeft className="size-4" aria-hidden />
            </button>
            <button type="button" onClick={() => setPaused((value) => !value)} aria-label={paused ? "Resume" : "Pause"} className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground">
              {paused ? <Play className="size-4" aria-hidden /> : <Pause className="size-4" aria-hidden />}
            </button>
            <button type="button" onClick={() => goTo(index + 1)} aria-label="Next step" className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground">
              <ChevronRight className="size-4" aria-hidden />
            </button>
          </div>
          <span className="text-xs text-muted-foreground">{paused ? "Paused" : hovered ? "Paused while you read" : ""}</span>
        </div>
      </div>
    </>
  );
}
