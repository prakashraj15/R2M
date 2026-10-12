import type { Metadata } from "next";
import { R2MProvider } from "@/components/R2MProvider";
import { AppShell } from "@/components/navigation/AppShell";
import "@/styles/globals.css";
import "@xyflow/react/dist/style.css";
export const metadata: Metadata = {
  title: "R2M — Responsibility to Monitoring",
  description: "R2M: AI agent governance, runtime control and evidence.",
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
        <R2MProvider>
          <AppShell>{children}</AppShell>
        </R2MProvider>
      </body>
    </html>
  );
}
