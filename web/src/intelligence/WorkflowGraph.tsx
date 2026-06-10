import "@xyflow/react/dist/style.css";
import "./styles/graph.css";
import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Edge,
  type Node,
} from "@xyflow/react";
import { useEffect, useMemo } from "react";
import type { EdgePayload, StreamEvent, WorkflowRun } from "./types";
import { FlowNode } from "./graph/FlowNode";
import { FlowEdge } from "./graph/FlowEdge";
import { buildGraphModel, buildGraphSignature } from "./graph/build";
import type { FlowNodeData, FlowEdgeData } from "./graph/types";

const nodeTypes = { workflow: FlowNode };
const edgeTypes = { workflow: FlowEdge };

interface WorkflowGraphProps {
  run: WorkflowRun | null;
  selectedNodeId: string | null;
  edgePayloads: Record<string, EdgePayload>;
  events: StreamEvent[];
  onSelectNode: (nodeId: string) => void;
  onSelectEdge: (edgeId: string) => void;
  onRestartFromNode: ((nodeId: string) => void) | null;
}

export function WorkflowGraph({ run, selectedNodeId, edgePayloads, events, onSelectNode, onSelectEdge, onRestartFromNode }: WorkflowGraphProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<FlowNodeData>>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge<FlowEdgeData>>([]);

  const graphModel = useMemo(() => {
    if (run === null) return null;
    return buildGraphModel(run, selectedNodeId, edgePayloads, events, onSelectEdge, onRestartFromNode);
  }, [run, selectedNodeId, edgePayloads, events, onSelectEdge, onRestartFromNode]);

  const sig = buildGraphSignature(run, selectedNodeId, edgePayloads, events);

  useEffect(() => {
    if (graphModel === null) return;
    setNodes((curr) => {
      const saved = new Map(curr.map((n) => [n.id, n.position]));
      return graphModel.nodes.map((n) => ({ ...n, position: saved.get(n.id) ?? n.position }));
    });
    setEdges(graphModel.edges);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sig, setNodes, setEdges]);

  if (run === null) {
    return <div className="workflow-graph empty">Open or start a session to see the workflow.</div>;
  }

  return (
    <div className="workflow-graph">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={(_, node) => onSelectNode(node.id)}
        defaultViewport={{ x: 20, y: 20, zoom: 0.9 }}
        minZoom={0.25}
        maxZoom={2}
        nodesDraggable
        nodesConnectable={false}
        elementsSelectable
        panOnDrag
        zoomOnScroll
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} color="#1e2d3d" gap={22} size={1.2} />
        <Controls showInteractive={false} />
        <MiniMap
          nodeColor={(n) => {
            const d = n.data as FlowNodeData;
            return (d.accentColor as string) ?? "#334155";
          }}
          maskColor="rgba(8,14,26,0.82)"
          style={{ background: "#0d1621", border: "1px solid #1e2d3d", borderRadius: 8 }}
        />
      </ReactFlow>
    </div>
  );
}
