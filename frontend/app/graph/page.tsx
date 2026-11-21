import type { Metadata } from "next";

import { GraphPage } from "@/components/pages/graph-page";

export const metadata: Metadata = { title: "Graph · ShelfLife" };

export default function Page() {
  return <GraphPage />;
}
