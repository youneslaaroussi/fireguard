import type { Edge, Node, XYPosition } from "@xyflow/react";
import type { StreamEvent, WorkflowRun, EdgePayload } from "../types";
import {
  ACCENT_COLORS,
  CLICKABLE_EDGE_IDS,
  DISPLAY_LABELS,
  FALLBACK_ICON,
  NODE_ICONS,
  NODE_ORDER,
  PRIMARY_POSITIONS,
  RERUNNABLE_NODES,
  STATUS_BORDER,
  TOOL_ACCENT_COLORS,
  TOOL_PLATFORM_BADGE,
} from "./constants";
import type { EntityGraphNode, FlowEdgeData, FlowNodeData, SubagentGraphNode, ToolGraphNode } from "./types";
import {
  AlertTriangle,
  Bot,
  Database,
  FileCheck2,
  Flame,
  House,
  MapPin,
  Navigation,
  Search,
  SquareTerminal,
} from "lucide-react";

// Public

export function buildGraphSignature(
  run: WorkflowRun | null,
  edgePayloads: Record<string, EdgePayload>,
  events: StreamEvent[],
): string {
  if (run === null) return "empty";
  const statuses = run.workflow.nodes
    .map((n) => `${n.node_id}:${run.node_states[n.node_id]?.status ?? "pending"}`)
    .join("|");
  const subs = subagentsFromEvents(events).map((n) => `${n.node_id}:${n.status}`).join("|");
  const toolList = toolsFromEvents(events);
  const tools = toolList.map((n) => `${n.node_id}:${n.status}`).join("|");
  const entities = entitiesFromTools(toolList).map((n) => `${n.node_id}:${n.status}:${Math.round(n.importance)}`).join("|");
  const payloads = Object.keys(edgePayloads).sort().join("|");
  return `${run.run_id}::${run.status}::${statuses}::${subs}::${tools}::${entities}::${payloads}`;
}

export function buildGraphModel(
  run: WorkflowRun,
  selectedNodeId: string | null,
  edgePayloads: Record<string, EdgePayload>,
  events: StreamEvent[],
  onSelectEdge: (id: string) => void,
  onRestartFromNode: ((nodeId: string) => void) | null,
): { nodes: Node<FlowNodeData>[]; edges: Edge<FlowEdgeData>[] } {
  const subagentList = subagentsFromEvents(events);
  const toolList = toolsFromEvents(events);
  const entityList = entitiesFromTools(toolList);

  const nodePositions = new Map<string, XYPosition>(
    Object.entries(PRIMARY_POSITIONS),
  );
  const subagentNodes = buildSubagentNodes(subagentList, selectedNodeId, nodePositions);
  const toolNodes = buildToolNodes(toolList, selectedNodeId, nodePositions);
  const entityNodes = buildEntityNodes(entityList, selectedNodeId, nodePositions);

  return {
    nodes: [
      ...buildPrimaryNodes(run, selectedNodeId, onRestartFromNode),
      ...subagentNodes,
      ...toolNodes,
      ...entityNodes,
    ],
    edges: [
      ...buildPrimaryEdges(run, edgePayloads, onSelectEdge),
      ...buildSubagentEdges(subagentNodes, edgePayloads, onSelectEdge),
      ...buildToolEdges(toolList, edgePayloads, onSelectEdge),
      ...buildEntityEdges(entityList, onSelectEdge),
    ],
  };
}

// Node builders

function buildPrimaryNodes(
  run: WorkflowRun,
  selectedNodeId: string | null,
  onRestartFromNode: ((nodeId: string) => void) | null,
) {
  return [...run.workflow.nodes]
    .sort((a, b) => NODE_ORDER.indexOf(a.node_id) - NODE_ORDER.indexOf(b.node_id))
    .map((node, index): Node<FlowNodeData> => {
      const status = run.node_states[node.node_id]?.status ?? "pending";
      const toolName = node.config.tool_name;
      const accentColor =
        typeof toolName === "string" && toolName === "exa_search"
          ? ACCENT_COLORS.exa_search
          : typeof toolName === "string" && toolName.startsWith("sandbox_")
            ? ACCENT_COLORS.sandbox
            : ACCENT_COLORS[node.node_id] ?? ACCENT_COLORS[node.config.kind as string] ?? "#6366f1";
      const canRestart =
        onRestartFromNode !== null &&
        RERUNNABLE_NODES.has(node.node_id) &&
        (status === "completed" || status === "failed");
      return {
        id: node.node_id,
        type: "workflow",
        position: { x: 20 + index * 210, y: 80 },
        data: {
          label: DISPLAY_LABELS[node.node_id] ?? node.label,
          status,
          accentColor,
          NodeIcon: NODE_ICONS[node.node_id] ?? FALLBACK_ICON,
          selected: selectedNodeId === node.node_id,
          compact: false,
          cluster: "workflow",
          layer: "workflow",
          onRestart: canRestart ? () => onRestartFromNode(node.node_id) : null,
        },
      };
    });
}

