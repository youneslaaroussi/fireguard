import { Button, Dialog, Intent, Tag } from "@blueprintjs/core";
import Editor from "@monaco-editor/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { MapAnnotation } from "./types";
import {
  createSession,
  getEvents,
  getChatHistory,
  getLatestRun,
  getNodeDetail,
  getRun,
  listSessions,
  resolveApproval,
  restartChatFrom,
  startRun,
  startChatRun,
  stopRun,
  streamRun,
} from "./api";
import type {
  ApprovalRecord,
  ChatAnnotation,
  ChatAttachment,
  ChatMessage,
  EdgePayload,
  NodeDetail,
  SessionListItem,
  SessionRecord,
  StreamEvent,
  WorkflowRun,
} from "./types";
import { WorkflowGraph } from "./WorkflowGraph";
import "./styles.css";

const MAX_ATTACHMENT_BYTES = 100 * 1024 * 1024;
const TEXT_ATTACHMENT_TYPES = new Set([
  "application/json",
  "application/xml",
  "application/yaml",
  "text/csv",
  "text/markdown",
  "text/plain",
]);

function statusIntent(status: string): Intent {
  if (status === "completed") return Intent.SUCCESS;
  if (status === "failed" || status === "rejected") return Intent.DANGER;
  if (status === "waiting" || status === "waiting_for_approval") return Intent.WARNING;
  if (status === "running") return Intent.PRIMARY;
  return Intent.NONE;
}

function isActive(run: WorkflowRun | null): boolean {
  return run !== null && (run.status === "running" || run.status === "created" || run.status === "waiting_for_approval");
}

function isActivityEvent(event: StreamEvent): boolean {
  return (
    event.event_type === "tool.started" ||
    event.event_type === "tool.completed" ||
    event.event_type === "tool.failed" ||
    event.event_type === "subagent.started" ||
    event.event_type === "subagent.completed" ||
    event.event_type === "subagent.failed" ||
    event.event_type === "fleet.started" ||
    event.event_type === "fleet.child.started" ||
    event.event_type === "fleet.child.completed" ||
    event.event_type === "fleet.completed" ||
    event.event_type === "sandbox.starting" ||
    event.event_type === "sandbox.ready" ||
    event.event_type === "sandbox.failed" ||
    event.event_type === "sandbox.terminated" ||
    event.event_type === "project_data.starting" ||
    event.event_type === "project_data.ready" ||
    event.event_type === "project_data.failed" ||
    event.event_type === "workflow.node.failed" ||
    event.event_type === "workflow.error.routed" ||
    event.event_type === "workflow.handoff.created" ||
    event.event_type === "retry.scheduled"
  );
}

function agentLabel(agentId: string | null | undefined, nodeId: string | null | undefined): string {
  const id = agentId ?? nodeId;
  if (id === "chat_agent") return "Request Router";
  if (id === "research_agent" || id === "evacuation_research") return "Data Checks";
  if (id === "writer_agent" || id === "evacuation_writer") return "Evacuation Brief";
  if (id === "style_agent" || id === "evacuation_style") return "Brief Formatter";
  return id ?? "Agent";
}

function toolTitle(annotation: ChatAnnotation): string {
  const toolName = annotation.tool_name;
  if (typeof toolName === "string") return toolName;
  return annotation.type;
}

interface AskQuestion {
  id: string;
  question: string;
  options: string[];
}

function askQuestionsFromAnnotation(annotation: ChatAnnotation): AskQuestion[] {
  const raw =
    annotation.type === "tool.started"
      ? annotation.args?.questions
      : annotation.output?.questions;
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((item, index) => {
    if (item === null || typeof item !== "object" || Array.isArray(item)) return [];
    const payload = item as Record<string, unknown>;
    const question = payload.question;
    if (typeof question !== "string" || question.trim().length === 0) return [];
    const rawOptions = payload.options;
    const options = Array.isArray(rawOptions)
      ? rawOptions.filter((option): option is string => typeof option === "string" && option.trim().length > 0)
      : [];
    return [
      {
        id: typeof payload.id === "string" && payload.id.trim().length > 0 ? payload.id : `q${index + 1}`,
        question,
        options,
      },
    ];
  });
}

function askTitleFromAnnotation(annotation: ChatAnnotation): string {
  const source = annotation.type === "tool.started" ? annotation.args : annotation.output;
  const title = source?.title;
  return typeof title === "string" && title.trim().length > 0 ? title : "Clarify request";
}

function isTextAttachment(file: File): boolean {
  if (file.type.startsWith("text/")) return true;
  if (TEXT_ATTACHMENT_TYPES.has(file.type)) return true;
  return /\.(csv|json|log|md|txt|xml|yaml|yml)$/i.test(file.name);
}

