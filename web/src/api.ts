import type {
  ClientConfig,
  ReplayMessage,
  ReplayRequest,
  Stats
} from "./types";

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    }
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json() as Promise<T>;
}

export function getConfig() {
  return json<ClientConfig>("/api/config");
}

export function getStats() {
  return json<Stats>("/api/stats");
}

export async function replay(body: ReplayRequest, onMessage: (message: ReplayMessage) => void) {
  const response = await fetch("/api/replay/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!response.ok || !response.body) {
    throw new Error(await response.text());
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (line.trim()) onMessage(JSON.parse(line) as ReplayMessage);
    }
  }
  if (buffer.trim()) onMessage(JSON.parse(buffer) as ReplayMessage);
}
