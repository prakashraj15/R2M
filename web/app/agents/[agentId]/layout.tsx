import { notFound } from "next/navigation";
export default async function AgentLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ agentId: string }>;
}) {
  const { agentId } = await params;
  if (agentId !== "opspilot") notFound();
  return children;
}
