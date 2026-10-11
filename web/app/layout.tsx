import type { Metadata } from "next";
import { MockProvider } from "@/components/MockProvider";
import { AppShell } from "@/components/navigation/AppShell";
import { LiveProvider } from "@/components/live/LiveProvider";
import "@/styles/globals.css";
import "@xyflow/react/dist/style.css";
export const metadata: Metadata = {
  title: "R2M — Responsibility to Monitoring",
  description: "OpsPilot governance and observability frontend prototype.",
  icons: { icon: "/brand/r2m-icon.svg" },
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
          <LiveProvider>
            <AppShell>{children}</AppShell>
          </LiveProvider>
        </MockProvider>
      </body>
    </html>
  );
}
