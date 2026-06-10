import { Button, Dialog, Intent, SegmentedControl, Tab, Tabs, Tag } from "@blueprintjs/core";
import Editor from "@monaco-editor/react";
import { isValidElement, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import rehypeKatex from "rehype-katex";
import ReactMarkdown from "react-markdown";
import remarkDirective from "remark-directive";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import "katex/dist/katex.min.css";
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

type WorkspaceTabId = "graph" | "deliverable" | "report";
type ReportStyleId = "risk" | "atlas" | "technical" | "brief";

const REPORT_STYLE_OPTIONS = [
  { label: "Risk", value: "risk" },
  { label: "Map", value: "atlas" },
  { label: "Technical", value: "technical" },
  { label: "Brief", value: "brief" },
];

interface ReportHeading {
  depth: number;
  number: string | null;
  title: string;
}

interface ReportParts {
  title: string;
  subtitle: string | null;
  bodyMarkdown: string;
  headings: ReportHeading[];
}

interface ReportBodyPage {
  id: string;
  markdown: string;
}

const REPORT_BODY_PAGE_TARGET_UNITS = 86;
const REPORT_MAJOR_SECTION_BREAK_UNITS = 42;

function remarkReportDirectives() {
  return (tree: unknown) => {
    function walk(node: unknown) {
      if (node === null || typeof node !== "object") return;
      const current = node as Record<string, unknown>;
      if (current.type === "containerDirective" || current.type === "leafDirective") {
        const data = (current.data ?? (current.data = {})) as Record<string, unknown>;
        data.hName = "div";
        data.hProperties = {
          className: `report-directive report-directive-${String(current.name)}`,
        };
      }
      if (Array.isArray(current.children)) {
        for (const child of current.children) walk(child);
      }
    }
    walk(tree);
  };
}

function normalizeMathMarkdown(markdown: string): string {
  return markdown
    .replace(/\\\[([\s\S]*?)\\\]/g, (_, math: string) => `\n\n$$\n${math.trim()}\n$$\n\n`)
    .replace(/\\\(([\s\S]*?)\\\)/g, (_, math: string) => `$${math.trim()}$`)
    .replace(/^\s*\[\s*(.*\\[A-Za-z][^\n]*)\s*\]\s*$/gm, (_, math: string) => `\n\n$$\n${math.trim()}\n$$\n\n`)
    .replace(/\(\s*([^()\n]*\\[A-Za-z][^()\n]*)\s*\)/g, (_, math: string) => `$${math.trim()}$`)
    .replace(/\[\s*([^\]\n]*\\[A-Za-z][^\]\n]*)\s*\]/g, (_, math: string) => `$${math.trim()}$`);
}

function stripMarkdownHeading(line: string): string {
  return line
    .replace(/^#{1,6}\s+/, "")
    .replace(/\*\*/g, "")
    .replace(/__/g, "")
    .trim();
}

function splitNumberedHeading(text: string): { number: string; title: string } | null {
  const match = text.trim().match(/^(\d+(?:\.\d+)*)(?:[.)])?\s+(.+)$/);
  if (match === null) return null;
  return { number: match[1], title: match[2].trim() };
}

