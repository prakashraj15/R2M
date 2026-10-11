import type { Metadata } from "next";
import { MockProvider } from "@/components/MockProvider";
import { AppShell } from "@/components/navigation/AppShell";
import "@/styles/globals.css";
import "@xyflow/react/dist/style.css";
export const metadata: Metadata = {
  title: "R2M — Responsibility to Monitoring",
  description: "OpsPilot governance and observability frontend prototype.",
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <MockProvider>
          <AppShell>{children}</AppShell>
        </MockProvider>
      </body>
    </html>
  );
}
