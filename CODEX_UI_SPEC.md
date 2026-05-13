# FireGuard UI Redesign — Codex Implementation Spec

## Overview

Completely rewrite `/apps/web/src/app/page.tsx`. Do not modify any other file unless explicitly stated. The goal is a **narrative demo flow** for a hackathon judge, not an ops dashboard. Every design decision below is final — do not add features, tabs, panels, chips, or metrics that are not specified here.

The existing design language (Blueprint.js dark theme, Tailwind, color palette) is **preserved**. What changes is structure and content density.

---

## Files to modify

- **`/apps/web/src/app/page.tsx`** — full rewrite (spec below)
- **`/apps/web/src/app/globals.css`** — append the CSS additions listed at the end of this spec

## Files to leave untouched

- `/apps/web/src/components/MapPanel.tsx`
- `/apps/web/src/components/StatusBadge.tsx`
- `/apps/web/src/lib/api.ts`
- `/apps/web/src/lib/types.ts`
- `/apps/web/src/app/layout.tsx`

---

## High-level layout

```
┌──────────────────────────────────────────────────────────────────────────┐
│  TOPBAR  (56px, fixed)                                                    │
│  FireGuard logo · step pills (3 steps) · Reset button                    │
└──────────────────────────────────────────────────────────────────────────┘
┌──────────────────────────┬───────────────────────────────────────────────┐
│  LEFT PANEL              │  CENTER                                        │
│  (360px fixed, scrollable│                                                │
│   overflow-y-auto)       │  ┌───────────────────────────────────────────┐│
│                          │  │  MAP  (MapPanel, always visible)           ││
│  [content changes based  │  │  height: 100% when no assessment           ││
│   on demo stage]         │  │  height: calc(100vh - 56px - 340px)        ││
│                          │  │  when assessment exists                    ││
│                          │  └───────────────────────────────────────────┘│
│                          │                                                │
│                          │  ┌───────────────────────────────────────────┐│
│                          │  │  GEMINI PANEL  (340px, only after assess)  ││
│                          │  │  Slides up from bottom                     ││
│                          │  └───────────────────────────────────────────┘│
└──────────────────────────┴───────────────────────────────────────────────┘
```

Total viewport height = 100vh. Topbar is 56px. Everything below fills `calc(100vh - 56px)`. Left panel and center are side-by-side flex children, both `height: calc(100vh - 56px)`.

---

## State variables (exact names)

```typescript
const [context, setContext] = useState<IncidentContext | null>(null);
const [assessment, setAssessment] = useState<AssessmentResult | null>(null);
const [actions, setActions] = useState<ActionItem[]>([]);
const [busy, setBusy] = useState<string | null>(null);
const [error, setError] = useState<string | null>(null);
const [approvalOpen, setApprovalOpen] = useState(false);
const [traceOpen, setTraceOpen] = useState(false);
const [initialLoadHold, setInitialLoadHold] = useState(true);
```

No other state variables. Remove `activePane`, `situationOpen`, `traceEvents`, `integrationStatus`, `evalResult`, `contactInputs`.

---

## Demo stage logic

```typescript
type DemoStage = "incident" | "assessing" | "reasoning" | "approving" | "executed";

function inferStage(assessment: AssessmentResult | null, actions: ActionItem[], busy: string | null): DemoStage {
  if (busy === "assessment") return "assessing";
  if (!assessment) return "incident";
  const executedCount = actions.filter(a => ["executed", "sent"].includes(a.status)).length;
  if (executedCount > 0) return "executed";
  if (assessment.approval.status === "approved") return "executed";
  if (assessment) return assessment.plan.requires_approval ? "approving" : "reasoning";
  return "reasoning";
}
```

After `runAssessment()` completes: set assessment, set actions, do NOT auto-open trace. Instead auto-advance stage to `"reasoning"`.

---

## Async handlers