function buildSubagentNodes(
  list: SubagentGraphNode[],
  selectedNodeId: string | null,
  positions: Map<string, XYPosition>,
): Node<FlowNodeData>[] {
  return list.map((sub, i) => {
    const pos = subagentPosition(i, list.length);
    positions.set(sub.node_id, pos);
    return {
      id: sub.node_id,
      type: "workflow",
      position: pos,
      data: {
        label: sub.label,
        status: sub.status,
        accentColor: ACCENT_COLORS.subagent,
        NodeIcon: Bot,
        selected: selectedNodeId === sub.node_id,
        compact: false,
        importance: 75,
        cluster: sub.node_id,
        layer: "subagent",
        onRestart: null,
      },
    };
  });
}

function buildToolNodes(
  list: ToolGraphNode[],
  selectedNodeId: string | null,
  subPositions: Map<string, XYPosition>,
): Node<FlowNodeData>[] {
  const siblingCount = new Map<string, number>();
  return list.map((tool) => {
    const idx = siblingCount.get(tool.parent_id) ?? 0;
    siblingCount.set(tool.parent_id, idx + 1);
    return {
      id: tool.node_id,
      type: "workflow",
      position: toolPosition(subPositions.get(tool.parent_id), idx),
      data: {
        label: tool.label,
        summary: tool.summary,
        status: tool.status,
        accentColor: toolAccent(tool.tool_name),
        NodeIcon: toolIcon(tool.tool_name),
        selected: selectedNodeId === tool.node_id,
        compact: true,
        importance: 70,
        cluster: tool.node_id,
        layer: "tool",
        onRestart: null,
        platformBadge: TOOL_PLATFORM_BADGE[tool.tool_name] ?? null,
      },
    };
  });
}

function buildEntityNodes(
  list: EntityGraphNode[],
  selectedNodeId: string | null,
  positions: Map<string, XYPosition>,
): Node<FlowNodeData>[] {
  const siblingCount = new Map<string, number>();
  return list.map((entity) => {
    const idx = siblingCount.get(entity.parent_id) ?? 0;
    siblingCount.set(entity.parent_id, idx + 1);
    const pos = entityPosition(positions.get(entity.parent_id), idx);
    positions.set(entity.node_id, pos);
    return {
      id: entity.node_id,
      type: "workflow",
      position: pos,
      data: {
        label: entity.label,
        summary: entity.summary,
        status: entity.status,
        accentColor: entity.accentColor,
        NodeIcon: Database,
        selected: selectedNodeId === entity.node_id,
        compact: true,
        importance: entity.importance,
        cluster: entityCluster(entity),
        layer: "entity",
        onRestart: null,
        platformBadge: entity.platformBadge ?? null,
      },
    };
  });
}

// Edge builders

function buildPrimaryEdges(
  run: WorkflowRun,
  edgePayloads: Record<string, EdgePayload>,
  onSelectEdge: (id: string) => void,
): Edge<FlowEdgeData>[] {
  return run.workflow.edges
    .map((edge) => {
      const clickable = CLICKABLE_EDGE_IDS.has(edge.edge_id);
      const hasPayload = edgePayloads[edge.edge_id] !== undefined;
      const targetStatus = run.node_states[edge.to_node_id]?.status ?? "pending";
      const strokeColor = hasPayload ? "#10b981" : STATUS_BORDER[targetStatus] ?? "#1e3a5f";
      return makeEdge({
        id: edge.edge_id,
        source: edge.from_node_id,
        target: edge.to_node_id,
        clickable,
        hasPayload,
        title: "View handoff payload",
        onSelectEdge,
        animated: run.status === "running" && targetStatus === "running",
        strokeColor,
      });
    });
}

