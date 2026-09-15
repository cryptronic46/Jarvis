import type { AuthStatus, HistorySearchResponse, SessionDetail, SessionSummary, StreamPacket } from "./types";

export class JarvisApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: string
  ) {
    super(message);
  }
}

async function expectJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = `API returned ${response.status}`;
    let code: string | undefined;

    try {
      const payload = await response.json();
      if (typeof payload?.detail === "string") {
        message = payload.detail;
      } else if (payload?.detail && typeof payload.detail === "object") {
        message = payload.detail.message ?? message;
        code = payload.detail.code;
      }
    } catch {
      // Keep generic API error.
    }

    throw new JarvisApiError(response.status, message, code);
  }
  return (await response.json()) as T;
}

export async function getSessions(): Promise<SessionSummary[]> {
  return expectJson(await fetch("/api/sessions", { cache: "no-store" }));
}

export async function createSession(): Promise<SessionDetail> {
  return expectJson(
    await fetch("/api/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" }
    })
  );
}

export async function getSession(sessionId: string): Promise<SessionDetail> {
  return expectJson(
    await fetch(`/api/sessions/${encodeURIComponent(sessionId)}`, {
      cache: "no-store"
    })
  );
}

export async function deleteSession(sessionId: string): Promise<void> {
  const response = await fetch(
    `/api/sessions/${encodeURIComponent(sessionId)}`,
    { method: "DELETE" }
  );
  if (!response.ok && response.status !== 204) {
    throw new Error(`API returned ${response.status}`);
  }
}

export async function streamChat(
  message: string,
  sessionId: string | null,
  onPacket: (packet: StreamPacket) => void
): Promise<void> {
  const response = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      session_id: sessionId
    })
  });

  if (!response.ok || !response.body) {
    throw new Error(`API returned ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });

    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      onPacket(JSON.parse(trimmed) as StreamPacket);
    }

    if (done) break;
  }

  if (buffer.trim()) {
    onPacket(JSON.parse(buffer) as StreamPacket);
  }
}


export async function searchHistory(
  query: string,
  limit = 10
): Promise<HistorySearchResponse> {
  const params = new URLSearchParams({
    q: query,
    limit: String(limit)
  });
  return expectJson(
    await fetch(`/api/history/search?${params.toString()}`, {
      cache: "no-store"
    })
  );
}


export async function getAuthStatus(): Promise<AuthStatus> {
  return expectJson(
    await fetch("/api/auth/status", {
      cache: "no-store"
    })
  );
}


export async function renameSession(
  sessionId: string,
  title: string
): Promise<SessionDetail> {
  return expectJson(
    await fetch(`/api/sessions/${encodeURIComponent(sessionId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title })
    })
  );
}