```typescript
async function runWithBusy(key: string, task: () => Promise<void>) {
  setBusy(key);
  setError(null);
  try { await task(); }
  catch (err) { setError(err instanceof Error ? err.message : "Operation failed."); }
  finally { setBusy(null); }
}

async function handleReset() {
  await runWithBusy("reset", async () => {
    await resetDemo();
    setAssessment(null);
    setActions([]);
    setApprovalOpen(false);
    setTraceOpen(false);
    const nextContext = await getCurrentIncident();
    setContext(nextContext);
  });
}

async function handleAssessment() {
  await runWithBusy("assessment", async () => {
    const result = await runAssessment();
    setAssessment(result);
    setContext(result.context);
    setActions(result.actions);
  });
}

async function handleApprove() {
  if (!assessment) return;
  await runWithBusy("approve", async () => {
    const result = await approveBundle(assessment.approval.approval_id);
    setActions(result.actions);
    setAssessment({ ...assessment, approval: result.approval, actions: result.actions });
    setApprovalOpen(false);
  });
}

async function handleExecute() {
  if (!assessment) return;
  await runWithBusy("execute", async () => {
    const result = await executeBundle(assessment.bundle_id);
    const nextActions = [...result.executed, ...result.failed, ...(result.skipped || [])];
    setActions(nextActions);
    setAssessment({ ...assessment, actions: nextActions });
  });
}
```

Initial load in `useEffect`:
```typescript
useEffect(() => {
  getCurrentIncident()
    .then(setContext)
    .catch(() => setError("Could not load incident data."));
}, []);

useEffect(() => {
  const t = window.setTimeout(() => setInitialLoadHold(false), 1200);
  return () => window.clearTimeout(t);
}, []);
```

---

## TOPBAR component

Fixed, 56px tall, full width. Dark background `#1c2127`. Flex row, items centered, px-4.

**Left side:**
- FireGuard logo: red shield icon (Blueprint `"shield"` icon, size 18, color `#e05a5a`) followed by text `"FireGuard"` in white, font-bold, text-sm, tracking-widest, uppercase.
- Small separator `·` in `text-gray-600`
- Text `"Wildfire Evacuation Agent"` in `text-gray-400 text-xs`

**Center:** Step pills — 3 steps:

```
① INCIDENT  ──  ② ASSESS  ──  ③ RESPOND
```

Render as a flex row gap-0. Each step:
- Circle number (18px, border, flex-center, text-xs)
- Label text-xs uppercase tracking-wider
- Connecting line `──` between steps (not after last)

Step states:
- **active** (current stage): circle bg `#e05a5a`, text white, label text white
- **completed** (past stage): circle bg `#394b59`, text `#8a9ba8`, label `#8a9ba8`, connecting line `#394b59`
- **upcoming**: circle border `#394b59`, text `#5c7080`, label `#5c7080`, connecting line `#293742`

Stage → step mapping:
- `"incident"` → step 1 active
- `"assessing"` → step 2 active
- `"reasoning"` → step 2 active
- `"approving"` → step 2 completed, step 3 active
- `"executed"` → all completed

**Right side:**
- If `busy` is set: small spinner (Blueprint `Spinner` size=16) + text matching busy key:
  - `"reset"` → `"Resetting..."`
  - `"assessment"` → `"Gemini is reasoning..."`
  - `"approve"` → `"Approving..."`
  - `"execute"` → `"Executing..."`
- Reset button: Blueprint `Button`, minimal, icon `"refresh"`, text `"Reset"`, small, onClick=handleReset, disabled when busy

---

## LEFT PANEL

Width 360px, fixed. `height: calc(100vh - 56px)`. `overflow-y: auto`. Background `#1c2127`. Border-right `1px solid #293742`.

Content depends on `stage`:

### Stage: `"incident"` (no assessment yet)

**Section: INCIDENT OVERVIEW**

Title row: `"INCIDENT"` label in `text-gray-500 text-xs uppercase tracking-widest`, font-medium. No border, just padding-top 24px, px-5.

**Fire signals** (from `context.fires`, show up to 3):
For each fire, render a compact row:
- Red dot (6px, `bg-red-500`, rounded-full, animate-pulse)
- Text: `"Active hotspot"` text-sm text-white
- Sub-text: `fire.source` in text-xs text-gray-400

If `context.fires.length > 3`: show `+{n} more hotspots` in text-xs text-gray-500.

**Zone risk rows** (from `context.zones`, show all):
For each zone, render:
```
ZONE NAME                      [RISK LEVEL TAG]
Pop: {population}  ·  Vuln: {vulnerable_count}
```
Zone name: text-sm font-medium text-white
Risk level tag: Blueprint `Tag` with intent from risk level (CRITICAL/HIGH→DANGER, MODERATE→WARNING, LOW→SUCCESS). Text: the risk level string.
Sub-line: text-xs text-gray-500.