async function readChatAttachment(file: File): Promise<ChatAttachment> {
  if (file.size > MAX_ATTACHMENT_BYTES) {
    throw new Error(`${file.name} is larger than 100 MB.`);
  }
  const dataUrl = await readFileDataUrl(file);
  const text = isTextAttachment(file) ? await file.text() : undefined;
  return {
    id: crypto.randomUUID(),
    name: file.name,
    media_type: file.type.length > 0 ? file.type : "application/octet-stream",
    size: file.size,
    data_url: dataUrl,
    text,
  };
}

function readFileDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") {
        resolve(reader.result);
      } else {
        reject(new Error(`Could not read ${file.name}.`));
      }
    };
    reader.onerror = () => reject(reader.error ?? new Error(`Could not read ${file.name}.`));
    reader.readAsDataURL(file);
  });
}

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

type AgenticIntelligenceAppProps = {
  autoPrompt?: string | null;
  workflowId?: string;
  sessionContext?: Record<string, unknown> | null;
  threat?: unknown;
  mode?: "full" | "overlay";
  onClose?: () => void;
  onAnnotation?: (annotation: MapAnnotation) => void;
};

export function AgenticIntelligenceApp({
  autoPrompt = null,
  workflowId = "fireguard_intelligence",
  sessionContext = null,
  threat = null,
  mode = "full",
  onClose,
  onAnnotation,
}: AgenticIntelligenceAppProps) {
  const [busy, setBusy] = useState(false);
  const [sessions, setSessions] = useState<SessionListItem[]>([]);
  const [currentSession, setCurrentSession] = useState<SessionRecord | null>(null);
  const [run, setRun] = useState<WorkflowRun | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [nodeDetail, setNodeDetail] = useState<NodeDetail | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [edgePayloadOpen, setEdgePayloadOpen] = useState(false);
  const [selectedEdgePayload, setSelectedEdgePayload] = useState<EdgePayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [approvalBusy, setApprovalBusy] = useState(false);
  const [chatInput, setChatInput] = useState("");
  const [chatAttachments, setChatAttachments] = useState<ChatAttachment[]>([]);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [edgePayloads, setEdgePayloads] = useState<Record<string, EdgePayload>>({});
  const [runEvents, setRunEvents] = useState<StreamEvent[]>([]);
  const sourceRef = useRef<EventSource | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const selectedNodeIdRef = useRef<string | null>(null);
  const modalOpenRef = useRef(false);
  const detailRefreshTimerRef = useRef<number | null>(null);
  const lastAutoPromptRef = useRef<string | null>(null);
  const onAnnotationRef = useRef(onAnnotation);

  useEffect(() => { onAnnotationRef.current = onAnnotation; }, [onAnnotation]);

  useEffect(() => {
    selectedNodeIdRef.current = selectedNodeId;
  }, [selectedNodeId]);

  useEffect(() => {
    modalOpenRef.current = modalOpen;
  }, [modalOpen]);

  const selectedNode = useMemo(() => {
    if (run === null || selectedNodeId === null) return null;
    return run.workflow.nodes.find((node) => node.node_id === selectedNodeId) ?? null;
  }, [run, selectedNodeId]);

  const pendingApproval = useMemo<ApprovalRecord | null>(() => {
    if (run === null || selectedNodeId === null || selectedNode?.config.kind !== "approval_gate") {
      return null;
    }
    return (
      Object.values(run.approvals).find(
        (approval) => approval.node_id === selectedNodeId && approval.status === "pending",
      ) ?? null
    );
  }, [run, selectedNode, selectedNodeId]);

  const transcript = useMemo(() => {
    if (nodeDetail === null) {
      return "Loading transcript...";
    }
    return JSON.stringify(
      {
        node: nodeDetail.node,
        state: nodeDetail.state,
        history: nodeDetail.history,
        transcript: nodeDetail.transcript,
        events: nodeDetail.events,
        trace: nodeDetail.trace,
      },
      null,
      2,
    );
  }, [nodeDetail]);

  const activityAnnotations = useMemo(
    () =>
      runEvents
        .filter(isActivityEvent)
        .map((event): ChatAnnotation => ({
          type: event.event_type,
          event_id: event.event_id,
          node_id: event.node_id,
          agent_id: event.agent_id,
          ...event.data,
        })),
    [runEvents],
  );

  const edgePayloadText = useMemo(() => {
    if (selectedEdgePayload === null) {
      return "{}";
    }
    return JSON.stringify(selectedEdgePayload, null, 2);
  }, [selectedEdgePayload]);

  const deriveEdgePayloads = useCallback((currentRun: WorkflowRun): Record<string, EdgePayload> => {
    const payloads: Record<string, EdgePayload> = {};
    for (const edge of currentRun.workflow.edges) {
      const targetState = currentRun.node_states[edge.to_node_id];
      const input = targetState?.input_payload;
      if (input === null || input === undefined) {
        continue;
      }
      payloads[edge.edge_id] = {
        from_node_id: edge.from_node_id,
        to_node_id: edge.to_node_id,
        condition: edge.condition,
        payload: input,
      };
    }
    return payloads;
  }, []);

  const deriveSubagentEdgePayloads = useCallback((events: StreamEvent[]): Record<string, EdgePayload> => {
    const payloads: Record<string, EdgePayload> = {};
    for (const event of events) {
      if (
        event.agent_id === null ||
        (event.event_type !== "subagent.completed" &&
          event.event_type !== "subagent.failed" &&
          event.event_type !== "fleet.child.completed")
      ) {
        continue;
      }
      const edgeId = `edge_research_agent_to_${event.agent_id}`;
      payloads[edgeId] = {
        from_node_id: "research_agent",
        to_node_id: event.agent_id,
        condition: event.event_type,
        payload: event.data,
      };
    }
    return payloads;
  }, []);

  const deriveToolEdgePayloads = useCallback((events: StreamEvent[]): Record<string, EdgePayload> => {
    const payloads: Record<string, EdgePayload> = {};
    for (const event of events) {
      if (
        event.agent_id === null ||
        (event.event_type !== "tool.started" &&
          event.event_type !== "tool.completed" &&
          event.event_type !== "tool.failed")
      ) {
        continue;
      }
      const toolName = event.data.tool_name;
      const invocationId = event.data.invocation_id;
      if (
        typeof invocationId !== "string" ||
        !isGraphTool(toolName)
      ) {
        continue;
      }
      const parentNodeId = event.node_id ?? event.agent_id;
      const toolNodeId = `tool_${parentNodeId}_${invocationId}`;
      const edgeId = `edge_${parentNodeId}_to_${toolNodeId}`;
      payloads[edgeId] = {
        from_node_id: parentNodeId,
        to_node_id: toolNodeId,
        condition: event.event_type,
        payload: event.data,
      };
    }
    return payloads;
  }, []);

  const mergeEdgePayloads = useCallback(
    (currentRun: WorkflowRun, events: StreamEvent[]) => ({
      ...deriveEdgePayloads(currentRun),
      ...deriveSubagentEdgePayloads(events),
      ...deriveToolEdgePayloads(events),
    }),
    [deriveEdgePayloads, deriveSubagentEdgePayloads, deriveToolEdgePayloads],
  );

  const refreshSessions = useCallback(async () => {
    const nextSessions = await listSessions();
    setSessions(nextSessions);
  }, []);

  const refreshRun = useCallback(async (currentRun: WorkflowRun) => {
    const fresh = await getRun(currentRun.session_id, currentRun.run_id);
    setRun(fresh);
    const events = await getEvents(fresh.session_id, fresh.run_id, true);
    setRunEvents(events);
    setEdgePayloads(mergeEdgePayloads(fresh, events));
    void refreshSessions();
  }, [mergeEdgePayloads, refreshSessions]);

  const refreshOpenNodeDetail = useCallback((currentRun: WorkflowRun, eventNodeId: string | null) => {
    const selected = selectedNodeIdRef.current;
    if (!modalOpenRef.current || selected === null || eventNodeId !== selected) {
      return;
    }
    if (detailRefreshTimerRef.current !== null) {
      window.clearTimeout(detailRefreshTimerRef.current);
    }
    detailRefreshTimerRef.current = window.setTimeout(() => {
      detailRefreshTimerRef.current = null;
      void getNodeDetail(currentRun.session_id, currentRun.run_id, selected, true)
        .then(setNodeDetail)
        .catch((caught: unknown) => {
          setError(caught instanceof Error ? caught.message : String(caught));
        });
    }, 150);
  }, []);

  const ensureAssistantMessage = useCallback((event: StreamEvent): string => {
    const id = `${event.run_id}:${event.agent_id ?? event.node_id ?? "assistant"}`;
    setChatMessages((messages) => {
      if (messages.some((message) => message.id === id)) {
        return messages;
      }
      return [
        ...messages,
        {
          id,
          role: "assistant",
          content: "",
          annotations: [],
          agent_id: event.agent_id,
          node_id: event.node_id,
          run_id: event.run_id,
        },
      ];
    });
    return id;
  }, []);

  const applyChatEvent = useCallback((event: StreamEvent) => {
    setRunEvents((events) => {
      if (events.some((item) => item.event_id === event.event_id)) {
        return events;
      }
      return [...events, event];
    });
    if (
      event.agent_id !== null &&
      (event.event_type === "subagent.completed" ||
        event.event_type === "subagent.failed" ||
        event.event_type === "fleet.child.completed")
    ) {
      const edgeId = `edge_research_agent_to_${event.agent_id}`;
      setEdgePayloads((current) => ({
        ...current,
        [edgeId]: {
          from_node_id: "research_agent",
          to_node_id: event.agent_id ?? edgeId,
          condition: event.event_type,
          payload: event.data,
        },
      }));
    }
    if (
      event.agent_id !== null &&
      (event.event_type === "tool.started" || event.event_type === "tool.completed" || event.event_type === "tool.failed")
    ) {
      const toolName = event.data.tool_name;
      const invocationId = event.data.invocation_id;
      if (
        typeof invocationId === "string" &&
        isGraphTool(toolName)
      ) {
        const parentNodeId = event.node_id ?? event.agent_id;
        const toolNodeId = `tool_${parentNodeId}_${invocationId}`;
        const edgeId = `edge_${parentNodeId}_to_${toolNodeId}`;
        setEdgePayloads((current) => ({
          ...current,
          [edgeId]: {
            from_node_id: parentNodeId ?? edgeId,
            to_node_id: toolNodeId,
            condition: event.event_type,
            payload: event.data,
          },
        }));
      }
    }
    if (event.event_type === "workflow.handoff.created") {
      const fromNodeId = event.data.from_node_id;
      const toNodeId = event.data.to_node_id;
      const condition = event.data.condition;
      const payload = event.data.payload;
      if (
        typeof fromNodeId === "string" &&
        typeof toNodeId === "string" &&
        typeof condition === "string" &&
        payload !== null &&
        typeof payload === "object" &&
        !Array.isArray(payload)
      ) {
        setEdgePayloads((current) => {
          const edge = run?.workflow.edges.find(
            (item) =>
              item.from_node_id === fromNodeId &&
              item.to_node_id === toNodeId &&
              item.condition === condition,
          );
          if (edge === undefined) {
            return current;
          }
          return {
            ...current,
            [edge.edge_id]: {
              from_node_id: fromNodeId,
              to_node_id: toNodeId,
              condition,
              payload: payload as Record<string, unknown>,
            },
          };
        });
      }
      return;
    }
    if (event.event_type === "tool.completed") {
      const toolName = event.data.tool_name;
      const output = event.data.output;
      if (toolName === "fireguard_map_annotation" && isObj(output) && output.ok === true) {
        const ann = (output as Record<string, unknown>).annotation;
        if (isObj(ann)) {
          onAnnotationRef.current?.(ann as unknown as MapAnnotation);
        }
      }
    }
    if (event.event_type === "agent.started") {
      ensureAssistantMessage(event);
      return;
    }
    if (event.event_type === "agent.message.delta") {
      const id = ensureAssistantMessage(event);
      const content = event.data.content;
      if (typeof content !== "string") return;
      setChatMessages((messages) =>
        messages.map((message) => (message.id === id ? { ...message, content: `${message.content}${content}` } : message)),
      );
      return;
    }
    if (event.event_type === "agent.message.completed") {
      const id = ensureAssistantMessage(event);
      const content = event.data.content;
      const structured = event.data.structured;
      const askAnnotation =
        structured !== null &&
        typeof structured === "object" &&
        !Array.isArray(structured) &&
        (structured as Record<string, unknown>).action === "ask_user"
          ? {
              type: "structured.ask_user",
              event_id: event.event_id,
              node_id: event.node_id,
              agent_id: event.agent_id,
              tool_name: "ask_user",
              output: {
                title: "Clarify request",
                questions: (structured as Record<string, unknown>).questions,
              },
            }
          : null;
      if (typeof content === "string") {
        setChatMessages((messages) => messages.map((message) => {
          if (message.id !== id) return message;
          if (askAnnotation === null) return { ...message, content };
          if (message.annotations.some((annotation) => annotation.event_id === event.event_id)) {
            return { ...message, content };
          }
          return { ...message, content, annotations: [...message.annotations, askAnnotation] };
        }));
      }
      return;
    }
  }, [ensureAssistantMessage, run]);

  const attachStream = useCallback(
    (currentRun: WorkflowRun) => {
      sourceRef.current?.close();
      sourceRef.current = streamRun(
        currentRun.session_id,
        currentRun.run_id,
        (event: StreamEvent) => {
          if (
            event.event_type === "workflow.node.started" ||
            event.event_type === "workflow.node.completed" ||
            event.event_type === "workflow.node.failed" ||
            event.event_type === "agent.message.completed" ||
            event.event_type === "approval.requested" ||
            event.event_type === "approval.resolved" ||
            event.event_type === "run.completed" ||
            event.event_type === "run.failed" ||
            event.event_type === "run.stopped"
          ) {
            void refreshRun(currentRun);
          }
          applyChatEvent(event);
          refreshOpenNodeDetail(currentRun, event.node_id);
        },
        () => {
          setError("Stream disconnected.");
        },
      );
    },
    [applyChatEvent, refreshOpenNodeDetail, refreshRun],
  );

  useEffect(() => {
    return () => {
      sourceRef.current?.close();
      if (detailRefreshTimerRef.current !== null) {
        window.clearTimeout(detailRefreshTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void refreshSessions().catch((caught: unknown) => {
        setError(caught instanceof Error ? caught.message : String(caught));
      });
    }, 0);
    return () => window.clearTimeout(timer);
  }, [refreshSessions]);

  async function handleNewSession() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      sourceRef.current?.close();
      const session = await createSession("FireGuard Intelligence Chat");
      setCurrentSession(session);
      setRun(null);
      setChatMessages([]);
      setEdgePayloads({});
      setRunEvents([]);
      setSelectedNodeId(null);
      setNodeDetail(null);
      setChatInput("");
      setChatAttachments([]);
      await refreshSessions();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function handleLoadSession(session: SessionListItem) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      sourceRef.current?.close();
      setCurrentSession(session);
      setSelectedNodeId(null);
      setNodeDetail(null);
      setChatInput("");
      setChatAttachments([]);
      const latest = await getLatestRun(session.session_id);
      if (latest === null) {
        setRun(null);
        setChatMessages([]);
        setEdgePayloads({});
        setRunEvents([]);
        return;
      }
      const events = await getEvents(latest.session_id, latest.run_id, true);
      setRun(latest);
      setRunEvents(events);
      setEdgePayloads(mergeEdgePayloads(latest, events));
      await reloadChatHistory(latest);
      if (isActive(latest)) {
        attachStream(latest);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function handleAttachmentFiles(files: FileList | null) {
    if (files === null || files.length === 0) return;
    setError(null);
    try {
      const nextAttachments = await Promise.all(Array.from(files).map(readChatAttachment));
      setChatAttachments((current) => [...current, ...nextAttachments]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      if (fileInputRef.current !== null) {
        fileInputRef.current.value = "";
      }
    }
  }

  function removeAttachment(id: string) {
    setChatAttachments((current) => current.filter((attachment) => attachment.id !== id));
  }

  async function sendChatMessage(messageText: string, attachments: ChatAttachment[] = []) {
    const message = messageText.trim();
    if ((message.length === 0 && attachments.length === 0) || isActive(run) || busy) return;
    setBusy(true);
    setError(null);
    setNodeDetail(null);
    setSelectedNodeId(null);
    try {
      sourceRef.current?.close();
      const session =
        currentSession ??
        (run === null
          ? await createSession(message.slice(0, 48) || "FireGuard Intelligence Chat")
          : { session_id: run.session_id, title: "FireGuard Intelligence Chat", created_at: "", updated_at: "", metadata: {} });
      const prompt = message.length > 0 ? message : "Analyze the attached file(s).";
      const started =
        workflowId === "fireguard_intelligence"
          ? await startChatRun(session.session_id, prompt, attachments, sessionContext)
          : await startRun(session.session_id, prompt, workflowId, {
              source: "replay_threat",
              attachments,
              session_context: sessionContext,
              threat,
            });
      const events = await getEvents(started.session_id, started.run_id, true);
      setCurrentSession(session);
      setRun(started);
      setRunEvents(events);
      setEdgePayloads(mergeEdgePayloads(started, events));
      setChatMessages((messages) => [
        ...messages,
        {
          id: `user:${started.run_id}`,
          role: "user",
          content: prompt,
          attachments,
          annotations: [],
          run_id: started.run_id,
          node_id: "human_trigger",
        },
      ]);
      attachStream(started);
      await refreshSessions();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function handleSendChat() {
    const attachments = chatAttachments;
    const message = chatInput.trim();
    if ((message.length === 0 && attachments.length === 0) || isActive(run) || busy) return;
    setChatInput("");
    setChatAttachments([]);
    await sendChatMessage(message, attachments);
  }

  useEffect(() => {
    if (autoPrompt === null || autoPrompt.trim().length === 0) return;
    if (lastAutoPromptRef.current === autoPrompt) return;
    if (busy || isActive(run)) return;
    lastAutoPromptRef.current = autoPrompt;
    setChatInput(autoPrompt);
    void sendChatMessage(autoPrompt);
  }, [autoPrompt, busy, run]);

  async function reloadChatHistory(currentRun: WorkflowRun) {
    const history = await getChatHistory(currentRun.session_id, currentRun.run_id, true);
    setChatMessages(history.messages);
  }

  async function handleRestartFrom(message: ChatMessage) {
    if (run === null) return;
    setBusy(true);
    setError(null);
    try {
      sourceRef.current?.close();
      const eventId = message.annotations.at(-1)?.event_id ?? null;
      const nodeId = message.node_id ?? message.agent_id ?? null;
      const restarted = await restartChatFrom(run.session_id, run.run_id, nodeId, eventId ?? null, null);
      const events = await getEvents(restarted.session_id, restarted.run_id, true);
      setRun(restarted);
      setRunEvents(events);
      setEdgePayloads(mergeEdgePayloads(restarted, events));
      await reloadChatHistory(restarted);
      attachStream(restarted);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function handleRestartFromNode(nodeId: string) {
    if (run === null) return;
    setBusy(true);
    setError(null);
    try {
      sourceRef.current?.close();
      const restarted = await restartChatFrom(run.session_id, run.run_id, nodeId, null, null);
      const events = await getEvents(restarted.session_id, restarted.run_id, true);
      setRun(restarted);
      setRunEvents(events);
      setEdgePayloads(mergeEdgePayloads(restarted, events));
      await reloadChatHistory(restarted);
      attachStream(restarted);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function handleStopRun() {
    if (run === null) return;
    setBusy(true);
    setError(null);
    try {
      sourceRef.current?.close();
      const stopped = await stopRun(run.session_id, run.run_id);
      const events = await getEvents(stopped.session_id, stopped.run_id, true);
      setRun(stopped);
      setRunEvents(events);
      setEdgePayloads(mergeEdgePayloads(stopped, events));
      await refreshSessions();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function handleSelectNode(nodeId: string) {
    if (run === null) return;
    if (!run.workflow.nodes.some((node) => node.node_id === nodeId)) return;
    setSelectedNodeId(nodeId);
    setNodeDetail(null);
    setModalOpen(true);
    try {
      setNodeDetail(await getNodeDetail(run.session_id, run.run_id, nodeId, true));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  async function handleResolveApproval(approve: boolean) {
    if (run === null || pendingApproval === null || selectedNodeId === null) return;
    setApprovalBusy(true);
    setError(null);
    try {
      const updated = await resolveApproval(pendingApproval, approve, approve ? "Approved in UI." : "Rejected in UI.");
      const events = await getEvents(updated.session_id, updated.run_id, true);
      setRun(updated);
      setRunEvents(events);
      setEdgePayloads(mergeEdgePayloads(updated, events));
      attachStream(updated);
      setNodeDetail(await getNodeDetail(updated.session_id, updated.run_id, selectedNodeId, true));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setApprovalBusy(false);
    }
  }

  function handleSelectEdge(edgeId: string) {
    const payload = edgePayloads[edgeId];
    if (payload === undefined) {
      const edge = run?.workflow.edges.find((item) => item.edge_id === edgeId);
      if (edge === undefined) return;
      setSelectedEdgePayload({
        from_node_id: edge.from_node_id,
        to_node_id: edge.to_node_id,
        condition: edge.condition,
        payload: {},
      });
    } else {
      setSelectedEdgePayload(payload);
    }
    setEdgePayloadOpen(true);
  }

  return (
    <div className={`agenticIntelligence agenticIntelligence--${mode} app-shell bp6-dark`}>
      <header className="topbar">
        <div className="brand">
          <h1>FireGuard Intelligence</h1>
          {run !== null && <Tag intent={statusIntent(run.status)}>{run.status}</Tag>}
        </div>
        <div className="topbar-actions">
          <Button
            icon="stop"
            text="Stop"
            intent={Intent.DANGER}
            disabled={!isActive(run) || busy}
            onClick={() => void handleStopRun()}
          />
          {mode === "overlay" && onClose !== undefined && (
            <Button icon="cross" minimal title="Close" onClick={onClose} />
          )}
        </div>
      </header>

      {error !== null && <div className="error-banner">{error}</div>}

      {mode === "full" && (
        <aside className="sessions-panel">
          <div className="sessions-header">
            <strong>Sessions</strong>
            <Button small icon="plus" text="New" loading={busy && run === null} onClick={() => void handleNewSession()} />
          </div>
          <div className="sessions-list">
            {sessions.length === 0 ? (
              <div className="empty-sessions">No sessions yet.</div>
            ) : (
              sessions.map((session) => {
                const active = currentSession?.session_id === session.session_id || run?.session_id === session.session_id;
                return (
                  <button
                    key={session.session_id}
                    className={active ? "session-item active" : "session-item"}
                    type="button"
                    disabled={busy}
                    onClick={() => void handleLoadSession(session)}
                  >
                    <span className="session-title">{session.title}</span>
                    <span className="session-meta">
                      {session.latest_run === null ? "No runs" : `${session.latest_run.status} - ${session.latest_run.run_id.slice(0, 12)}`}
                    </span>
                  </button>
                );
              })
            )}
          </div>
        </aside>
      )}

      <main className="workspace">
        <div className="graph-only">
          <WorkflowGraph
            run={run}
            selectedNodeId={selectedNodeId}
            edgePayloads={edgePayloads}
            events={runEvents}
            onSelectNode={(nodeId) => void handleSelectNode(nodeId)}
            onSelectEdge={handleSelectEdge}
            onRestartFromNode={isActive(run) || busy ? null : (nodeId) => void handleRestartFromNode(nodeId)}
          />
        </div>
      </main>

      <aside className="chat-panel">
        <section className="chat-tab">
          <div className="chat-messages">
            {chatMessages.length === 0 ? (
              <div className="empty-chat">Agent output appears here.</div>
            ) : (
              chatMessages.map((message) => (
                <article key={message.id} className={`chat-message ${message.role}`}>
                  <div className="message-meta">
                    <span>{message.role === "user" ? "You" : agentLabel(message.agent_id, message.node_id)}</span>
                    {message.role === "assistant" && (
                      <Button
                        small
                        minimal
                        icon="reset"
                        text="Restart"
                        disabled={busy || isActive(run)}
                        onClick={() => void handleRestartFrom(message)}
                      />
                    )}
                  </div>
                  <div className="message-content">
                    {message.content.length > 0 ? (
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {message.content}
                      </ReactMarkdown>
                    ) : (
                      "..."
                    )}
                  </div>
                  {message.attachments !== undefined && message.attachments.length > 0 && (
                    <div className="message-attachments">
                      {message.attachments.map((attachment) => (
                        <span key={attachment.id} className="attachment-chip readonly">
                          {attachment.name}
                          <small>{formatBytes(attachment.size)}</small>
                        </span>
                      ))}
                    </div>
                  )}
                  {message.annotations.length > 0 && (
                    <div className="message-tools">
                      {message.annotations.map((annotation, index) => (
                        <ToolCard
                          key={`${message.id}:${index}`}
                          annotation={annotation}
                          disabled={busy || isActive(run)}
                          onAskSubmit={(content) => void sendChatMessage(content)}
                        />
                      ))}
                    </div>
                  )}
                </article>
              ))
            )}
          </div>
          <div className="chat-input-row">
            <input
              ref={fileInputRef}
              className="file-input"
              type="file"
              multiple
              accept="image/*,.pdf,.txt,.md,.csv,.json,.xml,.yaml,.yml,text/*,application/pdf,application/json"
              onChange={(event) => void handleAttachmentFiles(event.target.files)}
            />
            <Button
              icon="upload"
              title="Attach files"
              disabled={isActive(run) || busy}
              onClick={() => fileInputRef.current?.click()}
            />
            <textarea
              value={chatInput}
              placeholder="Message FireGuard..."
              rows={2}
              onChange={(event) => setChatInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void handleSendChat();
                }
              }}
            />
            <Button
              intent={Intent.PRIMARY}
              icon="send-message"
              disabled={(chatInput.trim().length === 0 && chatAttachments.length === 0) || isActive(run) || busy}
              onClick={() => void handleSendChat()}
            />
          </div>
          {chatAttachments.length > 0 && (
            <div className="composer-attachments">
              {chatAttachments.map((attachment) => (
                <button
                  key={attachment.id}
                  className="attachment-chip"
                  type="button"
                  onClick={() => removeAttachment(attachment.id)}
                  title="Remove attachment"
                >
                  {attachment.name}
                  <small>{formatBytes(attachment.size)}</small>
                </button>
              ))}
            </div>
          )}
        </section>
      </aside>

      <Dialog
        className="transcript-dialog"
        title={selectedNode === null ? "Transcript" : `${selectedNode.label} Transcript`}
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
      >
        {pendingApproval !== null && (
          <div className="approval-actions">
            <div className="approval-copy">
              <strong>{pendingApproval.title}</strong>
              <span>{pendingApproval.instructions}</span>
            </div>
            <div className="approval-buttons">
              <Button
                icon="cross"
                intent={Intent.DANGER}
                text="Reject"
                loading={approvalBusy}
                onClick={() => void handleResolveApproval(false)}
              />
              <Button
                icon="tick"
                intent={Intent.SUCCESS}
                text="Approve"
                loading={approvalBusy}
                onClick={() => void handleResolveApproval(true)}
              />
            </div>
          </div>
        )}
        <div className="transcript-editor">
          <Editor
            language="json"
            theme="vs-dark"
            value={transcript}
            options={{
              readOnly: true,
              minimap: { enabled: false },
              wordWrap: "on",
              fontSize: 12,
              scrollBeyondLastLine: false,
              automaticLayout: true,
            }}
          />
        </div>
      </Dialog>

      <Dialog
        className="transcript-dialog"
        title={
          selectedEdgePayload === null
            ? "Handoff Payload"
            : `${selectedEdgePayload.from_node_id} -> ${selectedEdgePayload.to_node_id}`
        }
        isOpen={edgePayloadOpen}
        onClose={() => setEdgePayloadOpen(false)}
      >
        <div className="transcript-editor">
          <Editor
            language="json"
            theme="vs-dark"
            value={edgePayloadText}
            options={{
              readOnly: true,
              minimap: { enabled: false },
              wordWrap: "on",
              fontSize: 12,
              scrollBeyondLastLine: false,
              automaticLayout: true,
            }}
          />
        </div>
      </Dialog>
    </div>
  );
}

function isObj(v: unknown): v is Record<string, unknown> {
  return v !== null && typeof v === "object" && !Array.isArray(v);
}

function isGraphTool(toolName: unknown): boolean {
  return (
    toolName === "exa_search" ||
    (typeof toolName === "string" &&
      (toolName.startsWith("sandbox_") || toolName.startsWith("fireguard_")))
  );
}

function ToolCard({
  annotation,
  expanded = false,
  disabled = false,
  onAskSubmit,
}: {
  annotation: ChatAnnotation;
  expanded?: boolean;
  disabled?: boolean;
  onAskSubmit?: (content: string) => void;
}) {
  if (annotation.tool_name === "ask_user") {
    if (annotation.type === "tool.completed") {
      return null;
    }
    return <AskToolSheet annotation={annotation} disabled={disabled} onSubmit={onAskSubmit} />;
  }
  const ok = annotation.ok;
  const failed = annotation.type.includes("failed") || ok === false;
  const running = annotation.type === "tool.started" || annotation.type === "retry.scheduled";
  return (
    <details className={`tool-card ${failed ? "failed" : running ? "running" : "done"}`} open={expanded || failed}>
      <summary>
        <span>{toolTitle(annotation)}</span>
        <code>{annotation.type}</code>
      </summary>
      <pre>{JSON.stringify(annotation, null, 2)}</pre>
    </details>
  );
}

function AskToolSheet({
  annotation,
  disabled,
  onSubmit,
}: {
  annotation: ChatAnnotation;
  disabled: boolean;
  onSubmit?: (content: string) => void;
}) {
  const questions = askQuestionsFromAnnotation(annotation);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [otherAnswers, setOtherAnswers] = useState<Record<string, string>>({});

  if (questions.length === 0) {
    return <ToolCard annotation={{ ...annotation, tool_name: "ask_user_raw" }} expanded />;
  }

  const canSubmit = questions.every((question) => {
    const answer = answers[question.id];
    if (answer === "Other") {
      return (otherAnswers[question.id] ?? "").trim().length > 0;
    }
    return typeof answer === "string" && answer.trim().length > 0;
  });

  function submitAnswers() {
    const lines = ["Clarification answers:"];
    for (const question of questions) {
      const selected = answers[question.id];
      const answer = selected === "Other" ? otherAnswers[question.id] ?? "" : selected ?? "";
      lines.push(`- ${question.question}: ${answer.trim()}`);
    }
    onSubmit?.(lines.join("\n"));
  }

  return (
    <section className="ask-sheet">
      <div className="ask-sheet-header">
        <strong>{askTitleFromAnnotation(annotation)}</strong>
        <code>{annotation.type}</code>
      </div>
      <div className="ask-questions">
        {questions.map((question) => {
          const options = [...question.options, "Other"];
          return (
            <fieldset key={question.id} className="ask-question">
              <legend>{question.question}</legend>
              <div className="ask-options">
                {options.map((option) => (
                  <label key={option} className="ask-option">
                    <input
                      type="radio"
                      name={`${annotation.event_id ?? "ask"}:${question.id}`}
                      value={option}
                      checked={answers[question.id] === option}
                      onChange={() => setAnswers((current) => ({ ...current, [question.id]: option }))}
                    />
                    <span>{option}</span>
                  </label>
                ))}
              </div>
              {answers[question.id] === "Other" && (
                <textarea
                  className="ask-other-input"
                  rows={2}
                  value={otherAnswers[question.id] ?? ""}
                  placeholder="Type your answer..."
                  onChange={(event) =>
                    setOtherAnswers((current) => ({ ...current, [question.id]: event.target.value }))
                  }
                />
              )}
            </fieldset>
          );
        })}
      </div>
      <Button
        intent={Intent.PRIMARY}
        icon="send-message"
        text="Submit answers"
        disabled={disabled || !canSubmit}
        onClick={submitAnswers}
      />
    </section>
  );
}
