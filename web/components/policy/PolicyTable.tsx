"use client";
import { useR2M } from "@/components/R2MProvider";
import { Badge } from "@/components/ui/shared";
export function PolicyTable({
  selected,
  onSelect,
}: {
  selected: string;
  onSelect: (id: string) => void;
}) {
  const { state, policies } = useR2M();
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>POLICY</th>
            <th>VERSION</th>
            <th>STATUS</th>
            <th>CREATOR / UPDATED</th>
            <th>APPROVER</th>
            <th>NEXT REVIEW</th>
          </tr>
        </thead>
        <tbody>
          {policies.map((p) => {
            const review = state.approvals.find(
              (a) => a.kind === "policy" && a.policy === p.id,
            );
            return (
              <tr
                key={p.id}
                className={selected === p.id ? "row-selected" : ""}
              >
                <td>
                  <button className="table-link" onClick={() => onSelect(p.id)}>
                    {p.name}
                  </button>
                  <small>{p.id} · OpsPilot / Meridian</small>
                </td>
                <td>v{p.version}</td>
                <td>
                  <Badge>
                    {review?.status === "approved"
                      ? "Approved"
                      : review?.status === "rejected"
                        ? "Rejected"
                        : "In review"}
                  </Badge>
                </td>
                <td>
                  Alex Chen<small>{p.updated}</small>
                </td>
                <td>{review?.reviewedBy || "Awaiting reviewer"}</td>
                <td>{p.review}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