But zone risk comes from `assessment?.plan.zone_risks`. If no assessment yet, just show zone names and pop/vuln counts without risk tags.

**Road events** (from `context.road_events`, show up to 2):
Compact row:
- Yellow dot (6px, `bg-yellow-500`, rounded-full)
- `road_event.title` text-sm text-white (truncate to 42 chars)
- Sub-text: `road_event.road_name` text-xs text-gray-400

**Separator** `<hr className="border-gray-700 mx-5 my-4" />`

**CTA button — full width:**
```
[  Run Gemini Assessment  ]
```
Blueprint `Button`, large, intent=DANGER, fill=true, icon=`"predictive-analysis"`, loading when `busy === "assessment"`, disabled when busy or no context, onClick=handleAssessment.
Below button: text-xs text-gray-500 text-center mt-2:
`"Gemini will reason from fire, route, shelter, and zone data"`

---

### Stage: `"assessing"` (busy === "assessment")

Show a centered loading state in the left panel:

Large centered area (pt-12, px-5):
- Blueprint `Spinner` size=50, intent=DANGER
- Text `"Gemini is reasoning..."` text-sm text-white text-center mt-4 font-medium
- Sub-text `"Calling tools, assessing routes, composing the staged plan"` text-xs text-gray-400 text-center mt-2

Below, a faint animation list showing tool call simulation:
```
✓ get_operational_brief
✓ inspect_route_options
⟳ search_operational_memory
```
Use `animate-pulse` on the spinning one. Show these as text-xs font-mono text-gray-500 with appropriate checkmarks/spinner chars. Just hardcode these 3 items — they are representative of the real tool calls Gemini makes.

---

### Stage: `"reasoning"` or `"approving"` (assessment exists)

**Section: GEMINI PLAN**

Title row `"GEMINI PLAN"` label, same style as above.

**Strategy block** (pt-4 px-5):
Large strategy display:
- Strategy text: `assessment.plan.recommended_strategy` transformed:
  - `"staged_evacuation"` → `"Staged Evacuation"`
  - `"evacuate_now"` → `"Evacuate Now"`
  - `"shelter_in_place"` → `"Shelter in Place"`
  - `"monitor"` → `"Monitor"`
  - `"dispatch_assisted"` → `"Dispatch Assisted"`
- Render as text-xl font-bold text-white
- On the same line (flex justify-between): confidence percentage:
  `"{Math.round(assessment.plan.confidence * 100)}%"` in text-xl font-bold, color by confidence:
  - ≥0.8 → `text-green-400`
  - ≥0.6 → `text-yellow-400`
  - else → `text-red-400`
- Below: Blueprint `ProgressBar` value={assessment.plan.confidence} intent based on same thresholds, stripes=false, animate=false. Height via className `"h-1 mt-1"`.

**Planning mode tag** (mt-2):
Blueprint `Tag` minimal:
- `"gemini_selected"` → intent=SUCCESS, text `"Gemini · direct"`
- `"gemini_repaired"` → intent=WARNING, text `"Gemini · repaired"`
- else → intent=NONE, text `"no gemini"`

**Separator**

**Zone steps** (from `assessment.plan.steps`):
For each step:
```
[ZONE NAME]                    [STRATEGY TAG]
{step.message truncated to 72 chars}
+{N} min delay    (only if start_after_minutes > 0)
```
Zone name: text-sm font-medium text-white
Strategy tag: Blueprint `Tag` small, intent:
- `"evacuate_now"` / `"staged_evacuation"` → DANGER
- `"shelter_in_place"` / `"dispatch_assisted"` / `"shelter_in_place_dispatch_assisted"` → WARNING
- `"monitor"` → NONE

Message: text-xs text-gray-400 mt-1 (strip `"[DEMO - FireGuard] "` prefix if present)

Delay: text-xs text-blue-400 mt-1 (only if > 0): `"Starts +{start_after_minutes} min"`

Separate each step with a light inner border.

**Separator**

**Approval CTA:**

