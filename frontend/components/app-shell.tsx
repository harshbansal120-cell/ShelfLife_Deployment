"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import {
  Activity,
  BadgeCheck,
  Bot,
  CircleAlert,
  FileStack,
  FlaskConical,
  GitBranch,
  LayoutDashboard,
  Menu,
  Radar,
  Scale,
  ScanSearch,
  Settings2,
  SlidersHorizontal,
  X,
  type LucideIcon,
} from "lucide-react";

import { AutopilotToggle } from "@/components/autopilot-toggle";
import { GuidedTour } from "@/components/guided-tour";
import { Logo } from "@/components/logo";
import { API_URL, getHealth } from "@/lib/api";
import type { Health } from "@/lib/types";
import { cn } from "@/lib/utils";

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
}

const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: "Verify",
    items: [
      { href: "/", label: "Check an answer", icon: ScanSearch },
      { href: "/compare", label: "Compare apps", icon: Scale },
      { href: "/claims", label: "Claims", icon: BadgeCheck },
    ],
  },
  {
    label: "Keep fresh",
    items: [
      { href: "/impact", label: "Impact", icon: FileStack },
      { href: "/graph", label: "Dependency graph", icon: GitBranch },
      { href: "/autopilot", label: "Autopilot", icon: Bot },
      { href: "/policies", label: "Policies", icon: SlidersHorizontal },
      { href: "/monitors", label: "Monitors", icon: Radar },
    ],
  },
  {
    label: "Insight",
    items: [
      { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
      { href: "/evaluation", label: "Evaluation", icon: FlaskConical },
      { href: "/system", label: "System", icon: Settings2 },
    ],
  },
];

type HealthState = Health | "unreachable" | null;

function problems(health: HealthState): string[] {
  if (health === null) return [];
  if (health === "unreachable") {
    return [`Can't reach the ShelfLife API at ${API_URL}. Start the backend, then reload.`];
  }
  const found: string[] = [];
  if (!health.bifrost.ok) found.push(`Bifrost: ${health.bifrost.detail}.`);
  if (!health.tavily.ok) found.push(`Tavily: ${health.tavily.detail}.`);
  if (health.missing_settings.length > 0) {
    found.push(`Missing settings in .env: ${health.missing_settings.join(", ")}.`);
  }
  return found;
}

function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

function Navigation({ pathname, onNavigate }: { pathname: string; onNavigate?: () => void }) {
  return (
    <nav aria-label="Main" className="flex flex-col gap-6" data-tour="navigation">
      {NAV_GROUPS.map((group) => (
        <div key={group.label} className="flex flex-col gap-1">
          <p className="px-3 pb-1 text-[0.68rem] font-semibold tracking-[0.12em] text-muted-foreground uppercase">
            {group.label}
          </p>
          {group.items.map((item) => {
            const active = isActive(pathname, item.href);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={onNavigate}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "group flex items-center gap-3 rounded-lg px-3 py-2 text-sm outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
                  active
                    ? "bg-sidebar-accent font-semibold text-sidebar-accent-foreground"
                    : "text-sidebar-foreground/80 hover:bg-sidebar-accent/60 hover:text-sidebar-foreground",
                )}
              >
                <Icon
                  className={cn("size-4 shrink-0", active ? "text-brand" : "text-muted-foreground group-hover:text-foreground")}
                  aria-hidden
                />
                {item.label}
              </Link>
            );
          })}
        </div>
      ))}
    </nav>
  );
}

