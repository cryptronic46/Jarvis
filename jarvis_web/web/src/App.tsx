import {
  FormEvent,
  useEffect,
  useMemo,
  useRef,
  useState
} from "react";

import {
  JarvisApiError,
  createSession,
  deleteSession,
  getAuthStatus,
  getSession,
  getSessions,
  renameSession,
  streamChat
} from "./api";
import JarvisCoreVisual from "./components/JarvisCoreVisual";
import MessageContent, { MessageActions } from "./components/MessageContent";
import Sidebar from "./components/Sidebar";
import type {
  JarvisEvent,
  Message,
  SessionSummary,
  StreamPacket
} from "./types";

const WS_RETRY_MS = 1500;
function localMessage(role: "user" | "assistant", content = ""): Message {
  return { id: crypto.randomUUID(), role, content };
}

function SendIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="m4 11 16-7-7 16-2.2-6.8L4 11Z" />
    </svg>
  );
}

function GearIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="3" />
      <path d="M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.4-2.4 1A7 7 0 0 0 14.7 6L14.4 3h-4.8l-.3 3a7 7 0 0 0-1.8 1.1l-2.4-1-2 3.4 2 1.5a7 7 0 0 0 0 2l-2 1.5 2 3.4 2.4-1A7 7 0 0 0 9.3 18l.3 3h4.8l.3-3a7 7 0 0 0 1.8-1.1l2.4 1 2-3.4-2-1.5c.1-.3.1-.7.1-1Z" />
    </svg>
  );
}

function AttachIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M8.5 12.5 14 7a3 3 0 1 1 4.2 4.2l-7.8 7.8a5 5 0 0 1-7-7l8-8" />
    </svg>
  );
}

function MicIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect x="9" y="3" width="6" height="12" rx="3" />
      <path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3M9 21h6" />
    </svg>
  );
}

const suggestions = [
  ["✦", "Resumir um texto"],
  ["</>", "Ajuda com código"],
  ["◉", "Ideias criativas"],
  ["•••", "Mais opções"]
] as const;