If `assessment.plan.requires_approval` and `assessment.approval.status === "pending"`:
```
[  Review & Approve  ]
```
Blueprint `Button`, intent=WARNING, fill=true, icon=`"tick-circle"`, loading when `busy === "approve"`, onClick=`() => setApprovalOpen(true)`.
Sub-text: text-xs text-gray-500 text-center mt-1: `"{actions.filter(a => a.requires_human_approval).length} actions awaiting commander approval"`

If `assessment.approval.status === "approved"` and executed count is 0:
```
[  Execute Approved Actions  ]
```
Blueprint `Button`, intent=SUCCESS, fill=true, icon=`"play"`, loading when `busy === "execute"`, onClick=handleExecute.

---

### Stage: `"executed"` (actions have been executed)

**Section: MISSION COMPLETE**

Centered area (pt-8 px-5):
- Blueprint icon `"tick-circle"` size=32 color `#3dcc91` (green)
- Text `"Actions Dispatched"` text-lg font-bold text-white text-center mt-3
- Sub-text `"Commander-approved actions have been executed"` text-xs text-gray-400 text-center mt-2

**Action results** (from `actions`, show all):
For each action, compact row:
- Action type icon (use Blueprint icons):
  - `"resident_sms"` → `"mobile-phone"`
  - `"shelter_notify"` → `"home"`
  - `"road_ops_task"` → `"road"`
  - `"dispatch_task"` → `"drive-time"`
  - default → `"dot"`
- Action type text-xs text-gray-300
- Target text-xs text-gray-500
- Status tag: Blueprint `Tag` small, intent from status (`"executed"/"sent"` → SUCCESS, `"failed"` → DANGER, `"pending"` → WARNING)

**Separator**

Button row: `"Reset Demo"` Blueprint Button minimal icon=`"refresh"` onClick=handleReset, disabled when busy.

---

## CENTER: MAP

Always visible. `MapPanel` component with all existing props. The map fills the center column.

When no assessment: map takes full remaining height `calc(100vh - 56px)`.

When assessment exists: map height is `calc(100vh - 56px - 340px)` and the Gemini Panel occupies the bottom 340px. Use a CSS transition on height: `transition: height 0.4s ease`.

Pass to MapPanel:
- `context` (always)
- `assessment` (when exists, else null)
- All existing props the MapPanel already accepts — check MapPanel.tsx for its prop interface and pass everything it expects.

---

## CENTER: GEMINI PANEL (bottom, only when assessment exists)

Height 340px. Background `#1c2127`. Border-top `1px solid #293742`. Overflow hidden with inner scroll.

This is the **centerpiece of the demo** — show Gemini's actual reasoning prominently.

### Layout

Horizontal flex row, full width, full height:

**Column 1: Incident Summary + Tool Calls** (width 35%, border-right `1px solid #293742`, padding 20px, overflow-y auto)

Header: `"GEMINI REASONING"` text-xs uppercase tracking-widest text-gray-500 font-medium mb-3

**Incident summary** (from `assessment.plan.summary`):
text-sm text-white leading-relaxed. Show full text, no truncation. This is Gemini's voice — make it prominent.

**Tool calls** (from `assessment.gemini_tool_calls`, show as a timeline):
Section label: `"TOOLS CALLED"` text-xs uppercase tracking-widest text-gray-600 mt-4 mb-2.

For each tool call (array of strings), render a vertical timeline item:
```
●──  get_operational_brief
●──  inspect_route_options
●──  search_operational_memory
```
Use a small circle (6px, `bg-blue-500` or `bg-gray-600`) connected by a vertical line (1px, `bg-gray-700`). Tool name: text-xs font-mono text-blue-300.

If `assessment.gemini_tool_calls` is empty or null, show `"No tool calls recorded"` text-xs text-gray-600.

**Column 2: Plan Steps with Rationale** (width 40%, border-right `1px solid #293742`, padding 20px, overflow-y auto)

Header: `"PLAN STEPS"` text-xs uppercase tracking-widest text-gray-500 font-medium mb-3

For each step in `assessment.plan.steps`:

**Step card** (mb-4, pb-4, border-bottom `1px solid #293742` except last):
```
ZONE_B  [staged_evacuation]              +0 min
"Prepare Zone B first toward Railyard..."
  ↳ Gemini chose Zone B first to reduce corridor pressure.
```

