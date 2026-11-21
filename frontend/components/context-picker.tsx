"use client";

import { MapPin } from "lucide-react";

import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui-kit";
import type { CheckContext, Profile } from "@/lib/types";
import { COUNTRIES, contextLines, titleCase } from "@/lib/workspace-api";

/** Who the answer is for: a saved profile, or a one-off context. */
export function ContextPicker({
  context,
  onContextChange,
  profiles,
  profileId,
  onProfileChange,
}: {
  context: CheckContext;
  onContextChange: (context: CheckContext) => void;
  profiles: Profile[];
  profileId: string;
  onProfileChange: (id: string) => void;
}) {
  const profile = profiles.find((item) => item.id === profileId);
  const shown = profile ? profile.context : context;
  const summary = contextLines(shown);
  const set = (key: keyof CheckContext, value: string) =>
    onContextChange({ ...context, [key]: value || null });

  return (
    <details className="group rounded-lg border px-3 py-2.5" open={summary.length > 0 || undefined}>
      <summary className="flex cursor-pointer items-center gap-2 text-sm select-none">
        <MapPin className="size-4 text-muted-foreground" aria-hidden />
        <span className="font-medium">Context</span>
        <span className="truncate text-muted-foreground">
          {summary.length ? summary.join(" · ") : "optional: country, plan, environment"}
        </span>
      </summary>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        {profiles.length > 0 && (
          <label className="flex flex-col gap-1.5 text-sm sm:col-span-2">
            <span className="font-medium">Saved profile</span>
            <NativeSelect value={profileId} onChange={(event) => onProfileChange(event.target.value)}>
              <option value="">No profile: set the context below</option>
              {profiles.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name} (version {item.version})
                </option>
              ))}
            </NativeSelect>
            <span className="text-xs text-muted-foreground">
              Checks made with a profile are flagged on the dashboard when the profile changes later.
            </span>
          </label>
        )}
        <label className="flex flex-col gap-1.5 text-sm">
          <span className="font-medium">Country</span>
          <NativeSelect
            value={shown.country ?? ""}
            disabled={Boolean(profile)}
            onChange={(event) => set("country", event.target.value)}
          >
            <option value="">Any</option>
            {COUNTRIES.map((country) => (
              <option key={country} value={country}>
                {titleCase(country)}
              </option>
            ))}
          </NativeSelect>
        </label>
        <label className="flex flex-col gap-1.5 text-sm">
          <span className="font-medium">Plan or edition</span>
          <Input
            value={shown.edition ?? ""}
            disabled={Boolean(profile)}
            maxLength={120}
            placeholder="e.g. Free plan, Enterprise"
            className="h-9"
            onChange={(event) => set("edition", event.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1.5 text-sm">
          <span className="font-medium">Software environment</span>
          <Input
            value={shown.environment ?? ""}
            disabled={Boolean(profile)}
            maxLength={120}
            placeholder="e.g. Python 3.12 on Linux"
            className="h-9"
            onChange={(event) => set("environment", event.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1.5 text-sm">
          <span className="font-medium">Currency</span>
          <Input
            value={shown.currency ?? ""}
            disabled={Boolean(profile)}
            maxLength={12}
            placeholder="e.g. INR"
            className="h-9"
            onChange={(event) => set("currency", event.target.value)}
          />
        </label>
      </div>
    </details>
  );
}
