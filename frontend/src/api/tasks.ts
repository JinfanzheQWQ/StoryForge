import { requestJson } from "./client";
import type { TaskRecord } from "../types";

export function getTask(taskId: string): Promise<TaskRecord> {
  return requestJson<TaskRecord>(`/v1/tasks/${taskId}`);
}
