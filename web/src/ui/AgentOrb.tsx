import { useCallback, useEffect, useRef, useState } from "react";
import {
  createSession,
  getChatHistory,
  getLatestRun,
  listSessions,
  startChatRun,
  streamRun,
} from "../intelligence/api";
import type {
  ChatMessage,
  SessionListItem,
  StreamEvent,
  WorkflowRun,
} from "../intelligence/types";
import { WorkflowPanel } from "./WorkflowPanel";

type Props = {
  sessionContext?: Record<string, unknown> | null;
};

export function AgentOrb({ sessionContext = null }: Props) {
  const [historyOpen, setHistoryOpen] = useState(false);
  const [graphOpen, setGraphOpen] = useState(false);
  const [sessions, setSessions] = useState<SessionListItem[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [run, setRun] = useState<WorkflowRun | null>(null);
  const [rawEvents, setRawEvents] = useState<StreamEvent[]>([]);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sourceRef = useRef<EventSource | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  const runActive =
    run !== null &&
    (run.status === "running" || run.status === "created" || run.status === "waiting_for_approval");

  const hasMessages = chatMessages.length > 0;

  // Auto-open history when messages arrive
  useEffect(() => {
    if (chatMessages.length > 0) setHistoryOpen(true);
  }, [chatMessages.length]);

  // Auto-open workflow panel when run becomes active
  useEffect(() => {
    if (runActive) setGraphOpen(true);
  }, [runActive]);

  // Auto-scroll on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages]);

  // Load session list on first render
  useEffect(() => {
    listSessions().then(setSessions).catch(() => {});
  }, []);

  useEffect(() => () => { sourceRef.current?.close(); }, []);

  const attachStream = useCallback((currentRun: WorkflowRun) => {
    sourceRef.current?.close();
    sourceRef.current = streamRun(
      currentRun.session_id,
      currentRun.run_id,
      (event: StreamEvent) => {
        // Collect all raw events for the workflow graph
        setRawEvents((evs) => [...evs, event]);

        const msgId = `${event.run_id}:${event.agent_id ?? event.node_id ?? "assistant"}`;
        if (event.event_type === "agent.started") {
          setChatMessages((msgs) => {
            if (msgs.some((m) => m.id === msgId)) return msgs;
            return [
              ...msgs,
              { id: msgId, role: "assistant", content: "", annotations: [], agent_id: event.agent_id, node_id: event.node_id, run_id: event.run_id },
            ];
          });
        } else if (event.event_type === "agent.message.delta") {
          const chunk = event.data.content;
          if (typeof chunk === "string") {
            setChatMessages((msgs) =>
              msgs.map((m) => m.id === msgId ? { ...m, content: `${m.content}${chunk}` } : m)
            );
          }
        } else if (event.event_type === "agent.message.completed") {
          const full = event.data.content;
          if (typeof full === "string") {
            setChatMessages((msgs) =>
              msgs.map((m) => m.id === msgId ? { ...m, content: full } : m)
            );
          }
        } else if (
          event.event_type === "run.completed" ||
          event.event_type === "run.failed" ||
          event.event_type === "run.stopped"
        ) {
          void getLatestRun(currentRun.session_id).then((latest) => {
            if (latest !== null) setRun(latest);
          });
          listSessions().then(setSessions).catch(() => {});
        }
      },
      () => setError("Stream disconnected.")
    );
  }, []);

  async function handleLoadSession(session: SessionListItem) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      sourceRef.current?.close();
      setSessionId(session.session_id);
      const latest = await getLatestRun(session.session_id);
      if (latest === null) {
        setRun(null);
        setChatMessages([]);
        return;
      }
      setRun(latest);
      setRawEvents([]);
      const history = await getChatHistory(latest.session_id, latest.run_id, true);
      setChatMessages(history.messages);
      const stillActive =
        latest.status === "running" ||
        latest.status === "created" ||
        latest.status === "waiting_for_approval";
      if (stillActive) attachStream(latest);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleNewSession() {
    if (busy) return;
    sourceRef.current?.close();
    setSessionId(null);
    setRun(null);
    setChatMessages([]);
    setRawEvents([]);
    setHistoryOpen(false);
    setError(null);
  }

  async function handleSend() {
    const message = chatInput.trim();
    if (!message || runActive || busy) return;
    setChatInput("");
    setBusy(true);
    setError(null);
    try {
      sourceRef.current?.close();
      let sid = sessionId;
      if (sid === null) {
        const session = await createSession(message.slice(0, 48) || "FireGuard Chat");
        sid = session.session_id;
        setSessionId(sid);
      }
      const started = await startChatRun(sid, message, [], sessionContext);
      setRun(started);
      setChatMessages((msgs) => [
        ...msgs,
        {
          id: `user:${started.run_id}`,
          role: "user" as const,
          content: message,
          annotations: [],
          run_id: started.run_id,
          node_id: "human_trigger",
        },
      ]);
      attachStream(started);
      listSessions().then(setSessions).catch(() => {});
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
      inputRef.current?.focus();
    }
  }

  return (
    <>
      {/* Floating workflow panel — right side */}
      {graphOpen && (
        <WorkflowPanel
          run={run}
          events={rawEvents}
          onClose={() => setGraphOpen(false)}
        />
      )}

    <div className={`agentBar${runActive ? " agentBar--active" : ""}`}>
      {/* History panel — slides up above the bar */}
      {historyOpen && hasMessages && (
        <div className="agentHistory">
          {/* Session chips */}
          <div className="agentSessionRow">
            <button className="agentSessionChip" onClick={() => void handleNewSession()} disabled={busy}>
              + NEW
            </button>
            {sessions.slice(0, 8).map((session) => (
              <button
                key={session.session_id}
                className={`agentSessionChip${sessionId === session.session_id || run?.session_id === session.session_id ? " active" : ""}`}
                onClick={() => void handleLoadSession(session)}
                disabled={busy}
                title={session.title}
              >
                {session.title.slice(0, 28)}
              </button>
            ))}
          </div>

          {error && <div className="agentError">{error}</div>}

          {/* Messages */}
          <div className="agentMessages">
            {chatMessages.map((msg) => (
              <div key={msg.id} className={`agentMsg agentMsg--${msg.role}`}>
                <span className="agentMsgRole">{msg.role === "user" ? "YOU" : "AGENT"}</span>
                <span className="agentMsgContent">{msg.content || "…"}</span>
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>
        </div>
      )}

      {/* Input row — always visible */}
      <div className="agentInputRow">
        {hasMessages && (
          <button
            className={`agentHistoryToggle${historyOpen ? " active" : ""}`}
            onClick={() => setHistoryOpen((v) => !v)}
            title={historyOpen ? "Hide history" : "Show history"}
          >
            {historyOpen ? "▾" : "▴"} {chatMessages.length}
          </button>
        )}
        <textarea
          ref={inputRef}
          className="agentInput"
          value={chatInput}
          placeholder={runActive ? "Agent is thinking…" : "Ask FireGuard Intelligence…"}
          rows={1}
          disabled={runActive || busy}
          onChange={(e) => setChatInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void handleSend();
            }
          }}
        />
        <button
          className="agentSendBtn"
          disabled={!chatInput.trim() || runActive || busy}
          onClick={() => void handleSend()}
        >
          {busy || runActive ? "▪▪" : "↑"}
        </button>

        {/* Workflow graph toggle */}
        {run !== null && (
          <button
            className={`agentGraphBtn${graphOpen ? " active" : ""}${runActive ? " agentGraphBtn--live" : ""}`}
            onClick={() => setGraphOpen((v) => !v)}
            title="Workflow graph"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
              <circle cx="7" cy="2" r="1.5" fill="currentColor"/>
              <circle cx="2" cy="10" r="1.5" fill="currentColor"/>
              <circle cx="12" cy="10" r="1.5" fill="currentColor"/>
              <line x1="7" y1="3.5" x2="2" y2="8.5"  stroke="currentColor" strokeWidth="1"/>
              <line x1="7" y1="3.5" x2="12" y2="8.5" stroke="currentColor" strokeWidth="1"/>
              <line x1="2" y1="10" x2="12" y2="10"   stroke="currentColor" strokeWidth="1"/>
            </svg>
          </button>
        )}
      </div>
    </div>
    </>
  );
}
