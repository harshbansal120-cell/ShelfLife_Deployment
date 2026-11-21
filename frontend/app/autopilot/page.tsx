import type { Metadata } from "next";

import { AutopilotPage } from "@/components/pages/autopilot-page";

export const metadata: Metadata = { title: "Autopilot · ShelfLife" };

export default function Page() {
  return <AutopilotPage />;
}
