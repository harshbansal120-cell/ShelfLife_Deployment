import type { Metadata } from "next";

import { ImpactPage } from "@/components/pages/impact-page";

export const metadata: Metadata = { title: "Impact · ShelfLife" };

export default function Page() {
  return <ImpactPage />;
}
