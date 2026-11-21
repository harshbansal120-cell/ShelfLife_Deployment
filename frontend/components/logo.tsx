"use client";

import { useId } from "react";

import { cn } from "@/lib/utils";

/**
 * The ShelfLife mark: a leaf growing from a shelf. The leaf is what's fresh; the
 * shelf is where facts sit while they age.
 */
export function LogoMark({ className, title }: { className?: string; title?: string }) {
  // Each mark needs its own gradient id: a gradient inside a hidden copy (such as the
  // desktop sidebar on a phone) doesn't paint, and ids are shared across the page.
  const gradient = `shelflife-mark-${useId().replace(/:/g, "")}`;
  return (
    <svg
      viewBox="0 0 32 32"
      className={cn("size-8 shrink-0", className)}
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true}
      aria-label={title}
    >
      <defs>
        <linearGradient id={gradient} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="oklch(0.56 0.17 277)" />
          <stop offset="1" stopColor="oklch(0.38 0.15 280)" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill={`url(#${gradient})`} />
      {/* Leaf */}
      <path d="M15.6 21.2C10.4 18.4 9.6 11.6 16.9 6.6c4.6 4.3 4.2 11.2-1.3 14.6Z" fill="oklch(0.97 0.03 150)" />
      <path d="M15.7 21.1 17.6 10.4" stroke="oklch(0.42 0.15 278)" strokeWidth="1.3" strokeLinecap="round" />
      {/* Shelf and its brackets */}
      <rect x="6.5" y="22.2" width="19" height="2.4" rx="1.2" fill="#fff" />
      <path d="M9.5 24.6v2.4M22.5 24.6v2.4" stroke="#fff" strokeOpacity="0.7" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

export function Logo({ className, compact = false }: { className?: string; compact?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <LogoMark />
      {!compact && (
        <span className="flex flex-col leading-none">
          <span className="font-display text-[1.2rem] font-semibold tracking-tight">ShelfLife</span>
          <span className="mt-1 text-[0.6rem] font-semibold tracking-[0.1em] whitespace-nowrap text-muted-foreground uppercase">
            AI answers, kept fresh
          </span>
        </span>
      )}
    </span>
  );
}