function isPlainSectionHeading(line: string): boolean {
  const trimmed = line.trim();
  if (trimmed.length < 4 || trimmed.length > 82) return false;
  if (!/[A-Za-z]/.test(trimmed)) return false;
  if (/^[#>*\-+`|]/.test(trimmed)) return false;
  if (/[.!?:;,]$/.test(trimmed)) return false;
  if (/^\d/.test(trimmed)) return false;
  const words = trimmed.split(/\s+/);
  if (words.length > 8) return false;
  return words.some((word) => /^[A-Z0-9]/.test(word));
}

function normalizeReportStructure(markdown: string): string {
  const lines = normalizeMathMarkdown(markdown).split("\n");
  let insideFence = false;
  return lines
    .map((line) => {
      const trimmed = line.trim();
      if (trimmed.startsWith("```")) {
        insideFence = !insideFence;
        return line;
      }
      if (insideFence || trimmed.length === 0 || /^#{1,6}\s+/.test(trimmed)) {
        return line;
      }
      const numbered = splitNumberedHeading(trimmed);
      if (numbered !== null) {
        const level = numbered.number.includes(".") ? "###" : "##";
        return `${level} ${numbered.number} ${numbered.title}`;
      }
      if (isPlainSectionHeading(trimmed)) {
        return `## ${trimmed}`;
      }
      return line;
    })
    .join("\n");
}

function extractReportParts(markdown: string, language: "markdown" | "json"): ReportParts {
  if (language === "json") {
    return {
      title: "Structured FireGuard Output",
      subtitle: "JSON fallback",
      bodyMarkdown: `\`\`\`json\n${markdown}\n\`\`\``,
      headings: [],
    };
  }

  const normalized = normalizeReportStructure(markdown.trim());
  const lines = normalized.split("\n");
  let firstContentIndex = lines.findIndex((line) => line.trim().length > 0);
  if (firstContentIndex === -1) {
    return { title: "FireGuard Intelligence", subtitle: null, bodyMarkdown: "", headings: [] };
  }

  const firstLine = lines[firstContentIndex].trim();
  const title = stripMarkdownHeading(firstLine).length > 0 ? stripMarkdownHeading(firstLine) : "FireGuard Intelligence";
  lines.splice(firstContentIndex, 1);

  firstContentIndex = lines.findIndex((line) => line.trim().length > 0);
  const subtitleCandidate = firstContentIndex === -1 ? "" : stripMarkdownHeading(lines[firstContentIndex]);
  const subtitle =
    subtitleCandidate.length > 0 &&
    subtitleCandidate.length < 80 &&
    subtitleCandidate === subtitleCandidate.toUpperCase()
      ? subtitleCandidate
      : null;
  if (subtitle !== null && firstContentIndex !== -1) {
    lines.splice(firstContentIndex, 1);
  }

  const bodyMarkdown = lines.join("\n").trim();
  const headings = bodyMarkdown
    .split("\n")
    .flatMap((line): ReportHeading[] => {
      const match = line.match(/^(#{1,3})\s+(.+)$/);
      if (match === null) return [];
      const text = stripMarkdownHeading(match[2]);
      const numbered = splitNumberedHeading(text);
      return [
        {
          depth: match[1].length,
          number: numbered?.number ?? null,
          title: numbered?.title ?? text,
        },
      ];
    })
    .slice(0, 12);

  return { title, subtitle, bodyMarkdown, headings };
}

function splitMarkdownBlocks(markdown: string): string[] {
  const blocks: string[] = [];
  const current: string[] = [];
  let insideFence = false;
  let insideContainerDirective = false;

  function flush() {
    const block = current.join("\n").trim();
    if (block.length > 0) {
      blocks.push(block);
    }
    current.length = 0;
  }

  for (const line of markdown.split("\n")) {
    const trimmed = line.trim();

    if (/^(```|~~~)/.test(trimmed)) {
      current.push(line);
      insideFence = !insideFence;
      continue;
    }

    if (!insideFence && /^::pagebreak\s*$/.test(trimmed)) {
      flush();
      blocks.push(trimmed);
      continue;
    }

    if (!insideFence && /^:::[A-Za-z][\w-]*(?:\s+.*)?$/.test(trimmed)) {
      flush();
      current.push(line);
      insideContainerDirective = true;
      continue;
    }

    if (!insideFence && insideContainerDirective) {
      current.push(line);
      if (trimmed === ":::") {
        insideContainerDirective = false;
        flush();
      }
      continue;
    }

    if (!insideFence && trimmed.length === 0) {
      flush();
      continue;
    }

    current.push(line);
  }

  flush();
  return blocks;
}

function extractPageBreakRemainder(block: string): string | null {
  const trimmed = block.trim();
  if (/^::pagebreak\s*$/.test(trimmed)) return "";

  const lines = block.split("\n");
  if (!/^:::pagebreak\s*$/.test(lines[0]?.trim() ?? "")) return null;

  const remainderLines = lines.slice(1);
  if (remainderLines.at(-1)?.trim() === ":::") {
    remainderLines.pop();
  }
  return remainderLines.join("\n").trim();
}

function plainMarkdownText(markdown: string): string {
  return markdown
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/^>\s?/gm, "")
    .replace(/^\s*(?:[-*+]|\d+[.)])\s+/gm, "")
    .replace(/[*_`~[\]()|:]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function estimateMarkdownBlockUnits(block: string): number {
  const trimmed = block.trim();
  if (trimmed.length === 0) return 0;

  if (/^!\[.*?\]\(.*?\)\s*$/.test(trimmed)) return 40;

  if (/^#\s+/.test(trimmed)) return 16;
  if (/^##\s+/.test(trimmed)) return 10;
  if (/^###\s+/.test(trimmed)) return 7;
  if (/^####\s+/.test(trimmed)) return 5;

  const lines = trimmed.split("\n");
  const text = plainMarkdownText(trimmed);
  const textUnits = Math.max(1, Math.ceil(text.length / 92));

  if (/^(```|~~~)/.test(trimmed)) {
    return Math.min(30, 4 + lines.length * 1.2);
  }

  if (/^:::(callout|summary)\b/.test(trimmed)) {
    return 5 + textUnits * 1.7;
  }

  if (/^:::full-width\b/.test(trimmed)) {
    return 4 + Math.max(lines.length * 1.2, textUnits * 1.5);
  }

  const tableRows = lines.filter((line) => /^\s*\|.+\|\s*$/.test(line)).length;
  if (tableRows >= 2) {
    return 5 + tableRows * 2.1;
  }

  const listItems = lines.filter((line) => /^\s*(?:[-*+]|\d+[.)])\s+/.test(line)).length;
  if (listItems > 0) {
    return 2 + listItems * 1.35 + textUnits * 1.2;
  }

  if (/^>/.test(trimmed)) {
    return 6 + textUnits * 2;
  }

  return Math.max(2, textUnits * 1.6 + lines.length * 0.55);
}

function isMajorMarkdownHeading(block: string): boolean {
  return /^#{1,2}\s+/.test(block.trim());
}

function paginateReportMarkdown(markdown: string): ReportBodyPage[] {
  const blocks = splitMarkdownBlocks(markdown);
  const pages: string[] = [];
  const current: string[] = [];
  let currentUnits = 0;

  function flush() {
    const page = current.join("\n\n").trim();
    if (page.length > 0) {
      pages.push(page);
    }
    current.length = 0;
    currentUnits = 0;
  }

  function addBlock(block: string, nextBlock: string | null) {
    const units = estimateMarkdownBlockUnits(block);
    const nextUnits = nextBlock !== null ? Math.min(estimateMarkdownBlockUnits(nextBlock), 12) : 0;
    const isImage = /^!\[.*?\]\(.*?\)\s*$/.test(block.trim());
    const shouldBreak =
      current.length > 0 &&
      (currentUnits + units + nextUnits > REPORT_BODY_PAGE_TARGET_UNITS ||
        (isMajorMarkdownHeading(block) && currentUnits > REPORT_MAJOR_SECTION_BREAK_UNITS) ||
        (isImage && currentUnits > 20));

    if (shouldBreak) {
      flush();
    }

    current.push(block.trim());
    currentUnits += units;
  }

  blocks.forEach((block, index) => {
    const pageBreakRemainder = extractPageBreakRemainder(block);
    if (pageBreakRemainder !== null) {
      flush();
      if (pageBreakRemainder.length > 0) {
        addBlock(pageBreakRemainder, blocks[index + 1] ?? null);
      }
      return;
    }

    addBlock(block, blocks[index + 1] ?? null);
  });

  flush();

  return pages.map((page, index) => ({
    id: `body-page-${index + 1}`,
    markdown: page,
  }));
}

function reactNodeText(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(reactNodeText).join("");
  if (isValidElement<{ children?: ReactNode }>(node)) return reactNodeText(node.props.children);
  return "";
}

function ReportMarkdown({ markdown }: { markdown: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath, remarkDirective, remarkReportDirectives]}
      rehypePlugins={[[rehypeKatex, { strict: false, throwOnError: false }]]}
      components={{
        h1({ children }) {
          const text = reactNodeText(children);
          const numbered = splitNumberedHeading(text);
          return (
            <h1 className="report-section-heading">
              {numbered !== null && <span className="report-section-number">{numbered.number}</span>}
              <span>{numbered?.title ?? children}</span>
            </h1>
          );
        },
        h2({ children }) {
          const text = reactNodeText(children);
          const numbered = splitNumberedHeading(text);
          return (
            <h2 className={numbered !== null ? "report-chapter-heading numbered" : "report-chapter-heading"}>
              {numbered !== null && <span>{numbered.number}</span>}
              <strong>{numbered?.title ?? children}</strong>
            </h2>
          );
        },
        h3({ children }) {
          const text = reactNodeText(children);
          const numbered = splitNumberedHeading(text);
          return (
            <h3 className={numbered !== null ? "report-minor-heading numbered" : "report-minor-heading"}>
              {numbered !== null && <span>{numbered.number}</span>}
              <strong>{numbered?.title ?? children}</strong>
            </h3>
          );
        },
      }}
    >
      {markdown}
    </ReactMarkdown>
  );
}

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

function agentLabel(agentId: string | null | undefined): string {
  if (agentId === "chat_agent") return "Chat Agent";
  if (agentId === "research_agent") return "Research Agent";
  if (agentId === "writer_agent") return "Writer Agent";
  if (agentId === "style_agent") return "Style Agent";
  return agentId ?? "Agent";
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

export function AgenticIntelligenceApp() {
  const [busy, setBusy] = useState(false);
  const [sessions, setSessions] = useState<SessionListItem[]>([]);
  const [currentSession, setCurrentSession] = useState<SessionRecord | null>(null);
  const [run, setRun] = useState<WorkflowRun | null>(null);
  const [deliverableRun, setDeliverableRun] = useState<WorkflowRun | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [nodeDetail, setNodeDetail] = useState<NodeDetail | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [edgePayloadOpen, setEdgePayloadOpen] = useState(false);
  const [selectedEdgePayload, setSelectedEdgePayload] = useState<EdgePayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [approvalBusy, setApprovalBusy] = useState(false);
  const [activeTabId, setActiveTabId] = useState<WorkspaceTabId>("graph");
  const [reportStyleId, setReportStyleId] = useState<ReportStyleId>("risk");
  const [rightTabId, setRightTabId] = useState<"chat" | "activity">("chat");
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

  useEffect(() => {
    if (run === null) {
      setDeliverableRun(null);
      return;
    }
    const hasDeliverable =
      run.node_states.style_agent?.status === "completed" ||
      run.node_states.writer_agent?.status === "completed";
    if (hasDeliverable) {
      setDeliverableRun(run);
      return;
    }
    setDeliverableRun((current) => (current?.session_id === run.session_id ? current : null));
  }, [run]);

  const finalDeliverable = useMemo(() => {
    const styleState = deliverableRun?.node_states.style_agent;
    const stylePayload = styleState?.output_payload;
    if (styleState?.status === "completed" && stylePayload !== null && stylePayload !== undefined) {
      const styledMessage = stylePayload.message;
      if (typeof styledMessage === "string" && styledMessage.trim().length > 0) {
        return styledMessage;
      }
      return JSON.stringify(stylePayload, null, 2);
    }
    const writerState = deliverableRun?.node_states.writer_agent;
    const payload = writerState?.output_payload;
    if (writerState?.status !== "completed" || payload === null || payload === undefined) {
      return "Writer result is not available yet.";
    }
    const message = payload.message;
    if (typeof message === "string" && message.trim().length > 0) {
      return message;
    }
    return JSON.stringify(payload, null, 2);
  }, [deliverableRun]);

  const finalDeliverableLanguage = useMemo(() => {
    const styleState = deliverableRun?.node_states.style_agent;
    const stylePayload = styleState?.output_payload;
    if (styleState?.status === "completed" && stylePayload !== null && stylePayload !== undefined) {
      return typeof stylePayload?.message === "string" ? "markdown" : "json";
    }
    const writerState = deliverableRun?.node_states.writer_agent;
    const payload = writerState?.output_payload;
    return typeof payload?.message === "string" ? "markdown" : "json";
  }, [deliverableRun]);

  const reportParts = useMemo(
    () => extractReportParts(finalDeliverable, finalDeliverableLanguage),
    [finalDeliverable, finalDeliverableLanguage],
  );
  const reportBodyPages = useMemo(
    () => paginateReportMarkdown(reportParts.bodyMarkdown),
    [reportParts.bodyMarkdown],
  );

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
      const edgeId = `edge_${event.agent_id}_to_research_agent`;
      payloads[edgeId] = {
        from_node_id: event.agent_id,
        to_node_id: "research_agent",
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
      const toolNodeId = `tool_${event.agent_id}_${invocationId}`;
      const edgeId = `edge_${toolNodeId}_to_${event.agent_id}`;
      payloads[edgeId] = {
        from_node_id: toolNodeId,
        to_node_id: event.agent_id,
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
      const edgeId = `edge_${event.agent_id}_to_research_agent`;
      setEdgePayloads((current) => ({
        ...current,
        [edgeId]: {
          from_node_id: event.agent_id ?? edgeId,
          to_node_id: "research_agent",
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
        const toolNodeId = `tool_${event.agent_id}_${invocationId}`;
        const edgeId = `edge_${toolNodeId}_to_${event.agent_id}`;
        setEdgePayloads((current) => ({
          ...current,
          [edgeId]: {
            from_node_id: toolNodeId,
            to_node_id: event.agent_id ?? edgeId,
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
      const started = await startChatRun(session.session_id, prompt, attachments);
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
    <div className="agenticIntelligence app-shell bp6-dark">
      <header className="topbar">
        <div className="brand">
          <h1>FireGuard Intelligence</h1>
          {run !== null && <Tag intent={statusIntent(run.status)}>{run.status}</Tag>}
        </div>
        <Button
          icon="stop"
          text="Stop"
          intent={Intent.DANGER}
          disabled={!isActive(run) || busy}
          onClick={() => void handleStopRun()}
        />
      </header>

      {error !== null && <div className="error-banner">{error}</div>}

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

      <main className="workspace">
        <Tabs
          id="workspace-tabs"
          className="workspace-tabs"
          selectedTabId={activeTabId}
          onChange={(nextTabId) => setActiveTabId(nextTabId as WorkspaceTabId)}
        >
          <Tab
            id="graph"
            title="Graph"
            panel={
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
            }
          />
          <Tab
            id="deliverable"
            title="Deliverable"
            panel={
              <div className="deliverable-editor">
                <Editor
                  language={finalDeliverableLanguage}
                  theme="vs-dark"
                  value={finalDeliverable}
                  options={{
                    readOnly: true,
                    minimap: { enabled: false },
                    wordWrap: "on",
                    fontSize: 13,
                    lineHeight: 20,
                    scrollBeyondLastLine: false,
                    automaticLayout: true,
                  }}
                />
              </div>
            }
          />
          <Tab
            id="report"
            title="Report"
            panel={
              <div className="report-preview">
                <div className="report-style-picker" aria-label="Report style">
                  <span>Style</span>
                  <SegmentedControl
                    intent={Intent.PRIMARY}
                    options={REPORT_STYLE_OPTIONS}
                    size="small"
                    value={reportStyleId}
                    onValueChange={(value) => setReportStyleId(value as ReportStyleId)}
                  />
                </div>
                <div className={`report-pages report-style-${reportStyleId}`}>
                  <section className="report-page report-cover-page" aria-label="Report cover">
                    <div className="report-cover-illustration" aria-hidden="true">
                      <span />
                      <span />
                      <span />
                    </div>
                    <div className="report-cover-copy">
                      <p className="report-kicker">FireGuard Intelligence</p>
                      <h1>{reportParts.title}</h1>
                      {reportParts.subtitle !== null && <p className="report-subtitle">{reportParts.subtitle}</p>}
                    </div>
                    {reportParts.headings.length > 0 && (
                      <ol className="report-cover-toc" aria-label="Report contents">
                        {reportParts.headings.slice(0, 10).map((heading, index) => (
                          <li key={`${heading.depth}-${heading.number ?? "section"}-${heading.title}`}>
                            <span>{heading.number ?? String(index + 1)}</span>
                            <strong>{heading.title}</strong>
                          </li>
                        ))}
                      </ol>
                    )}
                    <div className="report-color-strip" aria-hidden="true" />
                  </section>

                  {reportBodyPages.map((page, index) => {
                    const pageNumber = index + 2;
                    return (
                      <section
                        key={page.id}
                        className="report-page report-body-page"
                        aria-label={`Report page ${pageNumber}`}
                      >
                        <header className="report-page-header">
                          <span>{reportParts.title}</span>
                          <strong>{String(pageNumber).padStart(2, "0")}</strong>
                        </header>
                        <article className="report-body-content">
                          <ReportMarkdown markdown={page.markdown} />
                        </article>
                        <footer className="report-page-footer">
                          <span>FireGuard Intelligence</span>
                          <span>Page {pageNumber}</span>
                        </footer>
                        <div className="report-color-strip" aria-hidden="true" />
                      </section>
                    );
                  })}
                </div>
              </div>
            }
          />
        </Tabs>
      </main>

      <aside className="chat-panel">
        <Tabs
          id="right-tabs"
          selectedTabId={rightTabId}
          onChange={(nextTabId) => setRightTabId(nextTabId as "chat" | "activity")}
        >
          <Tab
            id="chat"
            title="Chat"
            panel={
              <section className="chat-tab">
                <div className="chat-messages">
                  {chatMessages.length === 0 ? (
                    <div className="empty-chat">Ask the chat agent to start an intelligence workflow.</div>
                  ) : (
                    chatMessages.map((message) => (
                      <article key={message.id} className={`chat-message ${message.role}`}>
                        <div className="message-meta">
                          <span>{message.role === "user" ? "You" : agentLabel(message.agent_id)}</span>
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
                        <div className="message-content">{message.content.length > 0 ? message.content : "..."}</div>
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
                    placeholder="Message the chat agent..."
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
            }
          />
          <Tab
            id="activity"
            title="Activity"
            panel={
              <section className="activity-tab">
                {activityAnnotations.length === 0 ? (
                  <div className="empty-chat">No tool or workflow activity yet.</div>
                ) : (
                  activityAnnotations
                    .map((annotation, index) => (
                      <ToolCard
                        key={`${annotation.event_id}:activity:${index}`}
                        annotation={annotation}
                        expanded
                        disabled={busy || isActive(run)}
                        onAskSubmit={(content) => void sendChatMessage(content)}
                      />
                    ))
                )}
              </section>
            }
          />
        </Tabs>
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
