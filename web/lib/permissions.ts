import type { Role, Organization } from "./types.ts";
export const roleNames: Record<Role, string> = {
  vendor_developer: "Vendor developer",
  vendor_release_manager: "Release manager",
  customer_security: "Security reviewer",
  customer_ops: "Operations viewer",
};
export const rolesFor: Record<Organization, Role[]> = {
  atlas: ["vendor_developer", "vendor_release_manager"],
  meridian: ["customer_security", "customer_ops"],
};
export const canReview = (role: Role) => role === "customer_security";
export const canEvaluate = (role: Role) => role === "vendor_release_manager";
export const canDeploy = (role: Role) => role === "vendor_release_manager";
export const canRun = (role: Role) =>
  role === "vendor_developer" || role === "vendor_release_manager";
export const isVendor = (role: Role) => role.startsWith("vendor_");
