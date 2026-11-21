import type { Metadata } from "next";

import { ComparePage } from "@/components/pages/compare-page";

export const metadata: Metadata = { title: "Compare · ShelfLife" };

export default function Page() {
  return <ComparePage />;
}