function buildSubagentEdges(
  subNodes: Node<FlowNodeData>[],
  edgePayloads: Record<string, EdgePayload>,
  onSelectEdge: (id: string) => void,
): Edge<FlowEdgeData>[] {
  return subNodes.map((sub) => {
    const id = `edge_research_agent_to_${sub.id}`;
    const status = sub.data.status as string;
    const strokeColor = status === "completed" ? "#10b981" : status === "running" ? "#06b6d4" : "#1e3a5f";
    return makeEdge({
      id,
      source: "research_agent",
      target: sub.id,
      clickable: true,
      hasPayload: edgePayloads[id] !== undefined,
      title: "View subagent result",
      onSelectEdge,
      animated: status === "running",
      dashed: true,
      strokeColor,
    });
  });
}

function buildToolEdges(
  list: ToolGraphNode[],
  edgePayloads: Record<string, EdgePayload>,
  onSelectEdge: (id: string) => void,
): Edge<FlowEdgeData>[] {
  return list.map((tool) => {
    const id = `edge_${tool.parent_id}_to_${tool.node_id}`;
    const strokeColor = tool.status === "completed" ? "#10b981" : tool.status === "running" ? "#f97316" : "#1e3a5f";
    return makeEdge({
      id,
      source: tool.parent_id,
      target: tool.node_id,
      clickable: true,
      hasPayload: edgePayloads[id] !== undefined,
      title: `View ${tool.tool_name} result`,
      onSelectEdge,
      animated: tool.status === "running",
      dashed: true,
      strokeColor,
    });
  });
}

function buildEntityEdges(
  list: EntityGraphNode[],
  onSelectEdge: (id: string) => void,
): Edge<FlowEdgeData>[] {
  return list.map((entity) => makeEdge({
    id: `edge_${entity.parent_id}_to_${entity.node_id}`,
    source: entity.parent_id,
    target: entity.node_id,
    clickable: false,
    hasPayload: false,
    title: entity.label,
    onSelectEdge,
    animated: false,
    dashed: true,
    strokeColor: entity.accentColor,
  }));
}

// Positioning

function subagentPosition(index: number, total: number): XYPosition {
  const cols = Math.min(total, 3);
  const col = index % Math.max(cols, 1);
  const row = Math.floor(index / Math.max(cols, 1));
  const nodeWidth = 172;
  const gap = 20;
  const totalWidth = cols * nodeWidth + (cols - 1) * gap;
  const startX = PRIMARY_POSITIONS.research_agent.x - totalWidth / 2 + nodeWidth / 2;
  return { x: startX + col * (nodeWidth + gap), y: 260 + row * 132 };
}

function toolPosition(parentPos: XYPosition | undefined, siblingIndex: number): XYPosition {
  const p = parentPos ?? PRIMARY_POSITIONS.research_agent;
  return { x: p.x, y: p.y + 150 + siblingIndex * 104 };
}

function entityPosition(parentPos: XYPosition | undefined, siblingIndex: number): XYPosition {
  const p = parentPos ?? PRIMARY_POSITIONS.research_agent;
  return { x: p.x + 180, y: p.y - 96 + siblingIndex * 58 };
}

function entityCluster(entity: EntityGraphNode): string {
  if (entity.platformBadge === "weather" || entity.platformBadge === "place" || entity.platformBadge === "pt") {
    return entity.parent_id;
  }
  return entity.parent_id;
}

// Event parsing

export function subagentsFromEvents(events: StreamEvent[]): SubagentGraphNode[] {
  const map = new Map<string, SubagentGraphNode>();
  for (const ev of events) {
    if (ev.agent_id === null) continue;
    if (ev.event_type === "subagent.started" || ev.event_type === "fleet.child.started") {
      const childId = ev.data.child_id;
      map.set(ev.agent_id, {
        node_id: ev.agent_id,
        label: typeof childId === "string" ? childId : shortLabel(ev.agent_id),
        status: "running",
      });
    }
    if (ev.event_type === "subagent.completed" || ev.event_type === "fleet.child.completed") {
      const existing = map.get(ev.agent_id);
      map.set(ev.agent_id, {
        node_id: ev.agent_id,
        label: existing?.label ?? shortLabel(ev.agent_id),
        status: ev.data.ok === false ? "failed" : "completed",
      });
    }
    if (ev.event_type === "subagent.failed") {
      const existing = map.get(ev.agent_id);
      map.set(ev.agent_id, {
        node_id: ev.agent_id,
        label: existing?.label ?? shortLabel(ev.agent_id),
        status: "failed",
      });
    }
  }
  return Array.from(map.values());
}

