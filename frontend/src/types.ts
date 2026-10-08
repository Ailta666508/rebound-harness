export interface RunSummary {
  id: string;
  title: string;
  status: string;
  created_at: number;
  updated_at: number;
}
export interface Operation {
  id: string;
  step_key: string;
  tool: string;
  arguments: Record<string, unknown>;
  status: string;
  result: Record<string, unknown> | null;
  attempts: number;
}
export interface TraceEvent {
  seq: number;
  kind: string;
  operation_id: string | null;
  payload: Record<string, unknown>;
  created_at: number;
}
export interface Run extends RunSummary {
  steps: { key: string; tool: string; arguments: Record<string, unknown> }[];
  operations: Operation[];
  events: TraceEvent[];
  metadata: Record<string, unknown>;
  metrics?: Record<string, number>;
  [key: string]: unknown;
}

export async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const detail =
      typeof data.detail === "string"
        ? data.detail
        : `Request failed (${response.status}).`;
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export const label = (value: string) =>
  value.replaceAll("_", " ").replaceAll(".", " · ");
export const isDone = (status: string) =>
  ["completed", "committed", "succeeded", "success"].includes(status);
export const isAttention = (status: string) =>
  ["needs_review", "unknown", "interrupted", "failed", "paused"].includes(
    status,
  );
export const displayTime = (value: number) =>
  new Date(value * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
