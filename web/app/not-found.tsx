import { cp } from "@/lib/live-adapter";
export default function NotFound() {
  return (
    <div className="empty">
      <h1>Workspace not found</h1>
      <p>This workspace has one agent installed: OpsPilot.</p>
      {/* plain <a>: on the desk this crosses to the Control Plane origin */}
      <a className="button button-primary" href={cp("/agents/opspilot")}>
        Open OpsPilot
      </a>
    </div>
  );
}