function ServiceStatus({ health, problemsFound }: { health: HealthState; problemsFound: number }) {
  if (health === null) return null;
  const ok = health !== "unreachable" && problemsFound === 0;
  const label = !ok
    ? "Services need attention"
    : health.tavily.rate_limited
      ? "Tavily is rate-limiting"
      : "Bifrost and Tavily connected";
  return (
    <p className="flex items-center gap-2 px-3 text-xs text-muted-foreground">
      <span className={cn("size-2 rounded-full", ok ? "bg-fresh-line" : "bg-stale-line")} aria-hidden />
      {label}
    </p>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [health, setHealth] = useState<HealthState>(null);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    let active = true;
    getHealth()
      .then((value) => {
        if (active) setHealth(value);
      })
      .catch(() => {
        if (active) setHealth("unreachable");
      });
    return () => {
      active = false;
    };
  }, []);

  // Close the phone menu with Escape.
  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && setMenuOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menuOpen]);

  const found = problems(health);
  const connected = health !== null && health !== "unreachable";
  const guided = connected && Boolean(health.demo_mode);

  const sidebarBody = (onNavigate?: () => void) => (
    <>
      <Navigation pathname={pathname} onNavigate={onNavigate} />
      <div className="mt-auto flex flex-col gap-3 border-t border-sidebar-border pt-4">
        {connected && (
          <div className="flex flex-col gap-2 px-3">
            <p className="text-[0.68rem] font-semibold tracking-[0.12em] text-muted-foreground uppercase">Mode</p>
            <AutopilotToggle />
          </div>
        )}
        <ServiceStatus health={health} problemsFound={found.length} />
      </div>
    </>
  );

  return (
    <div className="flex min-h-dvh flex-1">
      <aside className="sticky top-0 hidden h-dvh w-64 shrink-0 flex-col gap-8 overflow-y-auto border-r border-sidebar-border bg-sidebar px-3 py-6 [scrollbar-width:thin] lg:flex">
        <Link href="/" className="rounded-lg px-3 outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <Logo />
        </Link>
        {sidebarBody()}
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-40 flex items-center justify-between gap-3 border-b bg-background/90 px-4 py-3 backdrop-blur lg:hidden">
          <Link href="/" className="outline-none">
            <Logo />
          </Link>
          <button
            type="button"
            onClick={() => setMenuOpen(true)}
            aria-label="Open the menu"
            aria-expanded={menuOpen}
            className="rounded-lg border p-2 outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Menu className="size-5" aria-hidden />
          </button>
        </header>

        {menuOpen && (
          <div className="fixed inset-0 z-[65] lg:hidden" role="dialog" aria-modal="true" aria-label="Menu">
            <button
              type="button"
              aria-label="Close the menu"
              className="absolute inset-0 bg-foreground/30 backdrop-blur-[2px]"
              onClick={() => setMenuOpen(false)}
            />
            <div className="absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col gap-8 overflow-y-auto bg-sidebar px-3 py-5 shadow-2xl">
              <div className="flex items-center justify-between px-3">
                <Logo />
                <button
                  type="button"
                  onClick={() => setMenuOpen(false)}
                  aria-label="Close the menu"
                  className="rounded-lg p-1.5 text-muted-foreground hover:bg-sidebar-accent"
                >
                  <X className="size-5" aria-hidden />
                </button>
              </div>
              {sidebarBody(() => setMenuOpen(false))}
            </div>
          </div>
        )}

        {found.length > 0 && (
          <div className="border-b border-stale-line/40 bg-stale-soft" role="alert">
            <div className="mx-auto flex w-full max-w-7xl items-start gap-2.5 px-5 py-3 text-sm text-stale sm:px-8 lg:px-12">
              <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
              <p>{found.join(" ")}</p>
            </div>
          </div>
        )}

        {children}

        <footer className="mt-auto border-t px-5 py-5 text-xs text-muted-foreground sm:px-8 lg:px-12">
          <div className="mx-auto flex w-full max-w-7xl flex-wrap items-center justify-between gap-2">
            <span className="flex items-center gap-1.5">
              <Activity className="size-3.5" aria-hidden />
              Every fact traced to a source, every score calculated in code.
            </span>
            <a href={`${API_URL}/docs`} className="underline-offset-4 hover:text-foreground hover:underline">
              API reference
            </a>
          </div>
        </footer>
      </div>
      {guided && <GuidedTour />}
    </div>
  );
}

export function PageContainer({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  return (
    <main
      className={cn(
        "mx-auto flex w-full flex-1 flex-col gap-8 px-5 py-8 sm:px-8 sm:py-12 lg:px-12",
        wide ? "max-w-7xl" : "max-w-5xl",
      )}
    >
      {children}
    </main>
  );
}
