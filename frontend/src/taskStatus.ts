import type { Task } from "./api"

export function phaseLabel(task: Task): string {
  return (task.execution_phase || task.state || task.status || "queued")
    .toLowerCase()
    .replaceAll("_", " ")
}
