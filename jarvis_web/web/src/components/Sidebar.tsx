import { KeyboardEvent, useEffect, useMemo, useState } from "react";

import { searchHistory } from "../api";
import type { HistoryHit, SessionSummary } from "../types";

type Props = {
  sessions: SessionSummary[];
  activeSessionId: string | null;
  onNew: () => void;
  onSelect: (sessionId: string) => void;
  onRequestDelete: (session: SessionSummary) => void;
  onRename: (sessionId: string, title: string) => Promise<boolean>;
};

function relativeTime(iso: string): string {
  const timestamp = new Date(iso).getTime();
  if (!Number.isFinite(timestamp)) return "";
  const diff = Math.max(0, Date.now() - timestamp);
  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;

  if (diff < minute) return "agora";
  if (diff < hour) return `há ${Math.floor(diff / minute)} min`;
  if (diff < day) return `há ${Math.floor(diff / hour)} h`;
  if (diff < 2 * day) return "ontem";
  if (diff < 7 * day) return `há ${Math.floor(diff / day)} dias`;
  return new Intl.DateTimeFormat("pt-PT", {
    day: "2-digit",
    month: "short"
  }).format(new Date(iso));
}

function ChatIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 5.5h14v10H9l-4 3v-13Z" />
    </svg>
  );
}

function PencilIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="m5 16 10-10 3 3L8 19l-4 1 1-4Z" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M7 8h10l-1 11H8L7 8Zm2-3h6l1 2H8l1-2Z" />
    </svg>
  );
}

export default function Sidebar({
  sessions,
  activeSessionId,
  onNew,
  onSelect,
  onRequestDelete,
  onRename
}: Props) {
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<HistoryHit[]>([]);
  const [searching, setSearching] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState("");
  const [renameSaving, setRenameSaving] = useState(false);
  const [renameError, setRenameError] = useState<string | null>(null);

  const sessionMap = useMemo(
    () => new Map(sessions.map((session) => [session.id, session])),
    [sessions]
  );

  useEffect(() => {
    const trimmed = query.trim();
    if (trimmed.length < 2) {
      setHits([]);
      setSearching(false);
      return;
    }

    setSearching(true);
    const timer = window.setTimeout(() => {
      void searchHistory(trimmed)
        .then((result) => setHits(result.hits))
        .finally(() => setSearching(false));
    }, 220);

    return () => window.clearTimeout(timer);
  }, [query]);

  function beginRename(session: SessionSummary) {
    setEditingId(session.id);
    setDraftTitle(session.title);
    setRenameError(null);
  }

  async function commitRename(sessionId: string) {
    if (renameSaving) return;
    const clean = draftTitle.trim();
    if (!clean) {
      setRenameError("O nome da conversa não pode ficar vazio.");
      return;
    }

    setRenameSaving(true);
    setRenameError(null);
    const saved = await onRename(sessionId, clean);
    setRenameSaving(false);

    if (saved) {
      setEditingId(null);
      setDraftTitle("");
    } else {
      setRenameError("Não foi possível gravar o nome da conversa.");
    }
  }

  function handleRenameKey(
    event: KeyboardEvent<HTMLInputElement>,
    sessionId: string
  ) {
    if (event.key === "Enter") {
      event.preventDefault();
      void commitRename(sessionId);
    } else if (event.key === "Escape" && !renameSaving) {
      setEditingId(null);
      setDraftTitle("");
      setRenameError(null);
    }
  }

  return (
    <aside className="sidebar">
      <div className="brandBlock">
        <div className="brandCore" aria-hidden="true"><span /></div>
        <div>
          <div className="brand">JARVIS</div>
          <div className="brandSubtitle">ASSISTENTE INTELIGENTE</div>
        </div>
      </div>

      <button className="newChat" type="button" onClick={onNew}>
        <span className="newChatPlus">+</span>
        Nova conversa
      </button>

      <label className="historySearch">
        <span className="searchIcon" aria-hidden="true">⌕</span>
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Pesquisar conversas..."
          aria-label="Pesquisar conversas"
        />
      </label>

      <div className="historyLabel">
        {query.trim().length >= 2 ? "Resultados" : "Conversas"}
      </div>

      <nav className="sessionList" aria-label="Histórico de conversas">
        {query.trim().length >= 2 ? (
          <>
            {searching && <div className="emptyHistory">A pesquisar…</div>}
            {!searching && hits.length === 0 && (
              <div className="emptyHistory">Sem resultados.</div>
            )}
            {hits.map((hit, index) => (
              <button
                className="historyHit"
                type="button"
                key={`${hit.session_id}-${hit.message_id ?? "title"}-${index}`}
                onClick={() => onSelect(hit.session_id)}
              >
                <strong>{hit.session_title}</strong>
                <span>{hit.snippet}</span>
              </button>
            ))}
          </>
        ) : (
          <>
            {sessions.length === 0 && (
              <div className="emptyHistory">Ainda não existem conversas.</div>
            )}
            {sessions.map((session) => (
              <div
                className={`sessionItem ${
                  activeSessionId === session.id ? "active" : ""
                }`}
                key={session.id}
              >
                <div className="sessionIcon"><ChatIcon /></div>
                {editingId === session.id ? (
                  <input
                    className="sessionRenameInput"
                    value={draftTitle}
                    autoFocus
                    maxLength={80}
                    onChange={(event) => setDraftTitle(event.target.value)}
                    onKeyDown={(event) => handleRenameKey(event, session.id)}
                    aria-label={`Renomear ${session.title}`}
                    disabled={renameSaving}
                  />
                ) : (
                  <button
                    className="sessionSelect"
                    type="button"
                    onClick={() => onSelect(session.id)}
                    title={session.title}
                  >
                    <span>{session.title}</span>
                    <small>
                      {session.message_count} msg · {relativeTime(session.updated_at)}
                    </small>
                  </button>
                )}
                <div className="sessionTools">
                  <button
                    className="sessionRename"
                    type="button"
                    aria-label={editingId === session.id ? "Guardar nome" : `Renomear ${session.title}`}
                    disabled={renameSaving}
                    onClick={() =>
                      editingId === session.id
                        ? void commitRename(session.id)
                        : beginRename(session)
                    }
                  >
                    {editingId === session.id ? (renameSaving ? "…" : "✓") : <PencilIcon />}
                  </button>
                  <button
                    className="sessionDelete"
                    type="button"
                    aria-label={`Eliminar ${session.title}`}
                    onClick={() => onRequestDelete(sessionMap.get(session.id) ?? session)}
                  >
                    <TrashIcon />
                  </button>
                </div>
              </div>
            ))}
          </>
        )}
      </nav>

      {renameError && <div className="renameError" role="alert">{renameError}</div>}

      <div className="sidebarFooter">
        <span>LOCAL</span><i /> <span>127.0.0.1</span>
      </div>
    </aside>
  );
}
