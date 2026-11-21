import type { Metadata } from "next";

import { PoliciesPage } from "@/components/pages/policies-page";

export const metadata: Metadata = { title: "Policies · ShelfLife" };

export default function Page() {
  return <PoliciesPage />;
}