Line 1: flex justify-between
- Left: zone_id text-xs font-mono text-gray-400 + strategy tag (Blueprint Tag, small, intent as above)
- Right: if start_after_minutes > 0: `"+{N} min"` text-xs text-blue-400, else `"immediate"` text-xs text-green-400

Line 2 (mt-1): step.message stripped of `"[DEMO - FireGuard] "` prefix. text-sm text-white.

Line 3+ (mt-1, ml-2): for each item in `step.rationale` (show first 2):
`"↳ {rationale}"` text-xs text-gray-500 italic

Evidence count (mt-1): `"{step.evidence_ids.length} evidence sources"` text-xs text-gray-600

**Column 3: Rejected Alternatives + Data Gaps** (width 25%, padding 20px, overflow-y auto)

**Rejected alternatives** section:
Header: `"CONSIDERED & REJECTED"` text-xs uppercase tracking-widest text-gray-500 font-medium mb-3

For each item in `assessment.plan.rejected_alternatives` (show up to 4):
```
ZONE_A → SHELTER_A
Route intersects DriveBC closure, active fire-risk...
```
Origin+destination: `"{alt.origin_id} → {alt.destination_id || 'none'}"` text-xs font-mono text-red-400
Reason: text-xs text-gray-500 mt-1 (truncate to 80 chars)
Separator: light bottom border

**Data gaps** section (if `assessment.gemini_decision?.data_gaps` exists and has items):
Section label: `"DATA GAPS"` text-xs uppercase tracking-widest text-gray-600 mt-4 mb-2

For each data gap string (from `assessment.gemini_decision?.data_gaps as string[]`, show up to 3):
```
⚠ Shelter capacity is operator-confirmed...
```
Icon `⚠` + text-xs text-yellow-600

**Risks if wrong** section (from `assessment.plan.risks_if_wrong`, show first 2):
Section label: `"RISKS IF WRONG"` text-xs uppercase tracking-widest text-gray-600 mt-4 mb-2
For each: `"• {risk}"` text-xs text-gray-600 (truncate to 60 chars)

---

## APPROVAL DIALOG

Triggered by `approvalOpen`, closed by `setApprovalOpen(false)`.

Blueprint `Dialog`, title `"Commander Approval Required"`, icon `"tick-circle"`, isOpen={approvalOpen}, onClose=`() => setApprovalOpen(false)`. className `"bp6-dark"`. style: width 540px.

**Dialog body:**

Blueprint `Callout` intent=WARNING title=`"Public-facing actions require your approval"`:
Text: `"The following actions will be dispatched to residents, shelters, and road operations upon approval. This cannot be undone."` text-sm.

**Plan summary** (mt-4):
`assessment?.plan.summary` — full text, text-sm text-gray-300.

**Action list** (mt-4):
For each action in `actions` where `action.requires_human_approval === true`:

Row (flex, gap-3, py-2, border-bottom `1px solid #293742`):
- Left: action type icon (same icon mapping as above), size 16, color `#5c7080`
- Center:
  - `action.action_type` text-xs font-medium text-white uppercase
  - `"→ {action.target}"` text-xs text-gray-400
  - `action.message` (strip `"[DEMO - FireGuard] "` prefix) text-xs text-gray-500 mt-1 (max 2 lines, truncate)
- Right: omit — do not show any simulated/live status tag

**Dialog footer buttons:**
- Cancel: Blueprint Button minimal `"Cancel"` onClick=`() => setApprovalOpen(false)` disabled when busy
- Approve: Blueprint Button intent=WARNING `"Approve and Proceed"` icon=`"tick"` loading when `busy === "approve"` onClick=handleApprove

---

## TRACE DIALOG

Triggered by `traceOpen`, closed by `setTraceOpen(false)`.

Add a `"View Gemini Trace"` button to the topbar right side (only when `assessment` exists). Blueprint Button minimal small icon=`"code-block"` text=`"Trace"` onClick=`() => setTraceOpen(true)`.

Blueprint `Dialog`, title `"Gemini Agent Trace"`, isOpen={traceOpen}, onClose=`() => setTraceOpen(false)`. className `"bp6-dark"`. style: width 720px, maxHeight `"80vh"`.

**Dialog body** (overflow-y auto, max-height calc(80vh - 120px)):

