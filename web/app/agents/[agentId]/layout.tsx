import { notFound } from "next/navigation";
import { Suspense } from "react";
import { LiveWorkspace } from "@/components/live/LiveWorkspace";
export default async function AgentLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ agentId: string }>;
}) {
  const { agentId } = await params;
  if (agentId === "opspilot") return children;
  if (
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
      agentId,
    )
  )
    notFound();
  return (
    <Suspense fallback={<p>Loading connected workspace…</p>}>
      <LiveWorkspace agent={agentId} />
    </Suspense>
  );
}