export function toolsFromEvents(events: StreamEvent[]): ToolGraphNode[] {
  const map = new Map<string, ToolGraphNode>();
  for (const ev of events) {
    if (ev.agent_id === null) continue;
    if (
      ev.event_type !== "tool.started" &&
      ev.event_type !== "tool.completed" &&
      ev.event_type !== "tool.failed"
    ) continue;
    const toolName = ev.data.tool_name;
    if (!isGraphTool(toolName)) continue;
    const invId = ev.data.invocation_id;
    if (typeof invId !== "string" || invId.length === 0) continue;
    const parentId = ev.node_id ?? ev.agent_id;
    const nodeId = `tool_${parentId}_${invId}`;
    const existing = map.get(nodeId);
    const output = isObj(ev.data.output) ? ev.data.output : existing?.output;
    map.set(nodeId, {
      node_id: nodeId,
      parent_id: parentId,
      label: toolLabel(ev, existing?.label),
      summary: toolSummary(ev, existing?.summary),
      status: ev.event_type === "tool.started" ? "running" : ev.event_type === "tool.completed" ? "completed" : "failed",
      tool_name: typeof toolName === "string" ? toolName : "tool",
      output,
    });
  }
  return Array.from(map.values());
}

function entitiesFromTools(tools: ToolGraphNode[]): EntityGraphNode[] {
  return tools.flatMap((tool) => {
    if (tool.status !== "completed" || tool.output === undefined) return [];
    if (tool.tool_name === "fireguard_search_zones") return zoneEntities(tool);
    if (tool.tool_name === "fireguard_search_shelters") return shelterEntities(tool);
    if (tool.tool_name === "fireguard_search_road_events") return roadEntities(tool);
    if (tool.tool_name === "fireguard_search_events") return detectionEntities(tool);
    if (tool.tool_name === "fireguard_evaluate_route") return routeEntities(tool);
    if (tool.tool_name === "fireguard_map_annotation") return annotationEntities(tool);
    return [];
  });
}

function zoneEntities(tool: ToolGraphNode): EntityGraphNode[] {
  return arrayValue(tool.output?.zones).filter(isObj).slice(0, 250).map((zone, index) => {
    const name = stringValue(zone.name) ?? `Zone ${index + 1}`;
    const population = numberValue(zone.population);
    const homes = numberValue(zone.homes);
    const distance = numberValue(zone.distance_km);
    return {
      node_id: entityId(tool, "zone", zone.zone_id, index),
      parent_id: tool.node_id,
      label: trunc(name, 38),
      summary: [population !== null ? `pop ${population.toLocaleString()}` : "", homes !== null ? `${homes.toLocaleString()} homes` : "", distance !== null ? `${round(distance)} km` : ""]
        .filter(Boolean)
        .join(" · "),
      status: "completed",
      accentColor: "#a78bfa",
      importance: clamp(48 + Math.log10(Math.max(population ?? 1, 1)) * 12 + (homes ?? 0) / 80, 45, 96),
      platformBadge: "zone",
    };
  });
}

function shelterEntities(tool: ToolGraphNode): EntityGraphNode[] {
  return arrayValue(tool.output?.shelters).filter(isObj).slice(0, 250).map((shelter, index) => {
    const name = stringValue(shelter.name) ?? `Shelter ${index + 1}`;
    const status = stringValue(shelter.status)?.toUpperCase() ?? "UNKNOWN";
    const community = stringValue(shelter.community) ?? stringValue(shelter.municipality);
    const distance = numberValue(shelter.distance_km);
    const open = status === "OPEN";
    return {
      node_id: entityId(tool, "shelter", shelter.facility_id, index),
      parent_id: tool.node_id,
      label: trunc(name, 36),
      summary: [status, community, distance !== null ? `${round(distance)} km` : ""].filter(Boolean).join(" · "),
      status: open ? "completed" : "waiting",
      accentColor: open ? "#22c55e" : "#64748b",
      importance: clamp((open ? 82 : 34) + (distance !== null ? Math.max(0, 18 - distance / 18) : 0), 28, 98),
      platformBadge: open ? "open" : "closed",
    };
  });
}