**Section 1: Agent Summary**
Two-column grid:
- Planning mode: label `"Planning Mode"` text-xs text-gray-500, value as Tag (same as left panel)
- Validation: label `"Validation"` text-xs text-gray-500, value: Tag intent=SUCCESS text=`"valid"` if `assessment?.plan_validation?.valid`, else Tag intent=DANGER text=`"errors"`
- Confidence: label `"Confidence"` text-xs text-gray-500, value: `"{Math.round(assessment.plan.confidence*100)}%"` text-sm
- Tool calls: label `"Tool Calls"` text-xs text-gray-500, value: `"{assessment.gemini_tool_calls?.length || 0}"` text-sm

**Section 2: Full Gemini Decision** (if `assessment.gemini_decision` exists)
Header `"GEMINI DECISION OUTPUT"` text-xs uppercase tracking-widest text-gray-500 mt-4 mb-2
Render as:
```jsx
<pre className="fg-trace-pre">
  {JSON.stringify(assessment.gemini_decision, null, 2)}
</pre>
```
Use CSS class `fg-trace-pre` (defined in globals.css additions below): `font-size: 11px; color: #8a9ba8; background: #161d24; border-radius: 4px; padding: 12px; overflow-x: auto; max-height: 400px; overflow-y: auto; white-space: pre-wrap; word-break: break-word;`

**Section 3: Validation errors** (if `assessment.validation_errors?.length > 0`)
Header `"VALIDATION NOTES"` same style mt-4 mb-2
For each error: text-xs text-yellow-600 `"• {error}"`

**Section 4: Eval result** — remove (not fetched anymore)

---

## Error display

If `error` is set, show at the top of left panel (below topbar edge, inside left panel, sticky top-0):
Blueprint `Callout` intent=DANGER title=`"Error"` className `"m-3 text-xs"`:
`{error}` — truncate to 120 chars.

---

## Initial loading state

While `showInitialLoader` (= `!error && (!context || initialLoadHold)`):

Overlay the entire screen (fixed, inset-0, `bg-[#1c2127]`, z-50, flex items-center justify-center):
- Blueprint `Spinner` size=40 intent=DANGER
- Text `"Loading FireGuard..."` text-sm text-gray-400 mt-4

---

## Helper functions to keep

Keep these from current page.tsx (they are used above):
```typescript
function intentForRisk(level: string): Intent { ... }
function intentForStatus(status: string): Intent { ... }
function shortText(value: string, maxLength: number): string { ... }
function stringify(value: unknown, fallback?: string): string { ... }
```

Remove: `planningModeText`, `intentForPlanningMode`, `operatorText`, `publicValidationErrorText`, `decisionRecordCount`, `liveOverlayRecordCount`, `inferDemoStage`, `asRecordArray`, `DEMO_STAGES`, `STAGE_COPY`.

---

## Imports

Keep all existing imports that are still used. Remove unused ones. The full import list:

```typescript
"use client";

import {
  Button,
  Callout,
  Classes,
  Dialog,
  Icon,
  Intent,
  ProgressBar,
  Spinner,
  Tag,
} from "@blueprintjs/core";
import { useEffect, useMemo, useState } from "react";
import { MapPanel } from "@/components/MapPanel";
import {
  approveBundle,
  executeBundle,
  getCurrentIncident,
  resetDemo,
  runAssessment,
} from "@/lib/api";
import type { ActionItem, AssessmentResult, IncidentContext } from "@/lib/types";
```

Remove imports for: `approveBundle` is still needed (above). `H4`, `H5`, `InputGroup`, `NonIdealState`, `ButtonGroup` — remove if not used. Only import Blueprint components that appear in the final code.

---

## MapPanel props

Check `/apps/web/src/components/MapPanel.tsx` for its exact prop interface. Pass everything it needs. At minimum:
- `context`
- `assessment`

If MapPanel has additional required props, provide them. Do not change MapPanel.tsx.

---

## CSS additions to globals.css

Append to `/apps/web/src/app/globals.css`:

