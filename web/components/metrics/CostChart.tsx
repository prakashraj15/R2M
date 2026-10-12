"use client";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
} from "recharts";
export function CostChart({
  data,
  kind = "runs",
}: {
  data: { name: string; value: number }[];
  kind?: "runs" | "cost";
}) {
  return (
    <div
      className="chart"
      role="img"
      aria-label={`${kind === "cost" ? "Model cost" : "Run duration in milliseconds"} by execution`}
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={data}
          margin={{ top: 10, right: 8, bottom: 0, left: 0 }}
        >
          <CartesianGrid
            strokeDasharray="3 5"
            vertical={false}
            stroke="#e9ede7"
          />
          <XAxis
            dataKey="name"
            axisLine={false}
            tickLine={false}
            tick={{ fill: "#839088", fontSize: 10 }}
          />
          <YAxis
            width={42}
            axisLine={false}
            tickLine={false}
            tick={{ fill: "#839088", fontSize: 10 }}
          />
          <Tooltip
            contentStyle={{
              border: "1px solid #e1e8db",
              borderRadius: 9,
              fontSize: 12,
            }}
            labelStyle={{ color: "#344537" }}
          />
          <Bar
            dataKey="value"
            name={kind === "cost" ? "USD" : "Duration (ms)"}
            fill="#bfe85c"
            radius={[4, 4, 0, 0]}
            maxBarSize={50}
            isAnimationActive={false}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
