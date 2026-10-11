import Link from "next/link";
export default function NotFound() {
  return (
    <div className="empty">
      <h1>Workspace not found</h1>
      <p>This prototype includes one agent: OpsPilot.</p>
      <Link className="button button-primary" href="/agents/opspilot">
        Open OpsPilot
      </Link>
    </div>
  );
}