function roadEntities(tool: ToolGraphNode): EntityGraphNode[] {
  return arrayValue(tool.output?.road_events).filter(isObj).slice(0, 250).map((road, index) => {
    const name = stringValue(road.road_name) ?? stringValue(road.title) ?? `Road event ${index + 1}`;
    const severity = stringValue(road.severity)?.toUpperCase();
    const status = stringValue(road.status)?.toUpperCase();
    const distance = numberValue(road.distance_km);
    const severe = severity === "MAJOR" || status === "ACTIVE";
    return {
      node_id: entityId(tool, "road", road.event_id, index),
      parent_id: tool.node_id,
      label: trunc(name, 38),
      summary: [severity, status, distance !== null ? `${round(distance)} km` : ""].filter(Boolean).join(" · "),
      status: severe ? "failed" : "completed",
      accentColor: severe ? "#f97316" : "#facc15",
      importance: severe ? 90 : 58,
      platformBadge: "road",
    };
  });
}

function detectionEntities(tool: ToolGraphNode): EntityGraphNode[] {
  return arrayValue(tool.output?.events).filter(isObj).slice(0, 300).flatMap((event, index) => {
    const source = stringValue(event.source) ?? stringValue(event.satellite) ?? `Detection ${index + 1}`;
    const acquired = stringValue(event.acquired_at);
    const frp = numberValue(event.frp);
    const brightness = numberValue(event.brightness);
    const confidence = stringValue(event.confidence);
    const time = acquired ? acquired.replace("T", " ").slice(5, 16) : "";
    const strength = (frp ?? 0) * 1.6 + Math.max(0, (brightness ?? 295) - 295) * 0.45;
    const detection: EntityGraphNode = {
      node_id: entityId(tool, "detection", `${source}_${acquired ?? ""}_${numberValue(event.latitude) ?? ""}_${numberValue(event.longitude) ?? ""}`, index),
      parent_id: tool.node_id,
      label: trunc(source, 28),
      summary: [frp !== null ? `FRP ${round(frp)}` : "", confidence ? `conf ${confidence}` : "", time].filter(Boolean).join(" · "),
      status: "completed",
      accentColor: "#ef4444",
      importance: clamp(30 + strength, 30, 98),
      platformBadge: "hotspot",
    };
    const children: EntityGraphNode[] = [];
    if (isObj(event.weather)) {
      const temp = numberValue(event.weather.temperature_2m);
      const humidity = numberValue(event.weather.relative_humidity_2m);
      const wind = numberValue(event.weather.wind_speed_10m);
      const gust = numberValue(event.weather.wind_gusts_10m);
      children.push({
        node_id: entityId(tool, "weather", `${detection.node_id}_weather`, index),
        parent_id: detection.node_id,
        label: "Weather",
        summary: [
          temp !== null ? `${round(temp)}C` : "",
          humidity !== null ? `RH ${Math.round(humidity)}%` : "",
          wind !== null ? `wind ${round(wind)} km/h` : "",
          gust !== null ? `gust ${round(gust)} km/h` : "",
        ].filter(Boolean).join(" · "),
        status: "completed",
        accentColor: "#38bdf8",
        importance: clamp(24 + (gust ?? wind ?? 0) * 0.9 + Math.max(0, 45 - (humidity ?? 45)) * 0.45, 24, 72),
        platformBadge: "weather",
      });
    }
    if (isObj(event.place)) {
      const address = stringValue(event.place.formatted_address);
      children.push({
        node_id: entityId(tool, "place", `${detection.node_id}_place`, index),
        parent_id: detection.node_id,
        label: "Place",
        summary: address ?? "location context",
        status: "completed",
        accentColor: "#94a3b8",
        importance: 26,
        platformBadge: "place",
      });
    }
    return [detection, ...children];
  });
}

