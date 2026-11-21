import type { ComponentProps, ReactNode } from "react";
import { CircleAlert, LoaderCircle } from "lucide-react";

import { cn } from "@/lib/utils";

export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  /** A short label above the title, such as the section it belongs to. */
  eyebrow?: string;
}) {
  return (
    <div className="flex flex-col gap-4 border-b pb-8 sm:flex-row sm:items-end sm:justify-between">
      <div className="flex max-w-3xl flex-col gap-3">
        {eyebrow && (
          <p className="text-xs font-semibold tracking-[0.14em] text-brand uppercase">{eyebrow}</p>
        )}
        <h1 className="text-[2rem] leading-tight font-semibold tracking-tight text-balance sm:text-[2.4rem]">
          {title}
        </h1>
        {description && (
          <p className="max-w-[68ch] text-[0.95rem] leading-7 text-pretty text-muted-foreground">{description}</p>
        )}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

/** A heading for a group of panels within a page. */
export function SectionTitle({ children, hint }: { children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
      <h2 className="text-lg font-semibold tracking-tight">{children}</h2>
      {hint && <p className="text-sm text-muted-foreground">{hint}</p>}
    </div>
  );
}

export function Panel({
  title,
  description,
  actions,
  children,
  className,
  "data-tour": tour,
}: {
  title?: string;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  /** Anchor for the guided walkthrough. */
  "data-tour"?: string;
}) {
  return (
    <section
      data-tour={tour}
      className={cn(
        "flex min-w-0 flex-col gap-5 rounded-2xl border bg-card p-5 text-card-foreground shadow-[0_1px_2px_oklch(0_0_0/0.04)] sm:p-6",
        className,
      )}
    >
      {(title || actions) && (
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 flex-col gap-1.5">
            {title && <h2 className="text-base leading-6 font-semibold tracking-tight">{title}</h2>}
            {description && <p className="max-w-[65ch] text-sm leading-6 text-muted-foreground">{description}</p>}
          </div>
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <dt className="text-[0.7rem] font-semibold tracking-[0.08em] text-muted-foreground uppercase">{label}</dt>
      <dd className="font-mono text-2xl font-medium tracking-tight tabular-nums">{value}</dd>
      {hint && <dd className="text-xs text-muted-foreground">{hint}</dd>}
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <p className="rounded-xl border border-dashed bg-surface/60 px-5 py-8 text-center text-sm leading-6 text-muted-foreground">
      {children}
    </p>
  );
}

export function Loading({ label = "Loading", inline = false }: { label?: string; inline?: boolean }) {
  if (inline) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
        <LoaderCircle className="size-4 motion-safe:animate-spin" aria-hidden />
        {label}
      </p>
    );
  }
  // A placeholder in the shape of a panel, so the page doesn't jump when data lands.
  return (
    <div role="status" aria-label={label} className="flex flex-col gap-4 rounded-2xl border bg-card p-6">
      <span className="h-4 w-40 rounded-md bg-muted motion-safe:animate-pulse" />
      <span className="h-3 w-full max-w-xl rounded-md bg-muted motion-safe:animate-pulse" />
      <span className="h-3 w-4/5 max-w-lg rounded-md bg-muted motion-safe:animate-pulse" />
      <span className="h-3 w-3/5 max-w-md rounded-md bg-muted motion-safe:animate-pulse" />
    </div>
  );
}

export function ErrorNote({ message }: { message: string | null | undefined }) {
  if (!message) return null;
  return (
    <p role="alert" className="flex items-start gap-2.5 rounded-xl border border-stale-line/40 bg-stale-soft px-4 py-3 text-sm text-stale">
      <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
      {message}
    </p>
  );
}

export function NativeSelect({ className, children, ...props }: ComponentProps<"select">) {
  return (
    <select
      className={cn(
        "h-9 w-full rounded-lg border border-input bg-background px-2.5 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30",
        className,
      )}
      {...props}
    >
      {children}
    </select>
  );
}

export function Field({
  label,
  htmlFor,
  hint,
  children,
}: {
  label: string;
  htmlFor: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-sm font-semibold">
        {label}
      </label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
  label,
}: {
  tabs: { id: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div role="tablist" aria-label={label} className="flex gap-2 overflow-x-auto border-b [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
      {tabs.map((tab, index) => (
        <button
          key={tab.id}
          id={`tab-${tab.id}`}
          type="button"
          role="tab"
          aria-selected={value === tab.id}
          tabIndex={value === tab.id ? 0 : -1}
          onClick={() => onChange(tab.id)}
          onKeyDown={(event) => {
            if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
            event.preventDefault();
            const step = event.key === "ArrowRight" ? 1 : -1;
            const next = tabs[(index + step + tabs.length) % tabs.length];
            onChange(next.id);
            document.getElementById(`tab-${next.id}`)?.focus();
          }}
          className={cn(
            "-mb-px shrink-0 border-b-2 px-3 py-2.5 text-sm whitespace-nowrap outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
            value === tab.id
              ? "border-brand font-semibold text-foreground"
              : "border-transparent text-muted-foreground hover:border-border hover:text-foreground",
          )}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

export function percent(value: number | null | undefined): string {
  return value === null || value === undefined ? "n/a" : `${Math.round(value * 100)}%`;
}
