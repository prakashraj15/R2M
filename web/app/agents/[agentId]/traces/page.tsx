import { Suspense } from "react";
import { TracePage } from "@/components/traces/TracePage";
export default function Page() {
  return (
    <Suspense fallback={<p>Loading trace view…</p>}>
      <TracePage />
    </Suspense>
  );
}