function routeEntities(tool: ToolGraphNode): EntityGraphNode[] {
  const output = tool.output;
  if (output === undefined) return [];
  const safe = output.safe === true;
  const distance = numberValue(output.distance_km);
  const minutes = numberValue(output.duration_minutes);
  const route: EntityGraphNode = {
    node_id: entityId(tool, "route", "primary", 0),
    parent_id: tool.node_id,
    label: safe ? "Route safe" : "Route blocked",
    summary: [distance !== null ? `${round(distance)} km` : "", minutes !== null ? `${Math.round(minutes)} min` : ""].filter(Boolean).join(" · "),
    status: safe ? "completed" : "failed",
    accentColor: safe ? "#14b8a6" : "#f97316",
    importance: safe ? 86 : 96,
    platformBadge: "route",
  };
  const points = arrayValue(output.polyline).filter(isObj).slice(0, 24).map((point, index): EntityGraphNode => ({
    node_id: entityId(tool, "point", `${numberValue(point.lat) ?? ""}_${numberValue(point.lon) ?? ""}`, index),
    parent_id: route.node_id,
    label: `Route point ${index + 1}`,
    summary: `${round(numberValue(point.lat) ?? 0, 3)}, ${round(numberValue(point.lon) ?? 0, 3)}`,
    status: "completed",
    accentColor: "#2dd4bf",
    importance: index === 0 || index === arrayValue(output.polyline).length - 1 ? 52 : 36,
    platformBadge: "pt",
  }));
  return [route, ...points];
}

function annotationEntities(tool: ToolGraphNode): EntityGraphNode[] {
  const annotation = isObj(tool.output?.annotation) ? tool.output.annotation : null;
  if (annotation === null) return [];
  const markers = arrayValue(annotation.markers).filter(isObj).slice(0, 250).map((marker, index): EntityGraphNode => {
    const type = stringValue(marker.type) ?? "marker";
    const label = stringValue(marker.label) ?? `Marker ${index + 1}`;
    const detail = stringValue(marker.detail);
    const isOpenShelter = type === "shelter_open";
    const isHotspot = type === "hotspot";
    const isBlockage = type === "blockage";
    return {
      node_id: entityId(tool, "marker", `${type}_${label}`, index),
      parent_id: tool.node_id,
      label: trunc(label, 36),
      summary: detail ?? type,
      status: isBlockage ? "failed" : isOpenShelter || isHotspot ? "completed" : "waiting",
      accentColor: isHotspot ? "#ef4444" : isOpenShelter ? "#22c55e" : isBlockage ? "#f97316" : "#94a3b8",
      importance: isHotspot || isBlockage || isOpenShelter ? 82 : 44,
      platformBadge: trunc(type.replace(/_/g, " "), 10),
    };
  });
  const routes = arrayValue(annotation.routes).filter(isObj).slice(0, 100).map((route, index): EntityGraphNode => {
    const label = stringValue(route.label) ?? `Annotated route ${index + 1}`;
    const status = stringValue(route.status)?.toUpperCase();
    const distance = numberValue(route.distance_km);
    const minutes = numberValue(route.duration_minutes);
    return {
      node_id: entityId(tool, "annotation_route", label, index),
      parent_id: tool.node_id,
      label: trunc(label, 38),
      summary: [status, distance !== null ? `${round(distance)} km` : "", minutes !== null ? `${Math.round(minutes)} min` : ""].filter(Boolean).join(" · "),
      status: status === "SAFE" ? "completed" : "failed",
      accentColor: status === "SAFE" ? "#14b8a6" : "#f97316",
      importance: status === "SAFE" ? 74 : 88,
      platformBadge: "route",
    };
  });
  return [...markers, ...routes];
}

// Helpers

function makeEdge({
  id, source, target, clickable, hasPayload, title, onSelectEdge, animated, dashed = false, strokeColor,
}: {
  id: string; source: string; target: string;
  clickable: boolean; hasPayload: boolean; title: string;
  onSelectEdge: (id: string) => void;
  animated: boolean; dashed?: boolean; strokeColor: string;
}): Edge<FlowEdgeData> {
  return {
    id,
    type: "workflow",
    source,
    target,
    animated,
    data: { clickable, hasPayload, title, strokeColor, onSelectEdge },
    style: { stroke: strokeColor, strokeWidth: animated ? 2 : 1.5, strokeDasharray: dashed ? "6 4" : undefined },
    markerEnd: { type: "arrowclosed", color: strokeColor, width: 14, height: 14 },
  };
}

function toolLabel(ev: StreamEvent, fallback = "tool"): string {
  const t = ev.data.tool_name;
  if (typeof t === "string") return toolDisplayName(t);
  return fallback;
}

