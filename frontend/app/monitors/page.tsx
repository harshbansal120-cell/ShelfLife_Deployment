import type { Metadata } from "next";

import { MonitorsPage } from "@/components/pages/monitors-page";

export const metadata: Metadata = { title: "Monitors · ShelfLife" };

export default function Page() {
  return <MonitorsPage />;
}
