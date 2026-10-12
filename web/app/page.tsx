"use client";
import { APP } from "@/lib/live-adapter";
import { Overview } from "@/components/overview/Overview";
import { OperationsDesk } from "@/components/desk/OperationsDesk";
// Each app's home: the Control Plane opens on the organization overview, the Operations Desk on the agent console.
export default function Home() {
  return APP === "desk" ? <OperationsDesk /> : <Overview />;
}
