import type { Metadata } from "next";

import { ClaimsPage } from "@/components/pages/claims-page";

export const metadata: Metadata = { title: "Claims · ShelfLife" };

export default function Page() {
  return <ClaimsPage />;
}