```css
/* FireGuard Gemini Panel */
.fg-gemini-panel {
  display: flex;
  flex-direction: row;
  height: 340px;
  background: #1c2127;
  border-top: 1px solid #293742;
  overflow: hidden;
  transition: opacity 0.3s ease;
}

.fg-gemini-col {
  overflow-y: auto;
  padding: 20px;
  scrollbar-width: thin;
  scrollbar-color: #394b59 transparent;
}

.fg-gemini-col::-webkit-scrollbar { width: 4px; }
.fg-gemini-col::-webkit-scrollbar-track { background: transparent; }
.fg-gemini-col::-webkit-scrollbar-thumb { background: #394b59; border-radius: 2px; }

.fg-trace-pre {
  font-size: 11px;
  color: #8a9ba8;
  background: #161d24;
  border-radius: 4px;
  padding: 12px;
  overflow-x: auto;
  max-height: 400px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
}

/* Tool call timeline */
.fg-tool-timeline {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.fg-tool-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  position: relative;
}

.fg-tool-item:not(:last-child)::after {
  content: '';
  position: absolute;
  left: 5px;
  top: 14px;
  bottom: -8px;
  width: 1px;
  background: #293742;
}

.fg-tool-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #2d72d2;
  flex-shrink: 0;
  margin-top: 3px;
}

/* Map height transitions */
.fg-map-container {
  transition: height 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
}

/* Step pills */
.fg-step-pill {
  display: flex;
  align-items: center;
  gap: 6px;
}

.fg-step-circle {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 600;
  flex-shrink: 0;
  border: 1px solid transparent;
}

.fg-step-line {
  width: 32px;
  height: 1px;
  background: #293742;
  margin: 0 4px;
}

.fg-step-line.completed {
  background: #394b59;
}

/* Step card in left panel */
.fg-step-card {
  padding: 12px 0;
  border-bottom: 1px solid #252e38;
}

.fg-step-card:last-child {
  border-bottom: none;
}

/* Left panel section labels */
.fg-section-label {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: #5c7080;
  padding: 20px 20px 8px 20px;
}

/* Rejected alternative rows */
.fg-rejected-row {
  padding: 8px 0;
  border-bottom: 1px solid #252e38;
}

.fg-rejected-row:last-child {
  border-bottom: none;
}
```

---

## Constraints and things NOT to add

- **No right panel.** No mission brief. No provider health chips.
- **No analytics row** (zone risk summary cards, route split bar, action state bar).
- **No tabs/panes** (Overview, Sources, Evidence, Actions, Audit, Diagnostics — all gone).
- **No numeric stat chips** like "45 fires", "3 roads", "5 ESS sites", "50 renders".
- **No wildfire_evacuation_trigger** field (it was removed from the backend).
- **No `candidate_facts_summary` display** in the UI.
- **No eval score display** in main UI (only in trace dialog if you want, but not required).
- **No Fivetran sync buttons** in the main flow.
- **No shelter capacity confirm buttons** in main flow.
- **No resident contact inputs** in main flow.
- **No situation alert dialog**.
- **No diagnostics panel**.
- **Do not add any component, stat, chip, badge, or section not explicitly described in this spec.**
- The map must always be visible. Do not hide it behind tabs.
- All text referencing `"[DEMO - FireGuard] "` prefix in messages: strip it before displaying in the UI.

---

## Exact file structure of page.tsx

Organize the file in this order:

1. `"use client"` directive
2. All imports
3. Type definitions (`DemoStage`)
4. Helper functions (`intentForRisk`, `intentForStatus`, `shortText`, `stringify`, `inferStage`)
5. `export default function Home()` containing:
   a. All useState declarations
   b. useMemo for stage
   c. useEffect hooks
   d. All async handlers
   e. Derived variables (publicActionCount, executedCount, showInitialLoader)
   f. Return JSX:
      - Initial loader overlay (conditional)
      - Main layout div (flex column, h-screen)
        - Topbar
        - Content row (flex-1, flex-row)
          - Left panel
          - Center column (flex-1, flex-col)
            - Map container
            - Gemini panel (conditional)
      - Approval Dialog
      - Trace Dialog

---

## Quality bar

The finished page.tsx must:
- Compile without TypeScript errors
- Not use any removed imports
- Show a clean, story-driven UI with exactly the sections described
- Have the Gemini panel appear after assessment with a smooth height transition on the map
- The left panel must scroll independently if content overflows
- The approval dialog must list all approval-gated actions with their messages
- The trace dialog must render the gemini_decision JSON

If anything in this spec is ambiguous, choose the simpler/cleaner implementation.
