import type { Metadata } from "next";

import { EvaluationPage } from "@/components/pages/evaluation-page";

export const metadata: Metadata = { title: "Evaluation · ShelfLife" };

export default function Page() {
  return <EvaluationPage />;
}
