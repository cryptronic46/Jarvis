export type Role = "user" | "assistant";

export type Message = {
  id: string;
  role: Role;
  content: string;
  created_at?: string;
};

export type SessionSummary = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
};

export type SessionDetail = SessionSummary & {
  messages: Message[];
};

export type HistoryHit = {
  session_id: string;
  session_title: string;
  message_id?: string | null;
  role?: string | null;
  snippet: string;
  score: number;
  updated_at: string;
};

export type HistorySearchResponse = {
  query: string;
  hits: HistoryHit[];
};

export type JarvisEvent = {
  type: string;
  timestamp: string;
  session_id?: string | null;
  data: Record<string, unknown>;
};

export type StreamPacket =
  | { type: "meta"; session_id: string; provider: string }
  | { type: "delta"; delta: string }
  | { type: "done"; message_id: string; session_id: string }
  | { type: "error"; message: string };


export type AuthStatus = {
  authenticated: boolean;
};