function toolSummary(ev: StreamEvent, fallback = ""): string {
  if (ev.event_type === "tool.started") return startedSummary(ev, fallback);
  const output = ev.data.output;
  const toolName = ev.data.tool_name;
  if (!isObj(output)) return fallback;
  if (ev.event_type === "tool.failed") {
    return errorSummary(output) ?? fallback;
  }
  if (toolName === "fireguard_search_zones") return zonesSummary(output);
  if (toolName === "fireguard_search_shelters") return sheltersSummary(output);
  if (toolName === "fireguard_search_road_events") return roadsSummary(output);
  if (toolName === "fireguard_search_events") return eventsSummary(output);
  if (toolName === "fireguard_evaluate_route") return routeSummary(output);
  if (toolName === "fireguard_map_annotation") return annotationSummary(output);
  if (toolName === "complete_workflow_node") return completionSummary(output);
  return genericOutputSummary(output) ?? fallback;
}

function startedSummary(ev: StreamEvent, fallback: string): string {
  const args = ev.data.args;
  if (!isObj(args)) return fallback;
  const radius = numberValue(args.radius_km);
  const size = numberValue(args.size);
  const lat = numberValue(args.latitude);
  const lon = numberValue(args.longitude);
  const parts = [];
  if (radius !== null) parts.push(`${round(radius)} km`);
  if (size !== null) parts.push(`limit ${size}`);
  if (lat !== null && lon !== null) parts.push(`${round(lat, 3)}, ${round(lon, 3)}`);
  return parts.length > 0 ? parts.join(" · ") : fallback;
}

function toolDisplayName(toolName: string): string {
  const names: Record<string, string> = {
    fireguard_search_zones: "Search zones",
    fireguard_search_shelters: "Search shelters",
    fireguard_search_road_events: "Road events",
    fireguard_search_events: "Fire detections",
    fireguard_evaluate_route: "Evaluate route",
    fireguard_map_annotation: "Map annotation",
    complete_workflow_node: "Final response",
    fireguard_bcws_context: "BCWS context",
    fireguard_stats: "Index stats",
    exa_search: "Web search",
  };
  return names[toolName] ?? toolName.replace(/^sandbox_/, "Sandbox ").replace(/^fireguard_/, "");
}

function zonesSummary(output: Record<string, unknown>): string {
  const count = numberValue(output.count) ?? arrayValue(output.zones).length;
  const first = firstObj(output.zones);
  const name = stringValue(first?.name);
  const population = numberValue(first?.population);
  const homes = numberValue(first?.homes);
  const detail = [name, population !== null ? `pop ${population.toLocaleString()}` : "", homes !== null ? `${homes.toLocaleString()} homes` : ""]
    .filter(Boolean)
    .join(" · ");
  return trunc(`${count} zones${detail ? ` · ${detail}` : ""}`, 64);
}

function sheltersSummary(output: Record<string, unknown>): string {
  const shelters = arrayValue(output.shelters).filter(isObj);
  const open = shelters.filter((item) => stringValue(item.status)?.toUpperCase() === "OPEN");
  const closed = shelters.filter((item) => stringValue(item.status)?.toUpperCase() === "CLOSED");
  const nearestOpen = open[0];
  const name = stringValue(nearestOpen?.name);
  const distance = numberValue(nearestOpen?.distance_km);
  const nearest = name ? `nearest open ${name}${distance !== null ? ` ${round(distance)} km` : ""}` : "no open shelter";
  return trunc(`${open.length} open · ${closed.length} closed · ${nearest}`, 70);
}

function roadsSummary(output: Record<string, unknown>): string {
  const count = numberValue(output.count) ?? arrayValue(output.road_events).length;
  const first = firstObj(output.road_events);
  const road = stringValue(first?.road_name) ?? stringValue(first?.title);
  const severity = stringValue(first?.severity);
  const distance = numberValue(first?.distance_km);
  const detail = [road, severity, distance !== null ? `${round(distance)} km` : ""].filter(Boolean).join(" · ");
  return trunc(`${count} road events${detail ? ` · ${detail}` : ""}`, 70);
}

function eventsSummary(output: Record<string, unknown>): string {
  const events = arrayValue(output.events).filter(isObj);
  const count = numberValue(output.count) ?? events.length;
  const frps = events.map((item) => numberValue(item.frp)).filter((value): value is number => value !== null);
  const maxFrp = frps.length > 0 ? Math.max(...frps) : null;
  const latest = stringValue(events[0]?.acquired_at);
  const detail = [maxFrp !== null ? `max FRP ${round(maxFrp)}` : "", latest ? latest.slice(0, 10) : ""].filter(Boolean).join(" · ");
  return trunc(`${count} detections${detail ? ` · ${detail}` : ""}`, 68);
}

