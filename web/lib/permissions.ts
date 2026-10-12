import type { Role } from "./types.ts";
export const roleNames: Record<Role, string> = {
  vendor_developer: "Vendor developer",
  vendor_release_manager: "Release manager",
  customer_security: "Security reviewer",
  customer_ops: "Operations engineer",
};
export const canReview = (role: Role) => role === "customer_security";
export const canEvaluate = (role: Role) => role === "vendor_release_manager";
export const canDeploy = (role: Role) => role === "vendor_release_manager";
// Live: Meridian operations chats with OpsPilot; Atlas roles may too (vendor-only fault testing).
export const canRun = (role: Role) => role !== "customer_security";
export const isVendor = (role: Role) => role.startsWith("vendor_");