export default function App() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [state, setState] = useState("connecting");
  const [sending, setSending] = useState(false);
  const [apiOnline, setApiOnline] = useState(false);
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<SessionSummary | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const retryTimer = useRef<number | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  const stateLabel = useMemo(() => {
    if (authenticated === false) return "Bloqueada";
    if (!apiOnline && state !== "connecting") return "API offline";
    const labels: Record<string, string> = {
      "jarvis.ready": "Pronta",
      "jarvis.thinking": "A pensar",
      "jarvis.executing": "A executar",
      "jarvis.completed": "Pronta",
      "jarvis.error": "Erro",
      connecting: "A ligar"
    };
    return labels[state] ?? state.replace("jarvis.", "");
  }, [state, apiOnline, authenticated]);

  const conversationActive = activeSessionId !== null || messages.length > 0;

  async function refreshSessions() {
    const list = await getSessions();
    setSessions(list);
    return list;
  }

  async function loadSession(sessionId: string) {
    const detail = await getSession(sessionId);
    setActiveSessionId(sessionId);
    setMessages(detail.messages);
    setSidebarOpen(false);
  }

  function startNewConversation() {
    // Idle-first: no empty session is persisted until the first message is sent.
    setActiveSessionId(null);
    setMessages([]);
    setInput("");
    setSidebarOpen(false);
    window.setTimeout(() => inputRef.current?.focus(), 40);
  }

  async function renameConversation(sessionId: string, title: string) {
    try {
      const updated = await renameSession(sessionId, title);
      setSessions((current) =>
        current.map((session) =>
          session.id === sessionId
            ? { ...session, title: updated.title, updated_at: updated.updated_at }
            : session
        )
      );
      return true;
    } catch {
      return false;
    }
  }

  async function confirmDelete() {
    if (!pendingDelete || deleting) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteSession(pendingDelete.id);
      await refreshSessions();
      if (pendingDelete.id === activeSessionId) {
        // Deleting the active chat returns JARVIS to the idle Concept D hero.
        setActiveSessionId(null);
        setMessages([]);
      }
      setPendingDelete(null);
    } catch {
      setDeleteError("Não foi possível eliminar a conversa.");
    } finally {
      setDeleting(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const auth = await getAuthStatus();
        if (cancelled) return;
        setAuthenticated(auth.authenticated);
        if (!auth.authenticated) return;
        // Deliberately do NOT auto-open the newest chat on startup.
        await refreshSessions();
      } catch {
        if (!cancelled) {
          setApiOnline(false);
          setAuthenticated(false);
        }
      }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: sending ? "smooth" : "auto" });
  }, [messages, sending]);

  useEffect(() => {
    if (authenticated !== true) return;
    let disposed = false;

    async function checkHealth() {
      try {
        const response = await fetch("/api/health", { cache: "no-store" });
        setApiOnline(response.ok);
      } catch {
        setApiOnline(false);
      }
    }

    function connectWebSocket() {
      if (disposed) return;
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const socket = new WebSocket(`${protocol}//${window.location.host}/api/events`);
      socketRef.current = socket;
      socket.onopen = () => {
        if (disposed) return;
        setApiOnline(true);
        setState("jarvis.ready");
      };
      socket.onmessage = (event) => {
        if (disposed) return;
        const payload = JSON.parse(event.data) as JarvisEvent;
        setState(payload.type);
      };
      socket.onerror = () => { if (!disposed) setApiOnline(false); };
      socket.onclose = () => {
        if (disposed) return;
        setApiOnline(false);
        setState("connecting");
        retryTimer.current = window.setTimeout(connectWebSocket, WS_RETRY_MS);
      };
    }

    void checkHealth();
    connectWebSocket();
    const healthTimer = window.setInterval(() => void checkHealth(), 5000);

    return () => {
      disposed = true;
      window.clearInterval(healthTimer);
      if (retryTimer.current !== null) window.clearTimeout(retryTimer.current);
      socketRef.current?.close();
    };
  }, [authenticated]);

  async function sendMessage(event: FormEvent) {
    event.preventDefault();
    const message = input.trim();
    if (!message || sending || authenticated !== true) return;

    let sessionId = activeSessionId;
    try {
      if (!sessionId) {
        const created = await createSession();
        sessionId = created.id;
        setActiveSessionId(sessionId);
      }

      setMessages((current) => [
        ...current,
        localMessage("user", message),
        localMessage("assistant", "")
      ]);
      setInput("");
      setSending(true);

      await streamChat(message, sessionId, (packet: StreamPacket) => {
        if (packet.type === "meta") {
          setActiveSessionId(packet.session_id);
        } else if (packet.type === "delta") {
          setMessages((current) => {
            if (current.length === 0) return current;
            const copy = [...current];
            const last = copy[copy.length - 1];
            if (last.role === "assistant") {
              copy[copy.length - 1] = { ...last, content: last.content + packet.delta };
            }
            return copy;
          });
        } else if (packet.type === "error") {
          setMessages((current) => {
            const copy = [...current];
            const last = copy[copy.length - 1];
            if (last?.role === "assistant" && !last.content) {
              copy[copy.length - 1] = { ...last, content: packet.message };
            } else {
              copy.push(localMessage("assistant", packet.message));
            }
            return copy;
          });
        }
      });

      await refreshSessions();
    } catch (error) {
      if (error instanceof JarvisApiError && error.status === 403) {
        setState("jarvis.ready");
        setMessages((current) => [...current, localMessage("assistant", error.message)]);
      } else {
        setApiOnline(false);
        setState("jarvis.error");
        setMessages((current) => [
          ...current,
          localMessage("assistant", "Não consegui comunicar com a API local da JARVIS. A ligação será tentada novamente.")
        ]);
      }
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="appLayout">
      <div className={`sidebarWrap ${sidebarOpen ? "open" : ""}`}>
        <Sidebar
          sessions={sessions}
          activeSessionId={activeSessionId}
          onNew={startNewConversation}
          onSelect={(id) => void loadSession(id)}
          onRequestDelete={(session) => { setDeleteError(null); setPendingDelete(session); }}
          onRename={(id, title) => renameConversation(id, title)}
        />
      </div>

      {sidebarOpen && (
        <button className="sidebarBackdrop" aria-label="Fechar histórico" type="button" onClick={() => setSidebarOpen(false)} />
      )}

      <main className={`chatShell ${conversationActive ? "conversationOpen" : "idleShell"}`}>
        <JarvisCoreVisual ambient={conversationActive} />

        <header className="topbar">
          <div className="topbarLeft">
            <button className="menuButton" type="button" onClick={() => setSidebarOpen(true)} aria-label="Abrir conversas">☰</button>
            <div>
              <div className="eyebrow">ASSISTENTE LOCAL</div>
              <h1>JARVIS</h1>
              <div className="headerTagline">MAIS DO QUE IA. SEU ALIADO.</div>
            </div>
          </div>

          <div className="topControls">
            <div className="status">
              <span className={`statusDot ${apiOnline ? "online" : "offline"}`} />
              <span>{stateLabel}</span>
              <span className="modePill">LOCAL</span>
            </div>
            <button className="settingsButton" type="button" title="Definições — em preparação" aria-label="Definições" aria-disabled="true">
              <GearIcon />
            </button>
          </div>
        </header>

        <div className="heroCopy heroCopyLeft" aria-hidden="true">
          <span>PENSAR</span><span>PLANEJAR</span><span>CRIAR</span><span>JUNTOS</span><i />
        </div>
        <div className="heroCopy heroCopyRightTop" aria-hidden="true">
          <span>“TECNOLOGIA</span><span>A SERVIÇO DE UM MUNDO</span><span>MELHOR.”</span><i />
        </div>
        <div className="heroCopy heroCopyRightBottom" aria-hidden="true">
          <span>SEMPRE</span><span>AO SEU LADO</span><i />
        </div>

        <section className={`conversation ${conversationActive ? "hasMessages" : "idleConversation"}`} aria-live="polite">
          {authenticated === false ? (
            <div className="welcome lockedWelcome">
              <div className="lockGlyph">◆</div>
              <h2>Sessão local bloqueada</h2>
              <p>Esta sessão do browser não está autenticada. O acesso autenticado deve ser iniciado pelo Launcher/ProcessHost da JARVIS.</p>
            </div>
          ) : messages.length === 0 ? (
            <div className="welcome">
              <div className="welcomeSpacer" />
              <h2>Em que posso ajudar?</h2>
              <p>A sua JARVIS local. Privada, segura e sempre ao seu lado.</p>
            </div>
          ) : (
            <div className="conversationGlass">
              <div className="messageFlow">
                {messages.map((message) => (
                  <article className={`message ${message.role}`} key={message.id}>
                    <div className="messageAvatar" aria-hidden="true">{message.role === "user" ? "U" : "J"}</div>
                    <div className="messageBody">
                      <div className="role">{message.role === "user" ? "VOCÊ" : "JARVIS"}</div>
                      <div className="bubble">
                        <MessageContent content={message.content || (message.role === "assistant" && sending ? "…" : "")} />
                      </div>
                      {message.role === "assistant" && message.content && <MessageActions content={message.content} />}
                    </div>
                  </article>
                ))}
                <div ref={endRef} />
              </div>
              <div className="suggestionRow" aria-label="Sugestões de conversa">
                {suggestions.map(([icon, label]) => (
                  <button key={label} type="button" onClick={() => { setInput(label); inputRef.current?.focus(); }}>
                    <span>{icon}</span>{label}
                  </button>
                ))}
              </div>
            </div>
          )}
        </section>

        <form className="composer" onSubmit={sendMessage}>
          <button className="composerUtility" type="button" title="Anexos — em preparação" aria-label="Anexar ficheiro" aria-disabled="true">
            <AttachIcon />
          </button>
          <textarea
            ref={inputRef}
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="Fale com a JARVIS..."
            rows={1}
            disabled={sending || authenticated !== true}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
          />
          <button className="composerUtility micUtility" type="button" title="Voz — em preparação" aria-label="Microfone" aria-disabled="true">
            <MicIcon />
          </button>
          <button className="sendButton" disabled={sending || authenticated !== true || !input.trim()} type="submit" aria-label="Enviar">
            {sending ? <span className="sendingPulse">•••</span> : <SendIcon />}
          </button>
        </form>
        <div className="footerMotto">CONHECIMENTO <i /> PRODUTIVIDADE <i /> UM FUTURO MELHOR</div>
      </main>

      {pendingDelete && (
        <div className="modalBackdrop" role="presentation" onMouseDown={() => !deleting && setPendingDelete(null)}>
          <div className="confirmModal" role="dialog" aria-modal="true" aria-labelledby="delete-title" onMouseDown={(event) => event.stopPropagation()}>
            <div className="modalEyebrow">JARVIS · HISTÓRICO</div>
            <h2 id="delete-title">Eliminar esta conversa?</h2>
            <p><strong>{pendingDelete.title}</strong> será removida do histórico. Esta ação não pode ser anulada.</p>
            {deleteError && <div className="modalError" role="alert">{deleteError}</div>}
            <div className="modalActions">
              <button type="button" className="cancelButton" onClick={() => setPendingDelete(null)} disabled={deleting}>Cancelar</button>
              <button type="button" className="dangerButton" onClick={() => void confirmDelete()} disabled={deleting}>{deleting ? "A eliminar…" : "Eliminar"}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