function routeSummary(output: Record<string, unknown>): string {
  const safe = output.safe === true ? "SAFE" : output.safe === false ? "BLOCKED" : "checked";
  const distance = numberValue(output.distance_km);
  const minutes = numberValue(output.duration_minutes);
  const risks = arrayValue(output.risk_flags).length;
  return [safe, distance !== null ? `${round(distance)} km` : "", minutes !== null ? `${Math.round(minutes)} min` : "", risks > 0 ? `${risks} risks` : ""]
    .filter(Boolean)
    .join(" · ");
}

function annotationSummary(output: Record<string, unknown>): string {
  const annotation = isObj(output.annotation) ? output.annotation : null;
  const markers = annotation ? arrayValue(annotation.markers).length : 0;
  const routes = annotation ? arrayValue(annotation.routes).length : 0;
  const message = annotation ? stringValue(annotation.message) : null;
  return trunc(`${markers} markers · ${routes} routes${message ? ` · ${message}` : ""}`, 74);
}

function completionSummary(output: Record<string, unknown>): string {
  const payload = isObj(output.payload) ? output.payload : null;
  const nested = payload && isObj(payload.payload) ? payload.payload : null;
  const message = stringValue(nested?.message) ?? stringValue(payload?.message);
  if (message) return trunc(message.replace(/\s+/g, " "), 74);
  return output.completed === true ? "response completed" : "workflow completion";
}

function errorSummary(output: Record<string, unknown>): string | null {
  const message = stringValue(output.message) ?? stringValue(output.error);
  return message ? trunc(message, 70) : null;
}

function genericOutputSummary(output: Record<string, unknown>): string | null {
  const count = numberValue(output.count);
  if (count !== null) return `${count.toLocaleString()} results`;
  const message = stringValue(output.message);
  return message ? trunc(message, 70) : null;
}

function isGraphTool(toolName: unknown): toolName is string {
  return (
    toolName === "complete_workflow_node" ||
    toolName === "exa_search" ||
    (typeof toolName === "string" &&
      (toolName.startsWith("sandbox_") || toolName.startsWith("fireguard_")))
  );
}

function toolAccent(toolName: string): string {
  if (TOOL_ACCENT_COLORS[toolName]) return TOOL_ACCENT_COLORS[toolName];
  if (toolName === "exa_search") return ACCENT_COLORS.exa_search;
  if (toolName.startsWith("fireguard_")) return ACCENT_COLORS.fireguard;
  return ACCENT_COLORS.sandbox;
}

function toolIcon(toolName: string) {
  if (toolName === "fireguard_search_zones") return MapPin;
  if (toolName === "fireguard_search_shelters") return House;
  if (toolName === "fireguard_search_road_events") return AlertTriangle;
  if (toolName === "fireguard_search_events") return Flame;
  if (toolName === "fireguard_evaluate_route") return Navigation;
  if (toolName === "fireguard_map_annotation") return MapPin;
  if (toolName === "complete_workflow_node") return FileCheck2;
  if (toolName === "exa_search") return Search;
  if (toolName.startsWith("fireguard_")) return Database;
  return SquareTerminal;
}

function shortLabel(id: string): string {
  return id.replace(/^subagent_/, "").replace(/^fleet_/, "Fleet ").slice(0, 20);
}

function entityId(tool: ToolGraphNode, kind: string, value: unknown, index: number): string {
  const source = stringValue(value) ?? `${kind}_${index}`;
  return `${tool.node_id}_${kind}_${slug(source)}_${index}`;
}

function slug(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 54) || "item";
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function trunc(s: string, max = 22): string {
  return s.length > max ? `${s.slice(0, max - 3)}...` : s;
}

function isObj(v: unknown): v is Record<string, unknown> {
  return v !== null && typeof v === "object" && !Array.isArray(v);
}

function arrayValue(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

function firstObj(v: unknown): Record<string, unknown> | null {
  const first = arrayValue(v)[0];
  return isObj(first) ? first : null;
}

function stringValue(v: unknown): string | null {
  return typeof v === "string" && v.trim().length > 0 ? v.trim() : null;
}

function numberValue(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function round(value: number, digits = 1): string {
  return value.toLocaleString(undefined, { maximumFractionDigits: digits });
}
