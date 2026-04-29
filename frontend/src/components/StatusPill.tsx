import type { TaskStatus } from "../types";

export function StatusPill({ status }: { status?: TaskStatus }) {
  const resolved = status || "unknown";
  return <span className={`status-pill status-${resolved}`}>{labelStatus(resolved)}</span>;
}

function labelStatus(status: TaskStatus): string {
  if (status === "queued") return "排队中";
  if (status === "running") return "运行中";
  if (status === "completed") return "已完成";
  if (status === "failed") return "失败";
  if (status === "unknown") return "未开始";
  return String(status);
}
